from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Bookmark


async def get_bookmark_states(session: AsyncSession) -> dict[int, str]:
    rows = await session.execute(select(Bookmark.pid, Bookmark.state))
    return {pid: state for pid, state in rows}


async def get_rank_map(session: AsyncSession) -> dict[int, int]:
    rows = await session.execute(select(Bookmark.pid, Bookmark.rank))
    return {pid: rank for pid, rank in rows}


async def get_min_rank(session: AsyncSession) -> int | None:
    return (
        await session.execute(select(Bookmark.rank).order_by(Bookmark.rank).limit(1))
    ).scalar()


async def set_active_rank(
    session: AsyncSession, *, pid: int, restrict: str, rank: int, now: datetime
) -> bool:
    """Insert a bookmark or reactivate/relocate an existing one.

    Returns True when a new row was created.
    """
    existing = (
        await session.execute(select(Bookmark.id).where(Bookmark.pid == pid))
    ).scalar_one_or_none()
    stmt = insert(Bookmark).values(
        pid=pid,
        restrict=restrict,
        rank=rank,
        state="active",
        first_seen_at=now,
        last_seen_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Bookmark.pid],
        set_={
            "restrict": restrict,
            "rank": rank,
            "state": "active",
            "last_seen_at": now,
            "unbookmarked_at": None,
        },
    )
    await session.execute(stmt)
    return existing is None


async def touch_seen(session: AsyncSession, pids: list[int], *, now: datetime) -> None:
    if not pids:
        return
    await session.execute(update(Bookmark).where(Bookmark.pid.in_(pids)).values(last_seen_at=now))


async def mark_unbookmarked(session: AsyncSession, pids: list[int], *, now: datetime) -> int:
    if not pids:
        return 0
    result = await session.execute(
        update(Bookmark)
        .where(Bookmark.pid.in_(pids), Bookmark.state == "active")
        .values(state="unbookmarked", unbookmarked_at=now)
    )
    return result.rowcount or 0


async def ordered_pids(session: AsyncSession) -> list[int]:
    """All bookmarked pids ordered by rank; unbookmarked rows sort last."""
    rows = await session.execute(
        select(Bookmark.pid)
        .order_by(
            (Bookmark.state != "active"),
            Bookmark.rank,
        )
    )
    return [row[0] for row in rows]
