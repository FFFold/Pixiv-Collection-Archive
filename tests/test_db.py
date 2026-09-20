import pytest
from sqlalchemy import select, text

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import AppSetting, Author, Bookmark, Illust


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.create_all()
    yield database
    await database.dispose()


async def test_create_all_creates_tables(db, tmp_path):
    assert (tmp_path / "test.db").exists()
    async with db.session() as session:
        result = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        names = {row[0] for row in result}
    assert {"illust", "author", "bookmark", "app_setting"} <= names


async def test_wal_mode_enabled(db):
    async with db.session() as session:
        result = await session.execute(text("PRAGMA journal_mode"))
        assert result.scalar_one() == "wal"


async def test_insert_and_query_illust(db):
    async with db.session() as session:
        session.add(Author(id=9, name="a"))
        await session.commit()
    async with db.session() as session:
        session.add(Illust(pid=123, title="hello", author_id=9, page_count=1, type="illust"))
        await session.commit()
    async with db.session() as session:
        row = (await session.execute(select(Illust).where(Illust.pid == 123))).scalar_one()
    assert row.title == "hello"
    assert row.state == "active"


async def test_bookmark_unique_pid(db):
    from sqlalchemy.exc import IntegrityError

    async with db.session() as session:
        session.add(Author(id=9, name="a"))
        session.add(Illust(pid=1, title="x", author_id=9))
        await session.commit()
    async with db.session() as session:
        session.add(Bookmark(pid=1, restrict="public", rank=0))
        await session.commit()
    with pytest.raises(IntegrityError):
        async with db.session() as session:
            session.add(Bookmark(pid=1, restrict="private", rank=1000))
            await session.commit()


async def test_app_setting_roundtrip(db):
    async with db.session() as session:
        session.add(AppSetting(key="refresh_token", value="abc"))
        await session.commit()
    async with db.session() as session:
        row = (
            await session.execute(select(AppSetting).where(AppSetting.key == "refresh_token"))
        ).scalar_one()
    assert row.value == "abc"
