from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Author, Bookmark, Illust, IllustTag, Tag
from pixiv_archive.web.schemas import GalleryItem, GalleryResponse

_SORTS = {
    "rank": (Bookmark.rank.asc(),),
    "create_date": (Illust.create_date.desc(), Bookmark.rank.asc()),
    "bookmarks": (Illust.total_bookmarks.desc(), Bookmark.rank.asc()),
    "views": (Illust.total_view.desc(), Bookmark.rank.asc()),
}


@dataclass
class GalleryFilters:
    sort: str = "rank"
    include_unbookmarked: bool = False
    only_unbookmarked: bool = False
    only_deleted: bool = False
    include_deleted: bool = False
    author_id: int | None = None
    tag: str | None = None
    q: str | None = None
    type: str | None = None
    x_restrict: int | None = None
    downloaded: bool | None = None
    rank_start: int | None = None
    rank_count: int | None = None
    restrict: str | None = None


def _base_conditions(filters: GalleryFilters) -> list[Any]:
    if filters.only_deleted:
        conditions: list[Any] = [Illust.state == "deleted"]
    elif filters.include_deleted:
        conditions = []
    else:
        conditions = [Illust.state == "active"]
    if filters.only_unbookmarked:
        conditions.append(Bookmark.state == "unbookmarked")
    elif not filters.include_unbookmarked:
        conditions.append(Bookmark.state == "active")
    if filters.author_id is not None:
        conditions.append(Illust.author_id == filters.author_id)
    if filters.type:
        conditions.append(Illust.type == filters.type)
    if filters.x_restrict is not None:
        conditions.append(Illust.x_restrict == filters.x_restrict)
    if filters.downloaded is True:
        conditions.append(Illust.has_original.is_(True))
    elif filters.downloaded is False:
        conditions.append(Illust.has_original.is_(False))
    if filters.restrict:
        conditions.append(Bookmark.restrict == filters.restrict)
    if filters.q:
        pattern = f"%{filters.q}%"
        conditions.append(or_(Illust.title.like(pattern), Author.name.like(pattern)))
    return conditions


def _build_base_select(filters: GalleryFilters) -> Select[Any]:
    stmt = (
        select(Illust, Bookmark, Author)
        .join(Bookmark, Bookmark.pid == Illust.pid)
        .join(Author, Author.id == Illust.author_id)
        .where(and_(*_base_conditions(filters)))
    )
    if filters.tag:
        stmt = (
            stmt.join(IllustTag, IllustTag.pid == Illust.pid)
            .join(Tag, Tag.id == IllustTag.tag_id)
            .where(Tag.name == filters.tag)
        )
    if filters.rank_start is not None or filters.rank_count is not None:
        # Restrict to a rank window via a subquery so the caller's own
        # pagination (offset/limit) is applied independently.
        window = (
            select(Bookmark.pid)
            .where(Bookmark.state == "active")
            .order_by(Bookmark.rank)
            .offset(filters.rank_start or 0)
        )
        if filters.rank_count is not None:
            window = window.limit(filters.rank_count)
        stmt = stmt.where(Illust.pid.in_(window))
    return stmt


def _order(stmt: Select[Any], filters: GalleryFilters) -> Select[Any]:
    order = _SORTS.get(filters.sort, _SORTS["rank"])
    return stmt.order_by(*order)


async def query_gallery(
    session: AsyncSession, filters: GalleryFilters, *, offset: int, limit: int
) -> GalleryResponse:
    """Run the filtered/sorted query and compute absolute display indexes.

    Display indexes are 1-based positions within the *whole* filtered set, so
    they stay stable while paginating. A window function computes them in the
    database, avoiding a second full scan.
    """
    base = _build_base_select(filters)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    order = _SORTS.get(filters.sort, _SORTS["rank"])
    indexed = _order(base, filters).add_columns(
        func.row_number().over(order_by=order).label("display_index")
    )
    rows = (await session.execute(indexed.offset(offset).limit(limit))).all()

    items = [
        GalleryItem(
            pid=illust.pid,
            index=int(display_index),
            title=illust.title,
            author_id=author.id,
            author_name=author.name,
            page_count=illust.page_count,
            type=illust.type,
            x_restrict=illust.x_restrict,
            width=illust.width,
            height=illust.height,
            create_date=illust.create_date,
            rank=bookmark.rank,
            has_original=illust.has_original,
            page_downloaded_count=illust.page_downloaded_count,
            preview_url=f"/api/illust/{illust.pid}/thumb",
            thumb_url=f"/api/illust/{illust.pid}/thumb",
            restrict=bookmark.restrict,
            unbookmarked=bookmark.state == "unbookmarked",
            state=illust.state,
        )
        for illust, bookmark, author, display_index in rows
    ]
    return GalleryResponse(items=items, total=total, offset=offset, limit=limit)
