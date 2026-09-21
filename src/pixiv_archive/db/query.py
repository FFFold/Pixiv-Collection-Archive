"""Shared illust filtering used by gallery, downloads and export."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, and_, exists, or_, select, true

from pixiv_archive.db.models import Author, Bookmark, Illust, IllustTag, Tag


@dataclass
class IllustFilters:
    """All supported illust filters; empty means the default active set."""

    sort: str = "rank"
    tags: list[str] = field(default_factory=list)
    author_ids: list[int] = field(default_factory=list)
    q: str | None = None
    type: str | None = None
    x_restrict: int | None = None
    downloaded: bool | None = None
    restrict: str | None = None
    only_unbookmarked: bool = False
    include_unbookmarked: bool = False
    only_deleted: bool = False
    include_deleted: bool = False
    page_min: int | None = None
    page_max: int | None = None
    bookmarks_min: int | None = None
    bookmarks_max: int | None = None
    views_min: int | None = None
    views_max: int | None = None
    rank_start: int | None = None
    rank_count: int | None = None


SORTS: dict[str, tuple[Any, ...]] = {
    "rank": (Bookmark.rank.asc(),),
    "create_date": (Illust.create_date.desc(), Bookmark.rank.asc()),
    "bookmarks": (Illust.total_bookmarks.desc(), Bookmark.rank.asc()),
    "views": (Illust.total_view.desc(), Bookmark.rank.asc()),
}


def sort_order(filters: IllustFilters) -> tuple[Any, ...]:
    return SORTS.get(filters.sort, SORTS["rank"])


def _base_conditions(filters: IllustFilters) -> list[Any]:
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
    if filters.author_ids:
        conditions.append(Illust.author_id.in_(filters.author_ids))
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
    if filters.page_min is not None:
        conditions.append(Illust.page_count >= filters.page_min)
    if filters.page_max is not None:
        conditions.append(Illust.page_count <= filters.page_max)
    if filters.bookmarks_min is not None:
        conditions.append(Illust.total_bookmarks >= filters.bookmarks_min)
    if filters.bookmarks_max is not None:
        conditions.append(Illust.total_bookmarks <= filters.bookmarks_max)
    if filters.views_min is not None:
        conditions.append(Illust.total_view >= filters.views_min)
    if filters.views_max is not None:
        conditions.append(Illust.total_view <= filters.views_max)
    return conditions


def build_illust_query(filters: IllustFilters) -> Select[Any]:
    """Base query (Illust, Bookmark, Author) with every filter applied."""
    return _apply_filters(select(Illust, Bookmark, Author), filters)


def build_filtered_pids(filters: IllustFilters) -> Select[Any]:
    """Pid-only projection ordered by the requested sort."""
    return _apply_filters(select(Illust.pid), filters).order_by(*sort_order(filters))


def _apply_filters(stmt: Select[Any], filters: IllustFilters) -> Select[Any]:
    """Attach joins, conditions, tag EXISTS and the rank window to ``stmt``.

    Shared by the row query and the pid query so both stay in sync.
    """
    conditions = _base_conditions(filters)
    stmt = (
        stmt.join(Bookmark, Bookmark.pid == Illust.pid)
        .join(Author, Author.id == Illust.author_id)
        .where(and_(true(), *conditions))
    )
    for tag_name in filters.tags:
        stmt = stmt.where(
            exists(
                select(IllustTag.pid)
                .join(Tag, Tag.id == IllustTag.tag_id)
                .where(IllustTag.pid == Illust.pid, Tag.name == tag_name)
            )
        )
    if filters.rank_start is not None or filters.rank_count is not None:
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
