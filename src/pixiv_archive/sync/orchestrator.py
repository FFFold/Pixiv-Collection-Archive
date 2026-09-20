import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import utcnow
from pixiv_archive.db.repo import bookmarks, illusts, sync_runs
from pixiv_archive.media.downloader import ImageDownloader
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.pixiv.client import PixivClient
from pixiv_archive.pixiv.errors import PixivError
from pixiv_archive.pixiv.models import Illust as PixivIllust
from pixiv_archive.sync import rank as rank_mod

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, int, int, str], None]

RESTRICTS = ("public", "private")


@dataclass
class SyncResult:
    run_id: int
    kind: str
    status: str = "completed"
    pages_fetched: int = 0
    new_count: int = 0
    unbookmarked_count: int = 0
    rank_rebuilt_count: int = 0
    previews_fetched: int = 0
    previews_failed: int = 0
    ugoira_meta_fetched: int = 0
    failed_count: int = 0
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


class MetadataSyncService:
    """Implements stage A: bookmark metadata synchronisation."""

    def __init__(
        self,
        *,
        db: Database,
        client: PixivClient,
        storage: WorksStorage,
        downloader: ImageDownloader,
        download_previews: bool = True,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self._db = db
        self._client = client
        self._storage = storage
        self._downloader = downloader
        self._download_previews = download_previews
        self._on_progress = on_progress
        self._cancel = asyncio.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def set_download_previews(self, enabled: bool) -> None:
        """Override preview fetching for this run (used by the CLI flag)."""
        self._download_previews = enabled

    def _progress(self, phase: str, done: int, total: int, message: str) -> None:
        if self._on_progress is not None:
            self._on_progress(phase, done, total, message)

    async def run_incremental(self, *, max_pages: int | None = None) -> SyncResult:
        """Fetch the front of both bookmark lists and register new bookmarks."""
        self._cancel.clear()
        started = utcnow()
        async with self._db.session() as session:
            run_id = await sync_runs.create_run(session, "incremental", now=started)
            await session.commit()

        result = SyncResult(run_id=run_id, kind="incremental")
        try:
            async with self._db.session() as session:
                known_pids = await illusts.get_known_pids(session)
                states = await bookmarks.get_bookmark_states(session)
                min_rank = await bookmarks.get_min_rank(session)

            discovered: list[tuple[PixivIllust, str]] = []
            seen: set[int] = set()
            for restrict in RESTRICTS:
                cursor: int | None = None
                while not self._cancel.is_set():
                    page = await self._client.list_bookmarks(restrict, max_bookmark_id=cursor)
                    result.pages_fetched += 1
                    self._progress(
                        "fetch",
                        result.pages_fetched,
                        0,
                        f"读取{restrict}收藏第 {result.pages_fetched} 页",
                    )
                    if not page.illusts:
                        break
                    page_all_known = True
                    for illust in page.illusts:
                        if illust.pid in known_pids and states.get(illust.pid) != "unbookmarked":
                            continue
                        page_all_known = False
                        if illust.pid not in seen:
                            seen.add(illust.pid)
                            discovered.append((illust, restrict))
                    if page_all_known:
                        break
                    if page.next_bookmark_id is None:
                        break
                    cursor = page.next_bookmark_id
                    if max_pages is not None and result.pages_fetched >= max_pages:
                        break

            if self._cancel.is_set():
                result.status = "cancelled"
                await self._finish(result, started)
                return result

            ranks = rank_mod.incremental_ranks(min_rank, len(discovered))
            now = utcnow()
            preview_targets: list[PixivIllust] = []
            ugoira_targets: list[PixivIllust] = []

            async with self._db.session() as session:
                for (illust, restrict), rank_value in zip(discovered, ranks, strict=True):
                    try:
                        await illusts.upsert_illust(
                            session, illust, meta_json=self._meta_json(illust)
                        )
                        await bookmarks.set_active_rank(
                            session,
                            pid=illust.pid,
                            restrict=restrict,
                            rank=rank_value,
                            now=now,
                        )
                        result.new_count += 1
                        preview_targets.append(illust)
                        if illust.type == "ugoira":
                            ugoira_targets.append(illust)
                    except Exception as exc:  # noqa: BLE001 - keep the batch going
                        result.failed_count += 1
                        result.warnings.append(f"作品 {illust.pid} 元数据写入失败: {exc}")
                await session.commit()

            await self._finalize(result, preview_targets, ugoira_targets)
            result.status = "cancelled" if self._cancel.is_set() else "completed"
        except Exception as exc:  # noqa: BLE001 - persist failure then re-raise
            result.status = "failed"
            result.error = str(exc)
            await self._finish(result, started)
            raise
        await self._finish(result, started)
        return result

    async def run_full(self, *, max_pages: int | None = None) -> SyncResult:
        """Walk both bookmark lists completely, rebuilding ranks and states."""
        self._cancel.clear()
        started = utcnow()
        async with self._db.session() as session:
            run_id = await sync_runs.create_run(session, "full", now=started)
            await session.commit()

        result = SyncResult(run_id=run_id, kind="full")
        try:
            listed: list[tuple[PixivIllust, str, int]] = []
            position = 0
            truncated = False
            for restrict in RESTRICTS:
                cursor: int | None = None
                while not self._cancel.is_set():
                    page = await self._client.list_bookmarks(restrict, max_bookmark_id=cursor)
                    result.pages_fetched += 1
                    self._progress(
                        "fetch",
                        result.pages_fetched,
                        position,
                        f"读取{restrict}收藏第 {result.pages_fetched} 页",
                    )
                    if not page.illusts:
                        break
                    for illust in page.illusts:
                        listed.append((illust, restrict, position))
                        position += 1
                    if page.next_bookmark_id is None:
                        break
                    cursor = page.next_bookmark_id
                    if max_pages is not None and result.pages_fetched >= max_pages:
                        truncated = True
                        break
                if truncated:
                    break

            async with self._db.session() as session:
                known_pids = await illusts.get_known_pids(session)
                old_ranks = await bookmarks.get_rank_map(session)

            listed_pids = {illust.pid for illust, _, _ in listed}
            missing = sorted(pid for pid in known_pids if pid not in listed_pids)

            now = utcnow()
            preview_targets: list[PixivIllust] = []
            ugoira_targets: list[PixivIllust] = []

            async with self._db.session() as session:
                for illust, restrict, pos in listed:
                    try:
                        await illusts.upsert_illust(
                            session, illust, meta_json=self._meta_json(illust)
                        )
                        new_rank = rank_mod.full_rank(pos)
                        was_known = illust.pid in known_pids
                        await bookmarks.set_active_rank(
                            session,
                            pid=illust.pid,
                            restrict=restrict,
                            rank=new_rank,
                            now=now,
                        )
                        if was_known:
                            if old_ranks.get(illust.pid) != new_rank:
                                result.rank_rebuilt_count += 1
                        else:
                            result.new_count += 1
                        preview_targets.append(illust)
                        if illust.type == "ugoira":
                            ugoira_targets.append(illust)
                    except Exception as exc:  # noqa: BLE001 - keep the batch going
                        result.failed_count += 1
                        result.warnings.append(f"作品 {illust.pid} 元数据写入失败: {exc}")
                if truncated:
                    result.warnings.append("达到 max_pages 限制，未完成全量遍历，未标记取消收藏")
                else:
                    result.unbookmarked_count = await bookmarks.mark_unbookmarked(
                        session, missing, now=now
                    )
                await session.commit()

            await self._finalize(result, preview_targets, ugoira_targets)
            result.status = "cancelled" if self._cancel.is_set() else "completed"
        except Exception as exc:  # noqa: BLE001 - persist failure then re-raise
            result.status = "failed"
            result.error = str(exc)
            await self._finish(result, started)
            raise
        await self._finish(result, started)
        return result

    async def _finalize(
        self,
        result: SyncResult,
        works: list[PixivIllust],
        ugoira_works: list[PixivIllust],
    ) -> None:
        """Fetch previews and ugoira metadata, then write meta.json snapshots."""
        if self._download_previews:
            fetched, failed = await self._fetch_previews(works)
            result.previews_fetched += fetched
            result.previews_failed += failed
        ugoira_fetched, ugoira_failed = await self._fetch_ugoira_metadata(ugoira_works)
        result.ugoira_meta_fetched += ugoira_fetched
        result.failed_count += ugoira_failed
        for illust in works:
            try:
                payload = illust.model_dump(mode="json", by_alias=True)
                self._storage.save_meta_json(illust.pid, payload)
            except OSError as exc:
                result.warnings.append(f"作品 {illust.pid} meta.json 写入失败: {exc}")

    async def _fetch_previews(self, works: list[PixivIllust]) -> tuple[int, int]:
        targets: list[tuple[str, Path]] = []
        for illust in works:
            url = illust.preview_url
            if not url:
                continue
            dest = self._storage.preview_path(illust.pid)
            if dest.exists():
                continue
            targets.append((url, dest))
        if not targets:
            return 0, 0
        results = await asyncio.gather(
            *(self._downloader.fetch_to_file(url, dest) for url, dest in targets)
        )
        fetched = sum(1 for ok in results if ok)
        return fetched, len(results) - fetched

    async def _fetch_ugoira_metadata(self, works: list[PixivIllust]) -> tuple[int, int]:
        fetched = 0
        failed = 0
        for illust in works:
            try:
                meta = await self._client.get_ugoira_metadata(illust.pid)
            except PixivError:
                failed += 1
                continue
            frames_json = json.dumps(
                [frame.model_dump() for frame in meta.frames], ensure_ascii=False
            )
            async with self._db.session() as session:
                await illusts.upsert_ugoira_meta(
                    session,
                    pid=illust.pid,
                    zip_url=meta.zip_url or "",
                    frames_json=frames_json,
                    frame_count=len(meta.frames),
                )
                await session.commit()
            fetched += 1
        return fetched, failed

    def _meta_json(self, illust: PixivIllust) -> str:
        return json.dumps(illust.model_dump(mode="json"), ensure_ascii=False)

    async def _finish(self, result: SyncResult, started: datetime) -> None:
        async with self._db.session() as session:
            await sync_runs.finish_run(
                session,
                result.run_id,
                status=result.status,
                pages_fetched=result.pages_fetched,
                new_count=result.new_count,
                unbookmarked_count=result.unbookmarked_count,
                rank_rebuilt_count=result.rank_rebuilt_count,
                previews_fetched=result.previews_fetched,
                previews_failed=result.previews_failed,
                failed_count=result.failed_count,
                error=result.error,
                now=utcnow(),
            )
            await session.commit()
        logger.info(
            "sync run %s finished: status=%s new=%s pages=%s",
            result.run_id,
            result.status,
            result.new_count,
            result.pages_fetched,
        )
