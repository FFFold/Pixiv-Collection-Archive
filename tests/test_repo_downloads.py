from datetime import UTC, datetime

import pytest

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Illust
from pixiv_archive.db.repo import downloads


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "drepo.db")
    await database.create_all()
    yield database
    await database.dispose()


async def _seed(db, pids: list[int]) -> None:
    async with db.session() as session:
        session.add(Author(id=1, name="a"))
        for pid in pids:
            session.add(Illust(pid=pid, title=f"t{pid}", author_id=1))
        await session.commit()


async def test_create_batch_and_enqueue(db):
    await _seed(db, [1, 2])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        added = await downloads.enqueue_jobs(
            session,
            batch_id=batch_id,
            jobs=[
                (1, "image", "000_p0.jpg"),
                (1, "thumb", "thumb.webp"),
                (2, "image", "000_p0.jpg"),
            ],
            now=datetime.now(UTC),
        )
        await session.commit()
    assert batch_id > 0
    assert added == 3

    async with db.session() as session:
        batch = await downloads.get_batch(session, batch_id)
        counts = await downloads.count_jobs_by_status(session, batch_id)
    assert batch.total == 3
    assert counts == {"pending": 3}


async def test_enqueue_jobs_is_idempotent(db):
    await _seed(db, [1])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="selected", filter_json="{}", now=datetime.now(UTC)
        )
        first = await downloads.enqueue_jobs(
            session, batch_id=batch_id, jobs=[(1, "image", "000_p0.jpg")], now=datetime.now(UTC)
        )
        second = await downloads.enqueue_jobs(
            session, batch_id=batch_id, jobs=[(1, "image", "000_p0.jpg")], now=datetime.now(UTC)
        )
        await session.commit()
    assert first == 1
    assert second == 0  # duplicate target ignored


async def test_claim_pending_jobs(db):
    await _seed(db, [1, 2, 3])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        await downloads.enqueue_jobs(
            session,
            batch_id=batch_id,
            jobs=[(pid, "image", "000_p0.jpg") for pid in (1, 2, 3)],
            now=datetime.now(UTC),
        )
        await session.commit()

    async with db.session() as session:
        claimed = await downloads.claim_pending_jobs(session, limit=2)
        await session.commit()
    assert [job.pid for job in claimed] == [1, 2]
    assert all(job.status == "running" for job in claimed)
    assert all(job.attempts == 1 for job in claimed)

    async with db.session() as session:
        claimed2 = await downloads.claim_pending_jobs(session, limit=10)
        await session.commit()
    assert [job.pid for job in claimed2] == [3]


async def test_finish_job_and_fail_job(db):
    await _seed(db, [1, 2])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        await downloads.enqueue_jobs(
            session,
            batch_id=batch_id,
            jobs=[(1, "image", "a.jpg"), (2, "image", "b.jpg")],
            now=datetime.now(UTC),
        )
        await session.commit()
    async with db.session() as session:
        jobs = await downloads.claim_pending_jobs(session, limit=2)
        await downloads.finish_job(session, jobs[0].id, now=datetime.now(UTC))
        await downloads.fail_job(session, jobs[1].id, error="boom", now=datetime.now(UTC))
        await session.commit()

    async with db.session() as session:
        batch = await downloads.get_batch(session, batch_id)
        counts = await downloads.count_jobs_by_status(session, batch_id)
        await downloads.finalize_batch_if_done(session, batch_id, now=datetime.now(UTC))
        batch = await downloads.get_batch(session, batch_id)
        await session.commit()
    assert counts == {"done": 1, "failed": 1}
    assert batch.finished == 1
    assert batch.failed == 1


async def test_reset_running_jobs_on_startup(db):
    await _seed(db, [1])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        await downloads.enqueue_jobs(
            session, batch_id=batch_id, jobs=[(1, "image", "a.jpg")], now=datetime.now(UTC)
        )
        await session.commit()
    async with db.session() as session:
        await downloads.claim_pending_jobs(session, limit=1)
        await session.commit()

    async with db.session() as session:
        reset = await downloads.reset_running_jobs(session)
        await session.commit()
    assert reset == 1
    async with db.session() as session:
        counts = await downloads.count_jobs_by_status(session, batch_id)
    assert counts == {"pending": 1}


async def test_retry_failed_jobs(db):
    await _seed(db, [1])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        await downloads.enqueue_jobs(
            session, batch_id=batch_id, jobs=[(1, "image", "a.jpg")], now=datetime.now(UTC)
        )
        await session.commit()
    async with db.session() as session:
        jobs = await downloads.claim_pending_jobs(session, limit=1)
        await downloads.fail_job(session, jobs[0].id, error="boom", now=datetime.now(UTC))
        await session.commit()

    async with db.session() as session:
        retried = await downloads.retry_failed_jobs(session, batch_id=batch_id)
        await session.commit()
    assert retried == 1
    async with db.session() as session:
        counts = await downloads.count_jobs_by_status(session, batch_id)
        batch = await downloads.get_batch(session, batch_id)
    assert counts == {"pending": 1}
    assert batch.failed == 0


async def test_mark_batch_finished_when_no_pending(db):
    await _seed(db, [1])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        await downloads.enqueue_jobs(
            session, batch_id=batch_id, jobs=[(1, "image", "a.jpg")], now=datetime.now(UTC)
        )
        await session.commit()
    async with db.session() as session:
        jobs = await downloads.claim_pending_jobs(session, limit=1)
        await downloads.finish_job(session, jobs[0].id, now=datetime.now(UTC))
        finished = await downloads.finalize_batch_if_done(session, batch_id, now=datetime.now(UTC))
        await session.commit()
    assert finished is True
    async with db.session() as session:
        batch = await downloads.get_batch(session, batch_id)
    assert batch.status == "completed"
    assert batch.finished_at is not None


async def test_finalize_batch_keeps_running_when_pending_left(db):
    await _seed(db, [1, 2])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        await downloads.enqueue_jobs(
            session,
            batch_id=batch_id,
            jobs=[(1, "image", "a.jpg"), (2, "image", "b.jpg")],
            now=datetime.now(UTC),
        )
        await session.commit()
    async with db.session() as session:
        finished = await downloads.finalize_batch_if_done(session, batch_id, now=datetime.now(UTC))
        await session.commit()
    assert finished is False


async def test_pending_job_count_and_missing_pids(db):
    await _seed(db, [1, 2, 3])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        await downloads.enqueue_jobs(
            session,
            batch_id=batch_id,
            jobs=[(1, "image", "a.jpg"), (2, "image", "b.jpg"), (3, "image", "c.jpg")],
            now=datetime.now(UTC),
        )
        await session.commit()
    async with db.session() as session:
        jobs = await downloads.claim_pending_jobs(session, limit=3)
        await downloads.finish_job(session, jobs[0].id, now=datetime.now(UTC))
        await downloads.fail_job(session, jobs[1].id, error="x", now=datetime.now(UTC))
        await session.commit()

    async with db.session() as session:
        assert await downloads.pending_job_count(session) == 0  # third job is running
        assert await downloads.missing_pids(session) == [2]
        await downloads.reset_running_jobs(session)
        await session.commit()

    async with db.session() as session:
        assert await downloads.pending_job_count(session) == 1
        assert await downloads.missing_pids(session) == [2, 3]
        pids_for_jobs = await downloads.jobs_for_pid(session, 1)
    assert len(pids_for_jobs) == 1
    assert pids_for_jobs[0].status == "done"
