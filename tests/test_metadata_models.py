import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import (
    Author,
    Illust,
    IllustPage,
    IllustTag,
    SyncRun,
    Tag,
    UgoiraMeta,
)


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "meta.db")
    await database.create_all()
    yield database
    await database.dispose()


async def test_metadata_tables_exist(db):
    from sqlalchemy import text

    async with db.session() as session:
        rows = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        names = {r[0] for r in rows}
    assert {"tag", "illust_tag", "illust_page", "ugoira_meta", "sync_run"} <= names


async def test_illust_page_composite_key(db):
    async with db.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=10, title="x", author_id=1, page_count=2))
        await session.commit()
    async with db.session() as session:
        session.add(IllustPage(pid=10, page_index=0, original_url="u0", ext=".jpg"))
        session.add(IllustPage(pid=10, page_index=1, original_url="u1", ext=".png"))
        await session.commit()
    with pytest.raises(IntegrityError):
        async with db.session() as session:
            session.add(IllustPage(pid=10, page_index=0, original_url="dup", ext=".jpg"))
            await session.commit()


async def test_tag_name_unique(db):
    async with db.session() as session:
        session.add(Tag(name="R-18"))
        await session.commit()
    with pytest.raises(IntegrityError):
        async with db.session() as session:
            session.add(Tag(name="R-18"))
            await session.commit()


async def test_illust_tag_position(db):
    async with db.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=10, title="x", author_id=1))
        session.add(Tag(name="t1"))
        session.add(Tag(name="t2"))
        await session.flush()
        tags = (await session.execute(select(Tag.id, Tag.name))).all()
        tag_ids = {name: tid for tid, name in tags}
        session.add(IllustTag(pid=10, tag_id=tag_ids["t1"], position=0))
        session.add(IllustTag(pid=10, tag_id=tag_ids["t2"], position=1))
        await session.commit()
    async with db.session() as session:
        rows = (
            await session.execute(
                select(IllustTag.tag_id, IllustTag.position).where(IllustTag.pid == 10)
            )
        ).all()
    assert sorted(p for _, p in rows) == [0, 1]


async def test_ugoira_meta_roundtrip(db):
    async with db.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=10, title="u", author_id=1, type="ugoira"))
        await session.commit()
    async with db.session() as session:
        session.add(
            UgoiraMeta(
                pid=10,
                zip_url="https://i.pximg.net/u.zip",
                frames_json='[{"file": "000000.jpg", "delay": 33}]',
                frame_count=1,
            )
        )
        await session.commit()
    async with db.session() as session:
        row = (await session.execute(select(UgoiraMeta).where(UgoiraMeta.pid == 10))).scalar_one()
    assert row.frame_count == 1
    assert "000000.jpg" in row.frames_json


async def test_sync_run_defaults(db):
    async with db.session() as session:
        session.add(SyncRun(kind="incremental"))
        await session.commit()
    async with db.session() as session:
        row = (await session.execute(select(SyncRun))).scalar_one()
    assert row.status == "running"
    assert row.pages_fetched == 0
    assert row.finished_at is None
