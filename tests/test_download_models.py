from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, DownloadBatch, DownloadJob, Illust


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "dl.db")
    await database.create_all()
    yield database
    await database.dispose()


async def test_download_tables_exist(db):
    from sqlalchemy import text

    async with db.session() as session:
        rows = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        names = {r[0] for r in rows}
    assert {"download_batch", "download_job"} <= names


async def test_download_job_defaults_and_unique(db):
    from sqlalchemy.exc import IntegrityError

    async with db.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=10, title="x", author_id=1))
        await session.commit()
    async with db.session() as session:
        session.add(DownloadJob(pid=10, kind="image", target="000_p0.jpg"))
        await session.commit()
    async with db.session() as session:
        job = (await session.execute(select(DownloadJob))).scalar_one()
    assert job.status == "pending"
    assert job.attempts == 0
    assert job.last_error is None

    with pytest.raises(IntegrityError):
        async with db.session() as session:
            session.add(DownloadJob(pid=10, kind="image", target="000_p0.jpg"))
            await session.commit()


async def test_download_job_allows_same_pid_different_kind(db):
    async with db.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=10, title="x", author_id=1))
        await session.commit()
    async with db.session() as session:
        session.add(DownloadJob(pid=10, kind="image", target="000_p0.jpg"))
        session.add(DownloadJob(pid=10, kind="thumb", target="thumb.webp"))
        await session.commit()
    async with db.session() as session:
        rows = (await session.execute(select(DownloadJob))).scalars().all()
    assert len(rows) == 2


async def test_download_batch_counts(db):
    now = datetime(2026, 5, 5, tzinfo=UTC)
    async with db.session() as session:
        session.add(
            DownloadBatch(
                scope="all_missing",
                filter_json=None,
                created_at=now,
                total=10,
                finished=2,
                failed=1,
            )
        )
        await session.commit()
    async with db.session() as session:
        batch = (await session.execute(select(DownloadBatch))).scalar_one()
    assert batch.total == 10
    assert batch.status == "running"
    assert batch.cancelled is False
