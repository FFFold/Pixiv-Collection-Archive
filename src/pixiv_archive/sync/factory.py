from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from pixiv_archive.config import Settings
from pixiv_archive.db.engine import Database
from pixiv_archive.media.downloader import ImageDownloader
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.pixiv.client import PixivClient
from pixiv_archive.sync.orchestrator import MetadataSyncService


@asynccontextmanager
async def open_sync_service(settings: Settings) -> AsyncIterator[MetadataSyncService]:
    """Build a fully wired MetadataSyncService and clean everything up after use."""
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
