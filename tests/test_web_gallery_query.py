from datetime import UTC, datetime

import pytest

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust, IllustTag, Tag
from pixiv_archive.web.gallery_query import GalleryFilters, query_gallery


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "gq.db")
    await database.create_all()
    yield database
    await database.dispose()


async def _seed(
    db,
    pid: int,
    *,
    rank: int,
    author=1,
    type_="illust",
    x=0,
    state="active",
    bm_state="active",
    tags=(),
    has_original=False,
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
                has_original=has_original,
                page_count=1,
                create_date=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()
    async with db.session() as session:
        session.add(Bookmark(pid=pid, restrict="public", rank=rank, state=bm_state))
        for name in tags:
            tag = Tag(name=f"{name}-{pid}")
            session.add(tag)
            await session.flush()
            session.add(IllustTag(pid=pid, tag_id=tag.id, position=0))
        await session.commit()


async def test_query_returns_items_in_rank_order_with_index(db):
    await _seed(db, 1, rank=100)
    await _seed(db, 2, rank=0)
    await _seed(db, 3, rank=200)
    async with db.session() as session:
        result = await query_gallery(session, GalleryFilters(), offset=0, limit=10)
    assert [item.pid for item in result.items] == [2, 1, 3]
    assert [item.index for item in result.items] == [1, 2, 3]
    assert result.total == 3


async def test_query_pagination_keeps_absolute_index(db):
    for i, pid in enumerate([10, 20, 30, 40, 50]):
        await _seed(db, pid, rank=i * 1024)
    async with db.session() as session:
        page = await query_gallery(session, GalleryFilters(), offset=2, limit=2)
    assert [item.pid for item in page.items] == [30, 40]
    assert [item.index for item in page.items] == [3, 4]


async def test_query_sorts_by_create_date_and_bookmarks(db):
    await _seed(db, 1, rank=0)
    await _seed(db, 2, rank=10)
    async with db.session() as session:
        newest = await query_gallery(
            session, GalleryFilters(sort="create_date"), offset=0, limit=10
        )
    assert newest.total == 2

    async with db.session() as session:
        popular = await query_gallery(session, GalleryFilters(sort="bookmarks"), offset=0, limit=10)
    assert len(popular.items) == 2


async def test_query_filters_by_x_restrict_and_type(db):
    await _seed(db, 1, rank=0, x=0, type_="illust")
    await _seed(db, 2, rank=10, x=1, type_="ugoira")
    async with db.session() as session:
        result = await query_gallery(
            session, GalleryFilters(x_restrict=1, type="ugoira"), offset=0, limit=10
        )
    assert [item.pid for item in result.items] == [2]


async def test_query_filters_download_state(db):
    await _seed(db, 1, rank=0, has_original=True)
    await _seed(db, 2, rank=10, has_original=False)
    async with db.session() as session:
        downloaded = await query_gallery(
            session, GalleryFilters(downloaded=True), offset=0, limit=10
        )
        pending = await query_gallery(session, GalleryFilters(downloaded=False), offset=0, limit=10)
    assert [item.pid for item in downloaded.items] == [1]
    assert [item.pid for item in pending.items] == [2]


async def test_query_filters_by_author_and_tag(db):
    await _seed(db, 1, rank=0, author=5, tags=("猫",))
    await _seed(db, 2, rank=10, author=6, tags=("犬",))
    async with db.session() as session:
        by_author = await query_gallery(session, GalleryFilters(author_id=5), offset=0, limit=10)
        by_tag = await query_gallery(session, GalleryFilters(tag="犬-2"), offset=0, limit=10)
    assert [item.pid for item in by_author.items] == [1]
    assert [item.pid for item in by_tag.items] == [2]


async def test_query_search_matches_title_and_author_name(db):
    await _seed(db, 777, rank=0)
    async with db.session() as session:
        by_title = await query_gallery(session, GalleryFilters(q="777"), offset=0, limit=10)
        by_author = await query_gallery(session, GalleryFilters(q="author1"), offset=0, limit=10)
    assert [item.pid for item in by_title.items] == [777]
    assert [item.pid for item in by_author.items] == [777]


async def test_query_unbookmarked_scope(db):
    await _seed(db, 1, rank=0, bm_state="unbookmarked")
    await _seed(db, 2, rank=10)
    async with db.session() as session:
        default = await query_gallery(session, GalleryFilters(), offset=0, limit=10)
        unbookmarked = await query_gallery(
            session,
            GalleryFilters(include_unbookmarked=True, only_unbookmarked=True),
            offset=0,
            limit=10,
        )
    assert [item.pid for item in default.items] == [2]
    assert [item.pid for item in unbookmarked.items] == [1]


async def test_query_excludes_deleted_illusts(db):
    await _seed(db, 1, rank=0, state="deleted")
    await _seed(db, 2, rank=10)
    async with db.session() as session:
        result = await query_gallery(session, GalleryFilters(), offset=0, limit=10)
    assert [item.pid for item in result.items] == [2]


async def test_query_rank_range(db):
    for i, pid in enumerate([10, 20, 30]):
        await _seed(db, pid, rank=i * 1024)
    async with db.session() as session:
        result = await query_gallery(
            session, GalleryFilters(rank_start=1, rank_count=1), offset=0, limit=10
        )
    assert [item.pid for item in result.items] == [20]
