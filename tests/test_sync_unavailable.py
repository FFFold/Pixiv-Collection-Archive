import pytest
from sqlalchemy import select

from fakes import FakeClient, FakeDownloader, make_illust, make_stub_illust, page
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import DownloadJob, Illust, IllustPage
from pixiv_archive.db.repo import bookmarks, downloads, illusts
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.sync.orchestrator import MetadataSyncService
from pixiv_archive.sync.unavailable import is_unavailable


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "unavail.db")
    await database.create_all()
    yield database
    await database.dispose()


def test_stub_by_url_is_unavailable():
    illust = make_stub_illust(123)
    assert is_unavailable(illust) is True


def test_stub_by_zero_author_is_unavailable():
    illust = make_illust(456, user={"id": 0, "name": "", "account": ""})
    assert is_unavailable(illust) is True


def test_normal_illust_is_available():
    assert is_unavailable(make_illust(789)) is False


def test_placeholder_in_meta_pages_is_detected():
    illust = make_illust(
        790,
        meta_pages=[
            {
                "image_urls": {
                    "original": "https://s.pximg.net/common/images/limit_mypixiv_360.png"
                }
            }
        ],
    )
    assert is_unavailable(illust) is True


async def test_mark_illust_deleted_keeps_metadata(db):
    async with db.session() as session:
        await illusts.upsert_illust(session, make_illust(1, title="keep me"), meta_json="{}")
        await session.commit()
    async with db.session() as session:
        changed = await illusts.mark_illust_deleted(session, 1)
        await session.commit()
    assert changed is True
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert row.state == "deleted"
    assert row.title == "keep me"


async def test_skip_pending_and_failed_jobs_for_pid(db):
    async with db.session() as session:
        await illusts.upsert_illust(session, make_illust(7), meta_json="{}")
        session.add(DownloadJob(pid=7, kind="image", target="000_p0.jpg", status="pending"))
        session.add(DownloadJob(pid=7, kind="thumb", target="thumb.webp", status="failed"))
        session.add(DownloadJob(pid=7, kind="image", target="001_p1.jpg", status="done"))
        await session.commit()
    async with db.session() as session:
        skipped = await downloads.skip_jobs_for_pid(session, 7)
        await session.commit()
    assert skipped == 2
    async with db.session() as session:
        rows = (await session.execute(select(DownloadJob))).scalars().all()
    by_target = {row.target: row.status for row in rows}
    assert by_target["000_p0.jpg"] == "skipped"
    assert by_target["thumb.webp"] == "skipped"
    assert by_target["001_p1.jpg"] == "done"


def build_service(db, tmp_path, client, downloader) -> MetadataSyncService:
    return MetadataSyncService(
        db=db,
        client=client,
        storage=WorksStorage(tmp_path / "works"),
        downloader=downloader,
        download_previews=True,
    )


async def test_full_sync_marks_stub_deleted_and_skips_side_effects(db, tmp_path):
    client = FakeClient({"public": [page([make_stub_illust(1)], cursor=None)], "private": []})
    downloader = FakeDownloader()
    result = await build_service(db, tmp_path, client, downloader).run_full()

    assert result.deleted_count == 1
    assert result.new_count == 0
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert row.state == "deleted"
    assert row.title == ""
    assert row.page_count == 0
    assert downloader.urls == []
    assert not (tmp_path / "works" / "1" / "meta.json").exists()
    async with db.session() as session:
        pages = (await session.execute(select(IllustPage))).scalars().all()
    assert pages == []


async def test_full_sync_deleting_keeps_existing_metadata_and_files(db, tmp_path):
    setup = FakeClient(
        {"public": [page([make_illust(1, title="original")], cursor=None)], "private": []}
    )
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()
    storage = WorksStorage(tmp_path / "works")
    assert storage.preview_path(1).exists()

    stub = FakeClient({"public": [page([make_stub_illust(1)], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, stub, FakeDownloader()).run_full()

    assert result.deleted_count == 1
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert row.state == "deleted"
    assert row.title == "original"
    assert storage.preview_path(1).exists()
    assert await original_url_for(db, 1) == "https://i.pximg.net/1.jpg"


async def test_full_sync_restores_work_that_came_back(db, tmp_path):
    stub = FakeClient({"public": [page([make_stub_illust(1)], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, stub, FakeDownloader()).run_full()
    assert result.deleted_count == 1

    alive = FakeClient({"public": [page([make_illust(1, title="back")], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, alive, FakeDownloader()).run_full()

    assert result.deleted_count == 0
    assert result.new_count == 0
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert row.state == "active"
    assert row.title == "back"


async def original_url_for(db, pid: int) -> str:
    async with db.session() as session:
        row = (
            await session.execute(select(IllustPage).where(IllustPage.pid == pid))
        ).scalar_one()
    return row.original_url


async def test_incremental_marks_known_work_deleted_when_first_page_shows_stub(db, tmp_path):
    setup = FakeClient(
        {"public": [page([make_illust(1, title="original")], cursor=None)], "private": []}
    )
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()

    shrunk = FakeClient({"public": [page([make_stub_illust(1)], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, shrunk, FakeDownloader()).run_incremental()

    assert result.deleted_count == 1
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert row.state == "deleted"
    assert row.title == "original"


async def test_incremental_restores_stub_that_came_back(db, tmp_path):
    stub = FakeClient({"public": [page([make_stub_illust(1)], cursor=None)], "private": []})
    await build_service(db, tmp_path, stub, FakeDownloader()).run_full()
    async with db.session() as session:
        assert (await session.get(Illust, 1)).state == "deleted"

    alive = FakeClient({"public": [page([make_illust(1, title="back")], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, alive, FakeDownloader()).run_incremental()

    assert result.deleted_count == 0
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert row.state == "active"
    assert row.title == "back"


async def test_incremental_marks_new_stub_as_deleted(db, tmp_path):
    client = FakeClient({"public": [page([make_stub_illust(9)], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, client, FakeDownloader()).run_incremental()

    assert result.deleted_count == 1
    assert result.new_count == 0
    async with db.session() as session:
        row = await session.get(Illust, 9)
    assert row.state == "deleted"
    assert row.page_count == 0


async def test_incremental_does_not_move_rank_of_known_deleted_work(db, tmp_path):
    setup = FakeClient(
        {
            "public": [
                page([make_illust(1), make_illust(2), make_illust(3)], cursor=None)
            ],
            "private": [],
        }
    )
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()
    async with db.session() as session:
        before = await bookmarks.get_rank_map(session)

    shrunk = FakeClient(
        {
            "public": [page([make_stub_illust(2), make_illust(3)], cursor=None)],
            "private": [],
        }
    )
    await build_service(db, tmp_path, shrunk, FakeDownloader()).run_incremental()
    async with db.session() as session:
        after = await bookmarks.get_rank_map(session)
    assert after[2] == before[2]
    assert after[3] == before[3]
