"""Live stage B download against the real pixiv image CDN.

Run with:
    uv run pytest tests/test_integration_download.py -m integration -v -s
Requires PIXIV_REFRESH_TOKEN / PIXIV_USER_ID and network access (PIXIV_PROXY).
"""

import pytest
from sqlalchemy import select

from pixiv_archive.config import Settings
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Bookmark, Illust, IllustPage
from pixiv_archive.download.scope import DownloadScope
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.sync.factory import open_download_worker, open_sync_service

pytestmark = pytest.mark.integration


def _register(settings: Settings) -> Database:
    return Database(settings.db_path)


async def _top_ranked_pids(db: Database, count: int) -> list[int]:
    async with db.session() as session:
        rows = await session.execute(select(Bookmark.pid).order_by(Bookmark.rank).limit(count))
        return [row[0] for row in rows]


async def test_live_download_small_sample(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings(_env_file=None)
    settings.ensure_dirs()

    async with open_sync_service(settings) as service:
        sync_result = await service.run_incremental(max_pages=1)
    assert sync_result.new_count == 30

    async with open_download_worker(settings) as worker:
        worker.set_thumb_enabled(False)
        report = await worker.run_scope(DownloadScope(kind="rank_range", start=0, count=2))

    print(
        f"\npages={report.pages_done} failed={report.pages_failed} "
        f"thumbs={report.thumbs_done} ugoira={report.ugoira_done} status={report.status}"
    )
    assert report.pages_done > 0
    assert report.pages_failed == 0

    db = _register(settings)
    target_pids = await _top_ranked_pids(db, 2)
    async with db.session() as session:
        illusts = (
            (await session.execute(select(Illust).where(Illust.pid.in_(target_pids))))
            .scalars()
            .all()
        )
        pages = (
            (await session.execute(select(IllustPage).where(IllustPage.pid.in_(target_pids))))
            .scalars()
            .all()
        )
    await db.dispose()

    assert len(illusts) == 2
    for illust in illusts:
        assert illust.has_original is True
        assert illust.page_downloaded_count == illust.page_count

    storage = WorksStorage(settings.works_dir)
    assert pages, "pages must exist"
    for page in pages:
        assert page.download_state == "done"
        candidates = list(storage.original_dir(page.pid).glob(f"{page.page_index:03d}_p*"))
        assert candidates, f"downloaded file missing for {page.pid} p{page.page_index}"
        assert candidates[0].stat().st_size > 0


async def test_live_download_thumbnails_for_downloaded_work(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings(_env_file=None)
    settings.ensure_dirs()

    async with open_sync_service(settings) as service:
        await service.run_incremental(max_pages=1)

    async with open_download_worker(settings) as worker:
        report = await worker.run_scope(DownloadScope(kind="rank_range", start=0, count=1))

    assert report.thumbs_done >= 1

    db = _register(settings)
    target_pids = await _top_ranked_pids(db, 1)
    await db.dispose()

    storage = WorksStorage(settings.works_dir)
    assert storage.thumb_path(target_pids[0]).exists()
