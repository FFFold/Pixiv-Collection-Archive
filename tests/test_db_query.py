from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust, IllustTag, Tag
from pixiv_archive.db.query import IllustFilters, build_filtered_pids, build_illust_query


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "q.db")
    await database.create_all()
    yield database
    await database.dispose()


async def _seed(
    db,
    pid: int,
    *,
    rank: int,
    author: int = 1,
    type_: str = "illust",
    x: int = 0,
    state: str = "active",
    bm_state: str = "active",
    restrict: str = "public",
    pages: int = 1,
    bookmarks: int = 0,
    views: int = 0,
    tags: tuple[str, ...] = (),
) -> None:
    async with db.session() as session:
        if await session.get(Author, author) is None:
            session.add(Author(id=author, name=f"author{author}", account=f"acct{author}"))
        session.add(
            Illust(
                pid=pid,
                title=f"作品 {pid}",
                author_id=author,
                type=type_,
                x_restrict=x,
                state=state,
                page_count=pages,
                total_bookmarks=bookmarks,
                total_view=views,
                create_date=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()
    async with db.session() as session:
        session.add(Bookmark(pid=pid, restrict=restrict, rank=rank, state=bm_state))
        for name in tags:
            tag_id = (
                await session.execute(select(Tag.id).where(Tag.name == name))
            ).scalar_one_or_none()
            if tag_id is None:
                tag = Tag(name=name)
                session.add(tag)
                await session.flush()
                tag_id = tag.id
            session.add(IllustTag(pid=pid, tag_id=tag_id, position=0))
        await session.commit()


async def test_default_returns_active_bookmarked(db):
    await _seed(db, 1, rank=0)
    await _seed(db, 2, rank=10, bm_state="unbookmarked")
    await _seed(db, 3, rank=20, state="deleted")
    async with db.session() as session:
        rows = (await session.execute(build_filtered_pids(IllustFilters()))).scalars().all()
    assert rows == [1]


async def test_multi_tag_is_and(db):
    await _seed(db, 1, rank=0, tags=("cat", "cute"))
    await _seed(db, 2, rank=10, tags=("cat",))
    await _seed(db, 3, rank=20, tags=("cute",))
    async with db.session() as session:
        both = (
            (await session.execute(build_filtered_pids(IllustFilters(tags=["cat", "cute"]))))
            .scalars()
            .all()
        )
        one = (
            (await session.execute(build_filtered_pids(IllustFilters(tags=["cat"]))))
            .scalars()
            .all()
        )
    assert both == [1]
    assert one == [1, 2]


async def test_multi_author_is_in(db):
    await _seed(db, 1, rank=0, author=5)
    await _seed(db, 2, rank=10, author=6)
    await _seed(db, 3, rank=20, author=7)
    async with db.session() as session:
        rows = (
            (await session.execute(build_filtered_pids(IllustFilters(author_ids=[5, 7]))))
            .scalars()
            .all()
        )
    assert rows == [1, 3]


async def test_page_count_range(db):
    await _seed(db, 1, rank=0, pages=1)
    await _seed(db, 2, rank=10, pages=3)
    await _seed(db, 3, rank=20, pages=10)
    async with db.session() as session:
        mid = (
            (await session.execute(build_filtered_pids(IllustFilters(page_min=2, page_max=5))))
            .scalars()
            .all()
        )
        at_least = (
            (await session.execute(build_filtered_pids(IllustFilters(page_min=3)))).scalars().all()
        )
    assert mid == [2]
    assert at_least == [2, 3]


async def test_bookmarks_and_views_range(db):
    await _seed(db, 1, rank=0, bookmarks=5, views=100)
    await _seed(db, 2, rank=10, bookmarks=50, views=1000)
    async with db.session() as session:
        hot = (
            (await session.execute(build_filtered_pids(IllustFilters(bookmarks_min=10))))
            .scalars()
            .all()
        )
        niche = (
            (await session.execute(build_filtered_pids(IllustFilters(views_max=500))))
            .scalars()
            .all()
        )
    assert hot == [2]
    assert niche == [1]


async def test_restrict_and_downloaded_filters(db):
    await _seed(db, 1, rank=0, restrict="private")
    await _seed(db, 2, rank=10, restrict="public")
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update().where(Illust.pid == 2).values(has_original=True)
        )
        await session.commit()
    async with db.session() as session:
        private = (
            (await session.execute(build_filtered_pids(IllustFilters(restrict="private"))))
            .scalars()
            .all()
        )
        done = (
            (await session.execute(build_filtered_pids(IllustFilters(downloaded=True))))
            .scalars()
            .all()
        )
    assert private == [1]
    assert done == [2]


async def test_build_illust_query_returns_full_rows(db):
    await _seed(db, 1, rank=0)
    async with db.session() as session:
        stmt = build_illust_query(IllustFilters())
        rows = (await session.execute(stmt)).all()
    assert len(rows) == 1
    illust, bookmark, author = rows[0]
    assert illust.pid == 1
    assert bookmark.rank == 0
    assert author.name == "author1"
