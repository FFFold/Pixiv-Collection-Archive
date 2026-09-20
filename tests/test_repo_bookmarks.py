from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Illust, SyncRun
from pixiv_archive.db.repo import bookmarks, sync_runs


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "bm.db")
    await database.create_all()
    yield database
    await database.dispose()


async def _seed_illust(db, pid: int) -> None:
    async with db.session() as session:
        if await session.get(Author, 1) is None:
            session.add(Author(id=1, name="a"))
        session.add(Illust(pid=pid, title=f"t{pid}", author_id=1))
        await session.commit()


async def test_set_active_rank_inserts(db):
    await _seed_illust(db, 1)
    async with db.session() as session:
        created = await bookmarks.set_active_rank(
            session, pid=1, restrict="public", rank=100, now=datetime.now(UTC)
        )
        await session.commit()
    assert created is True
    async with db.session() as session:
        states = await bookmarks.get_bookmark_states(session)
    assert states == {1: "active"}


async def test_set_active_rank_reactivates_unbookmarked(db):
    await _seed_illust(db, 1)
    now = datetime.now(UTC)
    async with db.session() as session:
        await bookmarks.set_active_rank(session, pid=1, restrict="public", rank=100, now=now)
        await session.commit()
    async with db.session() as session:
        await bookmarks.mark_unbookmarked(session, [1], now=now)
        await session.commit()
    async with db.session() as session:
        states = await bookmarks.get_bookmark_states(session)
    assert states == {1: "unbookmarked"}

    async with db.session() as session:
        created = await bookmarks.set_active_rank(
            session, pid=1, restrict="private", rank=-500, now=now + timedelta(hours=1)
        )
        await session.commit()
    assert created is False  # row existed, was reactivated
    async with db.session() as session:
        states = await bookmarks.get_bookmark_states(session)
        min_rank = await bookmarks.get_min_rank(session)
    assert states == {1: "active"}
    assert min_rank == -500


async def test_touch_seen_updates_last_seen_only(db):
    await _seed_illust(db, 1)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 6, 1, tzinfo=UTC)
    async with db.session() as session:
        await bookmarks.set_active_rank(session, pid=1, restrict="public", rank=0, now=t0)
        await session.commit()
    async with db.session() as session:
        await bookmarks.touch_seen(session, [1], now=t1)
        await session.commit()
    async with db.session() as session:
        row = (await session.execute(select(bookmarks.Bookmark))).scalar_one()
    assert row.first_seen_at == t0.replace(tzinfo=None)
    assert row.last_seen_at == t1.replace(tzinfo=None)
    assert row.rank == 0


async def test_mark_unbookmarked_sets_state_and_timestamp(db):
    await _seed_illust(db, 1)
    await _seed_illust(db, 2)
    now = datetime(2026, 2, 2, tzinfo=UTC)
    async with db.session() as session:
        await bookmarks.set_active_rank(session, pid=1, restrict="public", rank=0, now=now)
        await bookmarks.set_active_rank(session, pid=2, restrict="public", rank=10, now=now)
        await session.commit()
    async with db.session() as session:
        count = await bookmarks.mark_unbookmarked(session, [2], now=now)
        await session.commit()
    assert count == 1
    async with db.session() as session:
        states = await bookmarks.get_bookmark_states(session)
        row = (
            await session.execute(select(bookmarks.Bookmark).where(bookmarks.Bookmark.pid == 2))
        ).scalar_one()
    assert states == {1: "active", 2: "unbookmarked"}
    assert row.unbookmarked_at == now.replace(tzinfo=None)


async def test_get_min_rank_and_rank_map(db):
    await _seed_illust(db, 1)
    await _seed_illust(db, 2)
    now = datetime.now(UTC)
    async with db.session() as session:
        await bookmarks.set_active_rank(session, pid=1, restrict="public", rank=500, now=now)
        await bookmarks.set_active_rank(session, pid=2, restrict="public", rank=100, now=now)
        await session.commit()
    async with db.session() as session:
        assert await bookmarks.get_min_rank(session) == 100
        assert await bookmarks.get_rank_map(session) == {1: 500, 2: 100}


async def test_get_min_rank_returns_none_when_empty(db):
    async with db.session() as session:
        assert await bookmarks.get_min_rank(session) is None
        assert await bookmarks.get_rank_map(session) == {}


async def test_ordered_pids_puts_active_first_by_rank(db):
    await _seed_illust(db, 1)
    await _seed_illust(db, 2)
    await _seed_illust(db, 3)
    now = datetime.now(UTC)
    async with db.session() as session:
        await bookmarks.set_active_rank(session, pid=2, restrict="public", rank=200, now=now)
        await bookmarks.set_active_rank(session, pid=1, restrict="public", rank=100, now=now)
        await bookmarks.set_active_rank(session, pid=3, restrict="public", rank=300, now=now)
        await bookmarks.mark_unbookmarked(session, [3], now=now)
        await session.commit()
    async with db.session() as session:
        pids = await bookmarks.ordered_pids(session)
    assert pids == [1, 2, 3]  # rank order; unbookmarked last


async def test_sync_runs_lifecycle(db):
    now = datetime(2026, 3, 3, tzinfo=UTC)
    async with db.session() as session:
        run_id = await sync_runs.create_run(session, "incremental", now=now)
        await session.commit()
    assert run_id > 0
    async with db.session() as session:
        await sync_runs.finish_run(
            session,
            run_id,
            status="completed",
            pages_fetched=3,
            new_count=5,
            unbookmarked_count=1,
            rank_rebuilt_count=0,
            previews_fetched=5,
            previews_failed=0,
            failed_count=0,
            error=None,
            now=now + timedelta(minutes=1),
        )
        await session.commit()
    async with db.session() as session:
        row = (await session.execute(select(SyncRun))).scalar_one()
        last_full = await sync_runs.get_last_full_sync(session)
    assert row.status == "completed"
    assert row.new_count == 5
    assert row.finished_at is not None
    assert last_full is None


async def test_get_last_full_sync(db):
    now = datetime(2026, 4, 4, tzinfo=UTC)
    async with db.session() as session:
        run_id = await sync_runs.create_run(session, "full", now=now)
        await sync_runs.finish_run(
            session,
            run_id,
            status="completed",
            pages_fetched=69,
            new_count=0,
            unbookmarked_count=0,
            rank_rebuilt_count=0,
            previews_fetched=0,
            previews_failed=0,
            failed_count=0,
            error=None,
            now=now,
        )
        await session.commit()
    async with db.session() as session:
        last_full = await sync_runs.get_last_full_sync(session)
    assert last_full == now.replace(tzinfo=None)
