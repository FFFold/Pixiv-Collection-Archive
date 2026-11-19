import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import utcnow
from pixiv_archive.db.repo import bookmarks, downloads, illusts, sync_runs
from pixiv_archive.media.downloader import ImageDownloader
from pixiv_archive.media.storage import WorksStorage, atomic_write_bytes
from pixiv_archive.media.thumbnails import is_valid_image
from pixiv_archive.pixiv.client import PixivClient
from pixiv_archive.pixiv.errors import PixivError
from pixiv_archive.pixiv.models import Illust as PixivIllust
from pixiv_archive.sync import rank as rank_mod
from pixiv_archive.sync.unavailable import is_unavailable

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, int, int, str], None]

RESTRICTS = ("public", "private")
PREVIEW_ATTEMPTS_LIMIT = 5
UGOIRA_META_ATTEMPTS_LIMIT = 5


@dataclass
class SyncResult:
    run_id: int
    kind: str
    status: str = "completed"
    pages_fetched: int = 0
    new_count: int = 0
    unbookmarked_count: int = 0
    deleted_count: int = 0
    rank_rebuilt_count: int = 0
    previews_fetched: int = 0
    previews_failed: int = 0
    previews_pending: int = 0
    ugoira_meta_fetched: int = 0
    failed_count: int = 0
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class AssetRepairResult:
    reset: int = 0
    previews_fetched: int = 0
    previews_failed: int = 0
    previews_pending: int = 0
    ugoira_fetched: int = 0
    ugoira_failed: int = 0


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
            observed: list[tuple[PixivIllust, str]] = []
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
                    observed.extend((illust, restrict) for illust in page.illusts)
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
            pending_ranks: dict[int, int] = {
                illust.pid: rank_value
                for (illust, _), rank_value in zip(discovered, ranks, strict=True)
            }

            async with self._db.session() as session:
                existing_states = await illusts.get_illust_states(session)

                for illust, restrict in observed:
                    known = illust.pid in known_pids
                    unavailable = is_unavailable(illust)
                    if known and not unavailable:
                        if existing_states.get(illust.pid) != "deleted":
                            continue
                        await illusts.upsert_illust(
                            session, illust, meta_json=self._meta_json(illust)
                        )
                        self._save_meta(illust, result)
                        rank_value = await bookmarks.get_rank(session, illust.pid)
                        await bookmarks.set_active_rank(
                            session,
                            pid=illust.pid,
                            restrict=restrict,
                            rank=rank_value if rank_value is not None else 0,
                            now=now,
                        )
                        continue
                    if not unavailable:
                        continue
                    rank_value = pending_ranks.get(illust.pid)
                    if rank_value is None:
                        current = await bookmarks.get_rank(session, illust.pid)
                        if current is None:
                            continue
                        rank_value = current
                    if await self._handle_unavailable(
                        session, illust, restrict=restrict, rank=rank_value
                    ):
                        result.deleted_count += 1

                for (illust, restrict), rank_value in zip(discovered, ranks, strict=True):
                    if is_unavailable(illust):
                        continue
                    try:
                        await illusts.upsert_illust(
                            session, illust, meta_json=self._meta_json(illust)
                        )
                        self._save_meta(illust, result)
                        await bookmarks.set_active_rank(
                            session,
                            pid=illust.pid,
                            restrict=restrict,
                            rank=rank_value,
                            now=now,
                        )
                        result.new_count += 1
                    except Exception as exc:  # noqa: BLE001 - keep the batch going
                        result.failed_count += 1
                        result.warnings.append(f"作品 {illust.pid} 元数据写入失败: {exc}")
                await session.commit()

            await self._finalize(result)
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

            async with self._db.session() as session:
                for illust, restrict, pos in listed:
                    try:
                        rank_value = rank_mod.full_rank(pos)
                        if is_unavailable(illust):
                            deleted = await self._handle_unavailable(
                                session, illust, restrict=restrict, rank=rank_value
                            )
                            if deleted:
                                result.deleted_count += 1
                            continue
                        await illusts.upsert_illust(
                            session, illust, meta_json=self._meta_json(illust)
                        )
                        self._save_meta(illust, result)
                        was_known = illust.pid in known_pids
                        await bookmarks.set_active_rank(
                            session,
                            pid=illust.pid,
                            restrict=restrict,
                            rank=rank_value,
                            now=now,
                        )
                        if was_known:
                            if old_ranks.get(illust.pid) != rank_value:
                                result.rank_rebuilt_count += 1
                        else:
                            result.new_count += 1
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

            await self._finalize(result)
            result.status = "cancelled" if self._cancel.is_set() else "completed"
        except Exception as exc:  # noqa: BLE001 - persist failure then re-raise
            result.status = "failed"
            result.error = str(exc)
            await self._finish(result, started)
            raise
        await self._finish(result, started)
        return result

    async def _handle_unavailable(
        self, session: AsyncSession, illust: PixivIllust, *, restrict: str, rank: int
    ) -> bool:
        """Mark a pixiv stub as deleted, creating a bookmark-only row if new.

        Existing metadata, original URLs and downloaded files are left alone;
        only the state flag and bookmark position are written.
        """
        known = await illusts.get_illust_state(session, illust.pid) is not None
        if known:
            changed = await illusts.mark_illust_deleted(session, illust.pid)
        else:
            await illusts.create_placeholder_illust(session, pid=illust.pid)
            changed = True
        await bookmarks.set_active_rank(
            session, pid=illust.pid, restrict=restrict, rank=rank, now=utcnow()
        )
        await downloads.skip_jobs_for_pid(session, illust.pid)
        return changed

    async def _finalize(self, result: SyncResult) -> None:
        repair = await self.repair_assets()
        result.previews_fetched += repair.previews_fetched
        result.previews_failed += repair.previews_failed
        result.previews_pending = repair.previews_pending
        result.ugoira_meta_fetched += repair.ugoira_fetched
        result.failed_count += repair.ugoira_failed

    async def repair_assets(self, *, reset_failed: bool = False) -> AssetRepairResult:
        """Fetch every preview / ugoira metadata row that is not ready yet."""
        out = AssetRepairResult()
        if reset_failed:
            await self._reset_previews(out)
        if self._download_previews:
            await self._repair_previews(out)
        await self._repair_ugoira_metadata(out)
        async with self._db.session() as session:
            out.previews_pending = await illusts.count_previews_missing(session)
        return out

    async def _reset_previews(self, out: AssetRepairResult) -> None:
        async with self._db.session() as session:
            out.reset += await illusts.reset_failed_previews(session)
            ready = await illusts.get_ready_preview_pids(session)
            missing = [pid for pid in ready if not self._storage.has_preview(pid)]
            if missing:
                out.reset += await illusts.mark_previews_pending(session, missing)
            await session.commit()

    async def _repair_previews(self, out: AssetRepairResult) -> None:
        async with self._db.session() as session:
            backlog = await illusts.get_preview_backlog(
                session, max_attempts=PREVIEW_ATTEMPTS_LIMIT
            )
            present = [pid for pid in backlog if self._storage.has_preview(pid)]
            if present:
                await illusts.mark_previews_ready(session, present)
                await session.commit()
            missing = [pid for pid in backlog if pid not in set(present)]
            meta = await illusts.get_meta_json_map(session, missing) if missing else {}

        if not missing:
            return

        targets: list[tuple[int, str]] = []
        failures: list[tuple[int, str]] = []
        for pid in missing:
            url = self._preview_url(meta.get(pid))
            if url is None:
                failures.append((pid, "no preview url"))
            else:
                targets.append((pid, url))

        outcomes = await asyncio.gather(
            *(self._download_preview(pid, url) for pid, url in targets),
            return_exceptions=True,
        )
        succeeded: list[int] = []
        for (pid, _url), outcome in zip(targets, outcomes, strict=True):
            if outcome is None:
                succeeded.append(pid)
            elif isinstance(outcome, str):
                failures.append((pid, outcome))
            else:
                failures.append((pid, f"{type(outcome).__name__}: {outcome}"))

        async with self._db.session() as session:
            if succeeded:
                await illusts.mark_previews_ready(session, succeeded)
            for pid, error in failures:
                logger.warning("preview fetch failed for %s: %s", pid, error)
                await illusts.record_preview_failure(
                    session, pid, error=error, max_attempts=PREVIEW_ATTEMPTS_LIMIT
                )
            await session.commit()

        out.previews_fetched += len(succeeded)
        out.previews_failed += len(failures)

    async def _download_preview(self, pid: int, url: str) -> str | None:
        try:
            data = await self._downloader.fetch_bytes(url)
            if data is None:
                return "fetch failed"
            if not is_valid_image(data):
                return "invalid image data"
            atomic_write_bytes(self._storage.preview_path(pid), data)
        except Exception as exc:  # noqa: BLE001 - one target must not abort the batch
            return f"{type(exc).__name__}: {exc}"
        return None

    async def _repair_ugoira_metadata(self, out: AssetRepairResult) -> None:
        async with self._db.session() as session:
            backlog = await illusts.get_ugoira_meta_backlog(
                session, max_attempts=UGOIRA_META_ATTEMPTS_LIMIT
            )
        for pid in backlog:
            try:
                meta = await self._client.get_ugoira_metadata(pid)
            except PixivError as exc:
                logger.warning("ugoira metadata fetch failed for %s: %s", pid, exc)
                async with self._db.session() as session:
                    await illusts.record_ugoira_meta_failure(session, pid, error=str(exc))
                    await session.commit()
                out.ugoira_failed += 1
                continue
            frames_json = json.dumps(
                [frame.model_dump() for frame in meta.frames], ensure_ascii=False
            )
            async with self._db.session() as session:
                await illusts.upsert_ugoira_meta(
                    session,
                    pid=pid,
                    zip_url=meta.zip_url or "",
                    frames_json=frames_json,
                    frame_count=len(meta.frames),
                )
                await session.commit()
            out.ugoira_fetched += 1

    @staticmethod
    def _preview_url(meta_json: str | None) -> str | None:
        if not meta_json:
            return None
        try:
            payload = json.loads(meta_json)
        except ValueError:
            return None
        urls = payload.get("image_urls") or {}
        return urls.get("square_medium") or urls.get("medium")

    def _save_meta(self, illust: PixivIllust, result: SyncResult) -> None:
        try:
            payload = illust.model_dump(mode="json", by_alias=True)
            self._storage.save_meta_json(illust.pid, payload)
        except OSError as exc:
            result.warnings.append(f"作品 {illust.pid} meta.json 写入失败: {exc}")

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
