from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Illust, IllustPage, UgoiraMeta
from pixiv_archive.db.query import IllustFilters, build_filtered_pids


@dataclass(frozen=True)
class DownloadScope:
    """Which illusts a download request should cover."""

    kind: str
    pids: list[int] = field(default_factory=list)
    author_id: int | None = None
    start: int | None = None
    count: int | None = None
    x_restrict: int | None = None
    type: str | None = None
    # filter-scope extras (shared with the gallery filters)
    tags: list[str] = field(default_factory=list)
    author_ids: list[int] = field(default_factory=list)
    q: str | None = None
    restrict: str | None = None
    downloaded: bool | None = None
    page_min: int | None = None
    page_max: int | None = None
    bookmarks_min: int | None = None
    bookmarks_max: int | None = None
    views_min: int | None = None
    views_max: int | None = None
    only_unbookmarked: bool = False
    include_unbookmarked: bool = False


@dataclass
class ScopePlan:
    pids: list[int]
    jobs: list[tuple[int, str, str]]


def empty_scope_matches_nothing(scope: DownloadScope) -> bool:
    """A plain filter scope with no criteria would select the whole library."""
    if scope.kind != "filter":
        return False
    return (
        all(
            value is None
            for value in (
                scope.author_id,
                scope.start,
                scope.count,
                scope.x_restrict,
                scope.type,
                scope.q,
                scope.restrict,
                scope.downloaded,
                scope.page_min,
                scope.page_max,
                scope.bookmarks_min,
                scope.bookmarks_max,
                scope.views_min,
                scope.views_max,
            )
        )
        and not scope.pids
        and not scope.tags
        and not scope.author_ids
        and not scope.only_unbookmarked
        and not scope.include_unbookmarked
    )


def _filters_from_filter_scope(scope: DownloadScope) -> IllustFilters:
    author_ids = list(scope.author_ids)
    if scope.author_id is not None and scope.author_id not in author_ids:
        author_ids.append(scope.author_id)
    return IllustFilters(
        tags=scope.tags,
        author_ids=author_ids,
        q=scope.q,
        type=scope.type,
        x_restrict=scope.x_restrict,
        downloaded=scope.downloaded,
        restrict=scope.restrict,
        page_min=scope.page_min,
        page_max=scope.page_max,
        bookmarks_min=scope.bookmarks_min,
        bookmarks_max=scope.bookmarks_max,
        views_min=scope.views_min,
        views_max=scope.views_max,
        only_unbookmarked=scope.only_unbookmarked,
        include_unbookmarked=scope.include_unbookmarked,
    )


def build_illust_filter(scope: DownloadScope) -> Select[tuple[int]]:
    """Build the pid SELECT over active, bookmarked illusts matching the scope."""
    if scope.kind == "selected":
        if not scope.pids:
            return build_filtered_pids(IllustFilters()).where(sa.false())
        return build_filtered_pids(IllustFilters()).where(Illust.pid.in_(scope.pids))
    if scope.kind == "author":
        if scope.author_id is None:
            return build_filtered_pids(IllustFilters()).where(sa.false())
        return build_filtered_pids(IllustFilters(author_ids=[scope.author_id]))
    if scope.kind == "rank_range":
        ordered = build_filtered_pids(IllustFilters())
        if scope.start is not None or scope.count is not None:
            start = scope.start or 0
            ordered = ordered.offset(start)
            if scope.count is not None and scope.count >= 0:
                ordered = ordered.limit(scope.count)
        return ordered
    if scope.kind == "filter":
        if empty_scope_matches_nothing(scope):
            return build_filtered_pids(IllustFilters()).where(sa.false())
        stmt = build_filtered_pids(_filters_from_filter_scope(scope))
        if scope.pids:
            stmt = stmt.where(Illust.pid.in_(scope.pids))
        return stmt
    # all_missing: every active, bookmarked illust
    return build_filtered_pids(IllustFilters())


async def resolve_scope(session: AsyncSession, scope: DownloadScope) -> ScopePlan:
    """Turn a scope into concrete job tuples ``(pid, kind, target)``.

    Image jobs are only created for pages that are not yet downloaded; thumb
    jobs for every selected illust; ugoira jobs for zip + transcode.
    """
    if empty_scope_matches_nothing(scope):
        return ScopePlan(pids=[], jobs=[])

    pid_rows = (await session.execute(build_illust_filter(scope))).scalars().all()
    pids = list(pid_rows)
    if not pids:
        return ScopePlan(pids=[], jobs=[])

    type_rows = (
        await session.execute(select(Illust.pid, Illust.type).where(Illust.pid.in_(pids)))
    ).all()
    types = {pid: kind for pid, kind in type_rows}

    page_rows = (
        await session.execute(
            select(
                IllustPage.pid,
                IllustPage.page_index,
                IllustPage.download_state,
                IllustPage.ext,
            )
            .where(IllustPage.pid.in_(pids))
            .order_by(IllustPage.pid, IllustPage.page_index)
        )
    ).all()
    pending_pages: dict[int, list[tuple[int, str]]] = {}
    for pid, page_index, state, ext in page_rows:
        if state != "done":
            pending_pages.setdefault(pid, []).append((page_index, ext))

    ugoira_pids = {
        row[0]
        for row in (
            await session.execute(select(UgoiraMeta.pid).where(UgoiraMeta.pid.in_(pids)))
        ).all()
    }

    jobs: list[tuple[int, str, str]] = []
    for pid in pids:
        for page_index, ext in pending_pages.get(pid, []):
            jobs.append((pid, "image", f"{page_index:03d}_p{page_index}{ext}"))
        if types.get(pid) == "ugoira" and pid in ugoira_pids:
            jobs.append((pid, "ugoira_zip", "source.zip"))
            jobs.append((pid, "ugoira_mp4", "animation.mp4"))
        jobs.append((pid, "thumb", "thumb.webp"))
    return ScopePlan(pids=pids, jobs=jobs)
