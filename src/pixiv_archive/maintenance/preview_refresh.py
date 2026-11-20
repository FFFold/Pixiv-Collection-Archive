"""One-off re-download of every existing cover in the original aspect ratio."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

from pixiv_archive.db.engine import Database
from pixiv_archive.db.repo import illusts
from pixiv_archive.media.downloader import ImageDownloader
from pixiv_archive.media.preview import is_placeholder_url, preview_url_from_meta
from pixiv_archive.media.storage import WorksStorage, atomic_write_bytes
from pixiv_archive.media.thumbnails import is_valid_image

logger = logging.getLogger(__name__)

REFRESH_BATCH = 50
REFRESH_ATTEMPTS_LIMIT = 5

ProgressCallback = Callable[[str, int, int, str], None]


@dataclass
class RefreshReport:
    total: int = 0
    fetched: int = 0
    failed: int = 0
    remaining: int = 0
    skipped: int = 0
    resumed: bool = False


class PreviewRefresher:
    """Re-fetch covers for works that only have a square-cropped preview.

    Works are queued by moving them to ``preview_state='stale'``; the queue
    lives in the database, so an interrupted run resumes where it stopped and
    the sync backlog never mistakes a queued work for a finished one.
    """

    def __init__(
        self,
        *,
        db: Database,
        storage: WorksStorage,
        downloader: ImageDownloader,
    ) -> None:
        self._db = db
        self._storage = storage
        self._downloader = downloader

    async def run(
        self, *, restart: bool = False, on_progress: ProgressCallback | None = None
    ) -> RefreshReport:
        out = RefreshReport()
        async with self._db.session() as session:
            stale_now = await illusts.count_previews_stale(session)
            if restart or stale_now == 0:
                await illusts.mark_previews_stale(session, all_active=True)
            else:
                out.resumed = True
            await illusts.mark_previews_stale(session, all_active=False)
            await session.commit()
            attemptable = await illusts.get_stale_preview_pids(
                session, max_attempts=REFRESH_ATTEMPTS_LIMIT
            )
            out.total = len(attemptable)
            out.skipped = await illusts.count_previews_stale_exhausted(
                session, max_attempts=REFRESH_ATTEMPTS_LIMIT
            )

        if on_progress is not None:
            on_progress("refresh-previews", 0, out.total, f"重抓封面 0/{out.total}")

        done = 0
        attempted: set[int] = set()
        while True:
            async with self._db.session() as session:
                pending = await illusts.get_stale_preview_pids(
                    session, max_attempts=REFRESH_ATTEMPTS_LIMIT
                )
                batch = [pid for pid in pending if pid not in attempted][:REFRESH_BATCH]
                meta = await illusts.get_meta_json_map(session, batch) if batch else {}
            if not batch:
                break
            attempted.update(batch)

            outcomes = await asyncio.gather(
                *(self._refresh_one(pid, meta.get(pid)) for pid in batch),
                return_exceptions=True,
            )
            succeeded: list[int] = []
            failures: list[tuple[int, str]] = []
            for pid, outcome in zip(batch, outcomes, strict=True):
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
                    logger.warning("preview refresh failed for %s: %s", pid, error)
                    await illusts.record_refresh_failure(session, pid, error=error)
                await session.commit()

            out.fetched += len(succeeded)
            out.failed += len(failures)
            done += len(batch)
            if on_progress is not None:
                on_progress("refresh-previews", done, out.total, f"重抓封面 {done}/{out.total}")

        async with self._db.session() as session:
            out.remaining = await illusts.count_previews_stale(session)
        return out

    async def _refresh_one(self, pid: int, meta_json: str | None) -> str | None:
        url = preview_url_from_meta(meta_json)
        if url is None:
            return "no preview url"
        if is_placeholder_url(url):
            return "placeholder url"
        try:
            data = await self._downloader.fetch_bytes(url)
            if data is None:
                return "fetch failed"
            if not is_valid_image(data):
                return "invalid image data"
            # Atomic: a failure above never touches the existing cover.
            atomic_write_bytes(self._storage.preview_path(pid), data)
        except Exception as exc:  # noqa: BLE001 - one target must not abort the batch
            return f"{type(exc).__name__}: {exc}"
        return None
