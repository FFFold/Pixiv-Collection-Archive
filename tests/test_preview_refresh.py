import json

import pytest

from fakes import FakeDownloader
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Illust
from pixiv_archive.maintenance.preview_refresh import PreviewRefresher
from pixiv_archive.media.storage import WorksStorage

MEDIUM = "https://i.pximg.net/c/540x540_70/1_p0_master1200.jpg"
SQUARE = "https://i.pximg.net/c/540x540_10_webp/1_p0_square1200.jpg"


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / "refresh.db")
    await db.create_all()
    storage = WorksStorage(tmp_path / "works")
    yield db, storage
    await db.dispose()


async def _seed(db, storage, pid, *, thumb_ready=False, meta_urls=None, preview=b"old-square"):
    storage.work_dir(pid).mkdir(parents=True, exist_ok=True)
    if preview is not None:
        storage.preview_path(pid).write_bytes(preview)
    meta = json.dumps({"image_urls": meta_urls or {"medium": MEDIUM, "square_medium": SQUARE}})
    async with db.session() as session:
        if await session.get(Author, 1) is None:
            session.add(Author(id=1, name="a"))
        session.add(
            Illust(
                pid=pid,
                title="t",
                author_id=1,
                state="active",
                thumb_ready=thumb_ready,
                meta_json=meta,
            )
        )
        await session.commit()


async def test_refresh_overwrites_and_marks_ready(env):
    db, storage = env
    await _seed(db, storage, 1)
    downloader = FakeDownloader()
    report = await PreviewRefresher(db=db, storage=storage, downloader=downloader).run()
    assert (report.total, report.fetched, report.failed, report.remaining) == (1, 1, 0, 0)
    assert downloader.urls == [MEDIUM]
    assert storage.preview_path(1).read_bytes() != b"old-square"
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert (row.preview_state, row.preview_attempts, row.preview_error) == ("ready", 0, None)


async def test_failed_fetch_keeps_old_preview_and_records_error(env):
    db, storage = env
    await _seed(db, storage, 1)
    downloader = FakeDownloader(fail_urls={MEDIUM})
    report = await PreviewRefresher(db=db, storage=storage, downloader=downloader).run()
    assert (report.fetched, report.failed, report.remaining) == (0, 1, 1)
    assert storage.preview_path(1).read_bytes() == b"old-square"
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert (row.preview_state, row.preview_attempts, row.preview_error) == (
        "stale",
        1,
        "fetch failed",
    )


async def test_placeholder_url_is_rejected_without_a_request(env):
    db, storage = env
    await _seed(
        db,
        storage,
        1,
        meta_urls={"medium": "https://s.pximg.net/common/images/limit_unknown_360.png"},
    )
    downloader = FakeDownloader()
    report = await PreviewRefresher(db=db, storage=storage, downloader=downloader).run()
    assert downloader.urls == []
    assert report.failed == 1
    assert storage.preview_path(1).read_bytes() == b"old-square"


async def test_corrupt_payload_is_not_written(env):
    db, storage = env
    await _seed(db, storage, 1)
    downloader = FakeDownloader(corrupt_urls={MEDIUM})
    report = await PreviewRefresher(db=db, storage=storage, downloader=downloader).run()
    assert report.failed == 1
    assert storage.preview_path(1).read_bytes() == b"old-square"
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert row.preview_error == "invalid image data"


async def test_thumb_ready_works_are_not_refreshed(env):
    db, storage = env
    await _seed(db, storage, 1, thumb_ready=True)
    downloader = FakeDownloader()
    report = await PreviewRefresher(db=db, storage=storage, downloader=downloader).run()
    assert report.total == 0
    assert downloader.urls == []
    assert storage.preview_path(1).read_bytes() == b"old-square"


async def test_resume_only_fetches_remaining_stale(env):
    db, storage = env
    await _seed(db, storage, 1, preview=None)
    await _seed(db, storage, 2, preview=None)
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update().where(Illust.pid == 1).values(preview_state="ready")
        )
        await session.execute(
            Illust.__table__.update().where(Illust.pid == 2).values(preview_state="stale")
        )
        await session.commit()
    downloader = FakeDownloader()
    report = await PreviewRefresher(db=db, storage=storage, downloader=downloader).run()
    assert report.resumed is True
    assert downloader.urls == [MEDIUM]
    assert report.total == 1


async def test_exhausted_rows_are_skipped(env):
    db, storage = env
    await _seed(db, storage, 1)
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update()
            .where(Illust.pid == 1)
            .values(preview_state="stale", preview_attempts=5)
        )
        await session.commit()
    downloader = FakeDownloader()
    report = await PreviewRefresher(db=db, storage=storage, downloader=downloader).run()
    assert downloader.urls == []
    assert (report.remaining, report.skipped) == (1, 1)


async def test_total_counts_only_attemptable_rows(env):
    db, storage = env
    await _seed(db, storage, 1)
    await _seed(db, storage, 2)
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update()
            .where(Illust.pid == 1)
            .values(preview_state="stale", preview_attempts=5)
        )
        await session.execute(
            Illust.__table__.update().where(Illust.pid == 2).values(preview_state="stale")
        )
        await session.commit()
    downloader = FakeDownloader()
    report = await PreviewRefresher(db=db, storage=storage, downloader=downloader).run()
    assert (report.total, report.fetched, report.skipped, report.remaining) == (1, 1, 1, 1)
    assert downloader.urls == [MEDIUM]


async def test_restart_re_queues_exhausted_rows(env):
    db, storage = env
    await _seed(db, storage, 1)
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update()
            .where(Illust.pid == 1)
            .values(preview_state="stale", preview_attempts=5, preview_error="http 404")
        )
        await session.commit()
    downloader = FakeDownloader()
    report = await PreviewRefresher(db=db, storage=storage, downloader=downloader).run(restart=True)
    assert (report.total, report.fetched, report.resumed) == (1, 1, False)
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert (row.preview_state, row.preview_attempts, row.preview_error) == ("ready", 0, None)
