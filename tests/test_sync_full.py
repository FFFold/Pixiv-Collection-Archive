from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from fakes import FakeClient, FakeDownloader, make_illust, page
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Illust
from pixiv_archive.db.repo import bookmarks
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.sync.orchestrator import MetadataSyncService


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "full.db")
    await database.create_all()
    yield database
    await database.dispose()


def build_service(db, tmp_path, client, downloader, *, previews=True) -> MetadataSyncService:
    return MetadataSyncService(
        db=db,
        client=client,
        storage=WorksStorage(tmp_path / "works"),
        downloader=downloader,
        download_previews=previews,
    )


async def test_full_sync_rebuilds_ranks_by_position(db, tmp_path):
    client = FakeClient(
        {
            "public": [
                page([make_illust(1), make_illust(2)], cursor=777),
                page([make_illust(3)], cursor=None),
            ],
            "private": [page([make_illust(4)], cursor=None)],
        }
    )
    result = await build_service(db, tmp_path, client, FakeDownloader()).run_full()
    assert result.status == "completed"
    assert result.new_count == 4
    assert result.pages_fetched == 3
    async with db.session() as session:
        pids = await bookmarks.ordered_pids(session)
        ranks = await bookmarks.get_rank_map(session)
    assert pids == [1, 2, 3, 4]
    assert ranks == {1: 0, 2: 1024, 3: 2048, 4: 3072}


async def test_full_sync_marks_missing_as_unbookmarked(db, tmp_path):
    setup = FakeClient(
        {
            "public": [page([make_illust(1), make_illust(2)], cursor=None)],
            "private": [],
        }
    )
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()

    shrunk = FakeClient({"public": [page([make_illust(2)], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, shrunk, FakeDownloader()).run_full()
    assert result.unbookmarked_count == 1
    async with db.session() as session:
        states = await bookmarks.get_bookmark_states(session)
        pids = await bookmarks.ordered_pids(session)
    assert states == {1: "unbookmarked", 2: "active"}
    assert pids == [2, 1]


async def test_full_sync_refreshes_metadata(db, tmp_path):
    setup = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()

    refreshed = FakeClient(
        {
            "public": [page([make_illust(1, title="new title", total_bookmarks=999)], cursor=None)],
            "private": [],
        }
    )
    await build_service(db, tmp_path, refreshed, FakeDownloader()).run_full()
    async with db.session() as session:
        row = (await session.execute(select(Illust))).scalar_one()
    assert row.title == "new title"
    assert row.total_bookmarks == 999


async def test_full_sync_counts_rank_corrections(db, tmp_path):
    setup = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()
    async with db.session() as session:
        await bookmarks.set_active_rank(
            session, pid=1, restrict="public", rank=-99999, now=datetime.now(UTC)
        )
        await session.commit()
    again = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, again, FakeDownloader()).run_full()
    assert result.rank_rebuilt_count == 1
    async with db.session() as session:
        assert await bookmarks.get_rank_map(session) == {1: 0}


async def test_full_sync_reactivates_and_repositions(db, tmp_path):
    setup = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()
    async with db.session() as session:
        await bookmarks.mark_unbookmarked(session, [1], now=datetime.now(UTC))
        await session.commit()

    again = FakeClient(
        {
            "public": [page([make_illust(2), make_illust(1)], cursor=None)],
            "private": [],
        }
    )
    await build_service(db, tmp_path, again, FakeDownloader()).run_full()
    async with db.session() as session:
        pids = await bookmarks.ordered_pids(session)
        states = await bookmarks.get_bookmark_states(session)
    assert pids == [2, 1]
    assert states == {1: "active", 2: "active"}


async def test_full_sync_backfills_missing_previews(db, tmp_path):
    setup = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    downloader = FakeDownloader()
    await build_service(db, tmp_path, setup, downloader).run_full()
    storage = WorksStorage(tmp_path / "works")
    storage.preview_path(1).unlink()

    again = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    downloader2 = FakeDownloader()
    await build_service(db, tmp_path, again, downloader2).run_full()
    assert downloader2.urls == ["https://i.pximg.net/1_sq.jpg"]
    assert storage.preview_path(1).exists()


async def test_full_sync_does_not_refetch_existing_previews(db, tmp_path):
    setup = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()
    again = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    downloader = FakeDownloader()
    await build_service(db, tmp_path, again, downloader).run_full()
    assert downloader.urls == []


async def test_full_sync_truncated_does_not_mark_unbookmarked(db, tmp_path):
    setup = FakeClient(
        {
            "public": [page([make_illust(1), make_illust(2), make_illust(3)], cursor=None)],
            "private": [],
        }
    )
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()

    limited = FakeClient(
        {
            "public": [
                page([make_illust(3)], cursor=42),
                page([make_illust(2)], cursor=43),
            ],
            "private": [],
        }
    )
    result = await build_service(db, tmp_path, limited, FakeDownloader()).run_full(max_pages=1)
    assert result.unbookmarked_count == 0
    assert any("max_pages" in warning for warning in result.warnings)
