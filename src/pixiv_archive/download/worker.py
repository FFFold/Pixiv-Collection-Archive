import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Illust, IllustPage, UgoiraMeta, utcnow
from pixiv_archive.db.repo import downloads
from pixiv_archive.download.scope import DownloadScope, resolve_scope
from pixiv_archive.media.storage import WorksStorage, atomic_write_bytes
from pixiv_archive.media.thumbnails import generate_thumb, is_valid_image
from pixiv_archive.media.ugoira import transcode_to_mp4

TranscodeFn = Callable[..., Awaitable[bool]]

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp")


class BytesDownloader(Protocol):
    """The subset of ImageDownloader the worker depends on."""

    async def fetch_bytes(self, url: str) -> bytes | None: ...

    async def fetch_to_file(self, url: str, dest: Path) -> bool: ...


@dataclass
class DownloadWorkerConfig:
    concurrency: int = 4
    max_attempts: int = 3
    ffmpeg_bin: str = "ffmpeg"
    transcode: TranscodeFn | None = None


@dataclass
class DownloadReport:
    batch_id: int
    status: str = "completed"
    pages_done: int = 0
    pages_failed: int = 0
    thumbs_done: int = 0
    ugoira_done: int = 0
    failed: int = 0


class DownloadWorker:
    """Executes stage B: downloads originals, ugoira zips and thumbnails."""

    def __init__(
        self,
        *,
        db: Database,
        storage: WorksStorage,
        downloader: BytesDownloader,
        config: DownloadWorkerConfig | None = None,
    ) -> None:
        self._db = db
        self._storage = storage
        self._downloader = downloader
        self._config = config or DownloadWorkerConfig()
        self._transcode = self._config.transcode
        self._thumbs_enabled = True

    def set_thumb_enabled(self, enabled: bool) -> None:
        self._thumbs_enabled = enabled

    async def retry_failed(self) -> int:
        async with self._db.session() as session:
            count = await downloads.retry_failed_jobs(session)
            await session.commit()
        return count

    async def run_scope(self, scope: DownloadScope) -> DownloadReport:
        async with self._db.session() as session:
            batch_id = await downloads.create_batch(
                session, scope=scope.kind, filter_json=None, now=utcnow()
            )
            plan = await resolve_scope(session, scope)
            await downloads.enqueue_jobs(session, batch_id=batch_id, jobs=plan.jobs, now=utcnow())
            await downloads.reset_running_jobs(session)
            await session.commit()

        report = DownloadReport(batch_id=batch_id)
        if not plan.jobs:
            async with self._db.session() as session:
                await downloads.finalize_batch_if_done(session, batch_id, now=utcnow())
                await session.commit()
            return report

        while True:
            async with self._db.session() as session:
                jobs = await downloads.claim_pending_jobs(session, limit=self._config.concurrency)
                await session.commit()
            if not jobs:
                break
            await asyncio.gather(
                *(self._run_job(job.id, job.pid, job.kind, job.target, report) for job in jobs)
            )

        async with self._db.session() as session:
            finalized = await downloads.finalize_batch_if_done(session, batch_id, now=utcnow())
            batch = await downloads.get_batch(session, batch_id)
            counts = await downloads.count_jobs_by_status(session, batch_id)
            await session.commit()
        report.failed = counts.get("failed", 0)
        if batch is not None and finalized:
            report.status = batch.status
        return report

    async def _run_job(
        self, job_id: int, pid: int, kind: str, target: str, report: DownloadReport
    ) -> None:
        if kind == "thumb" and not self._thumbs_enabled:
            await self._finish(job_id, status="skipped")
            return
        handler = {
            "image": self._handle_image,
            "thumb": self._handle_thumb,
            "ugoira_zip": self._handle_ugoira_zip,
            "ugoira_mp4": self._handle_ugoira_mp4,
        }.get(kind)
        if handler is None:
            await self._mark_failed(job_id, f"unknown job kind {kind}")
            return
        try:
            ok, skipped = await handler(pid, target, report)
        except Exception as exc:  # noqa: BLE001 - a single job must not kill the batch
            await self._mark_failed(job_id, str(exc))
            return
        if skipped:
            await self._finish(job_id, status="skipped")
        elif ok:
            await self._finish(job_id)
        else:
            await self._mark_failed(job_id, "download failed")

    async def _finish(self, job_id: int, *, status: str = "done") -> None:
        async with self._db.session() as session:
            await downloads.finish_job(session, job_id, now=utcnow(), status=status)
            await session.commit()

    async def _mark_failed(self, job_id: int, error: str) -> None:
        async with self._db.session() as session:
            await downloads.fail_job(session, job_id, error=error, now=utcnow())
            await session.commit()

    async def _load_page(self, pid: int, target: str) -> tuple[str, str] | None:
        page_index = self._page_index_from_target(target)
        async with self._db.session() as session:
            row = (
                await session.execute(
                    select(IllustPage.original_url, IllustPage.download_state).where(
                        IllustPage.pid == pid, IllustPage.page_index == page_index
                    )
                )
            ).first()
        return (row[0], row[1]) if row is not None else None

    async def _handle_image(
        self, pid: int, target: str, report: DownloadReport
    ) -> tuple[bool, bool]:
        loaded = await self._load_page(pid, target)
        if loaded is None:
            return False, False
        url, download_state = loaded
        dest = self._storage.original_dir(pid) / target
        if download_state == "done" and dest.exists():
            report.pages_done += 1
            return True, True

        data = await self._downloader.fetch_bytes(url)
        if data is None:
            await self._mark_page_failed(pid, target, "fetch failed")
            report.pages_failed += 1
            return False, False
        if not is_valid_image(data):
            await self._mark_page_failed(pid, target, "invalid image data")
            report.pages_failed += 1
            return False, False

        atomic_write_bytes(dest, data)
        await self._mark_page_done(pid, target)
        report.pages_done += 1
        return True, False

    async def _handle_thumb(
        self, pid: int, target: str, report: DownloadReport
    ) -> tuple[bool, bool]:
        dest = self._storage.work_dir(pid) / target
        if dest.exists():
            report.thumbs_done += 1
            return True, True
        source = await self._ensure_first_original(pid)
        if source is None:
            return False, False
        generated = await asyncio.to_thread(generate_thumb, source, dest)
        if generated:
            report.thumbs_done += 1
        return generated, False

    async def _ensure_first_original(self, pid: int) -> Path | None:
        """Return a local original image, downloading missing pages on demand.

        Thumbnail jobs may run concurrently with (or before) image jobs, so the
        source image may not be on disk yet. Downloading it here keeps job
        ordering irrelevant at the cost of a duplicate write in the worst case.
        """
        existing = self._first_original(pid)
        if existing is not None:
            return existing
        async with self._db.session() as session:
            rows = (
                await session.execute(
                    select(IllustPage.original_url, IllustPage.page_index, IllustPage.ext)
                    .where(IllustPage.pid == pid)
                    .order_by(IllustPage.page_index)
                    .limit(1)
                )
            ).first()
        if rows is None:
            return None
        url, page_index, ext = rows
        target = f"{page_index:03d}_p{page_index}{ext}"
        data = await self._downloader.fetch_bytes(url)
        if data is None or not is_valid_image(data):
            return None
        destination = self._storage.original_dir(pid) / target
        atomic_write_bytes(destination, data)
        await self._mark_page_done(pid, target)
        return destination

    async def _handle_ugoira_zip(
        self, pid: int, target: str, report: DownloadReport
    ) -> tuple[bool, bool]:
        dest = self._storage.work_dir(pid) / target
        if dest.exists():
            return True, True
        async with self._db.session() as session:
            meta = await session.get(UgoiraMeta, pid)
        if meta is None or not meta.zip_url:
            return False, False
        ok = await self._downloader.fetch_to_file(meta.zip_url, dest)
        if ok:
            report.ugoira_done += 1
        return ok, False

    async def _handle_ugoira_mp4(
        self, pid: int, target: str, report: DownloadReport
    ) -> tuple[bool, bool]:
        dest = self._storage.animation_path(pid)
        if dest.exists():
            return True, True
        zip_path = self._storage.work_dir(pid) / "source.zip"
        if not zip_path.exists():
            return False, False
        async with self._db.session() as session:
            meta = await session.get(UgoiraMeta, pid)
        if meta is None:
            return False, False
        if self._transcode is not None:
            ok = await self._transcode(
                zip_path=zip_path,
                frames_json=meta.frames_json,
                frames_dir=self._storage.work_dir(pid) / "frames",
                dest=dest,
            )
        else:
            ok = await asyncio.to_thread(
                transcode_to_mp4,
                zip_path=zip_path,
                frames_json=meta.frames_json,
                frames_dir=self._storage.work_dir(pid) / "frames",
                dest=dest,
                ffmpeg_bin=self._config.ffmpeg_bin,
            )
        if ok:
            report.ugoira_done += 1
            return True, False
        return False, True  # no ffmpeg / invalid frames -> skip, keep the zip

    def _first_original(self, pid: int) -> Path | None:
        directory = self._storage.original_dir(pid)
        if not directory.is_dir():
            return None
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() in IMAGE_SUFFIXES:
                return path
        return None

    async def _mark_page_done(self, pid: int, target: str) -> None:
        page_index = self._page_index_from_target(target)
        async with self._db.session() as session:
            await session.execute(
                update(IllustPage)
                .where(IllustPage.pid == pid, IllustPage.page_index == page_index)
                .values(download_state="done", last_error=None)
            )
            await self._refresh_illust_counters(session, pid)
            await session.commit()

    async def _mark_page_failed(self, pid: int, target: str, error: str) -> None:
        page_index = self._page_index_from_target(target)
        async with self._db.session() as session:
            previous = (
                await session.execute(
                    select(IllustPage.attempts).where(
                        IllustPage.pid == pid, IllustPage.page_index == page_index
                    )
                )
            ).scalar_one_or_none()
            attempts = (previous or 0) + 1
            await session.execute(
                update(IllustPage)
                .where(IllustPage.pid == pid, IllustPage.page_index == page_index)
                .values(download_state="failed", last_error=error[:500], attempts=attempts)
            )
            await self._refresh_illust_counters(session, pid)
            await session.commit()

    async def _refresh_illust_counters(self, session: AsyncSession, pid: int) -> None:
        total = (
            await session.execute(
                select(func.count()).select_from(IllustPage).where(IllustPage.pid == pid)
            )
        ).scalar_one()
        done = (
            await session.execute(
                select(func.count())
                .select_from(IllustPage)
                .where(IllustPage.pid == pid, IllustPage.download_state == "done")
            )
        ).scalar_one()
        await session.execute(
            update(Illust)
            .where(Illust.pid == pid)
            .values(page_downloaded_count=done, has_original=(done == total and total > 0))
        )

    @staticmethod
    def _page_index_from_target(target: str) -> int:
        try:
            return int(target.split("_", 1)[0])
        except (ValueError, IndexError):
            return 0
