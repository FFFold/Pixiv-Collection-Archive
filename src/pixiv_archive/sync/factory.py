import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from pixiv_archive.config import Settings
from pixiv_archive.db.engine import Database
from pixiv_archive.download.worker import DownloadWorker, DownloadWorkerConfig
from pixiv_archive.media.downloader import ImageDownloader
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.pixiv.client import PixivClient
from pixiv_archive.sync.orchestrator import MetadataSyncService


@asynccontextmanager
async def open_sync_service(settings: Settings) -> AsyncIterator[MetadataSyncService]:
    """Build a fully wired MetadataSyncService and clean everything up after use.

    Ensures the schema exists (idempotent) so the CLI works on a fresh volume
    without a separate migration step.
    """
    await _ensure_schema(settings)
    db = Database(settings.db_path)
    image_client = httpx.AsyncClient(proxy=settings.pixiv_proxy, timeout=30.0)
    captured: dict[str, str] = {}

    client = PixivClient(
        settings.pixiv_refresh_token,
        settings.pixiv_user_id,
        proxy=settings.pixiv_proxy,
        min_interval_ms=settings.api_min_interval_ms,
        on_refresh_token=lambda token: captured.__setitem__("refresh_token", token),
    )
    service = MetadataSyncService(
        db=db,
        client=client,
        storage=WorksStorage(settings.works_dir),
        downloader=ImageDownloader(
            image_client,
            mirror=settings.pixiv_image_mirror,
            concurrency=settings.image_concurrency,
        ),
        download_previews=settings.download_previews,
    )
    try:
        yield service
        if "refresh_token" in captured:
            await db.update_setting("pixiv_refresh_token", captured["refresh_token"])
    finally:
        await client.aclose()
        await image_client.aclose()
        await db.dispose()


async def _ensure_schema(settings: Settings) -> None:
    """Bring the database up to the latest migration revision (idempotent).

    A fresh volume is created and stamped by Alembic, so subsequent
    ``alembic upgrade`` invocations behave correctly.
    """
    ini_path = _find_alembic_ini()
    if ini_path is None:
        # Fallback for environments without the ini (e.g. bare package install).
        from pixiv_archive.db import models  # noqa: F401  (register models)
        from pixiv_archive.db.base import Base

        db = Database(settings.db_path)
        try:
            async with db.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await db.dispose()
        return

    from alembic import command
    from alembic.config import Config

    config = Config(str(ini_path))
    config.set_main_option("script_location", str(_script_location(ini_path)))
    await asyncio.to_thread(command.upgrade, config, "head")


def _find_alembic_ini() -> Path | None:
    candidates = [Path.cwd() / "alembic.ini"]
    package_root = Path(__file__).resolve().parents[3]
    candidates.append(package_root / "alembic.ini")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _script_location(ini_path: Path) -> Path:
    return (ini_path.parent / "src" / "pixiv_archive" / "db" / "migrations").resolve()


@asynccontextmanager
async def open_download_worker(settings: Settings) -> AsyncIterator[DownloadWorker]:
    """Build a DownloadWorker with a shared HTTP client, cleaning up afterwards."""
    await _ensure_schema(settings)
    db = Database(settings.db_path)
    image_client = httpx.AsyncClient(proxy=settings.pixiv_proxy, timeout=60.0)
    worker = DownloadWorker(
        db=db,
        storage=WorksStorage(settings.works_dir),
        downloader=ImageDownloader(
            image_client,
            mirror=settings.pixiv_image_mirror,
            concurrency=settings.image_concurrency,
        ),
        config=DownloadWorkerConfig(
            concurrency=settings.image_concurrency,
            ffmpeg_bin=settings.ffmpeg_bin,
        ),
    )
    try:
        yield worker
    finally:
        await image_client.aclose()
        await db.dispose()
