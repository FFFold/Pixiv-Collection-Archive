from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Bookmark, Illust, IllustPage, UgoiraMeta


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
            for value in (scope.author_id, scope.start, scope.count, scope.x_restrict, scope.type)
        )
        and not scope.pids
    )


def build_illust_filter(scope: DownloadScope) -> Select[tuple[int]]:
    """Build the SELECT over active, bookmarked illusts matching the scope."""
    stmt = (
        select(Illust.pid)
        .join(Bookmark, Bookmark.pid == Illust.pid)
        .where(Bookmark.state == "active", Illust.state == "active")
    )
    if scope.kind == "selected":
        if not scope.pids:
            return stmt.where(sa.false())
        return stmt.where(Illust.pid.in_(scope.pids)).order_by(Bookmark.rank)
    if scope.kind == "author":
        if scope.author_id is None:
            return stmt.where(sa.false())
        return stmt.where(Illust.author_id == scope.author_id).order_by(Bookmark.rank)
    if scope.kind == "rank_range":
        ordered = stmt.order_by(Bookmark.rank)
        if scope.start is not None or scope.count is not None:
            start = scope.start or 0
            ordered = ordered.offset(start)
            if scope.count is not None and scope.count >= 0:
                ordered = ordered.limit(scope.count)
        return ordered
    if scope.kind == "filter":
        conditions = []
        if scope.x_restrict is not None:
            conditions.append(Illust.x_restrict == scope.x_restrict)
        if scope.type is not None:
            conditions.append(Illust.type == scope.type)
        if scope.author_id is not None:
            conditions.append(Illust.author_id == scope.author_id)
        if scope.pids:
            conditions.append(Illust.pid.in_(scope.pids))
        if conditions:
            stmt = stmt.where(and_(*conditions))
    return stmt.order_by(Bookmark.rank)


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
