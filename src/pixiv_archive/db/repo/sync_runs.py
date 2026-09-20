from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import SyncRun


async def create_run(session: AsyncSession, kind: str, *, now: datetime) -> int:
    run = SyncRun(kind=kind, status="running", started_at=now)
    session.add(run)
    await session.flush()
    return run.id


async def finish_run(
    session: AsyncSession,
    run_id: int,
    *,
    status: str,
    pages_fetched: int,
    new_count: int,
    unbookmarked_count: int,
    rank_rebuilt_count: int,
    previews_fetched: int,
    previews_failed: int,
    failed_count: int,
    error: str | None,
    now: datetime,
) -> None:
    run = await session.get(SyncRun, run_id)
    if run is None:
        return
    run.status = status
    run.finished_at = now
    run.pages_fetched = pages_fetched
    run.new_count = new_count
    run.unbookmarked_count = unbookmarked_count
    run.rank_rebuilt_count = rank_rebuilt_count
    run.previews_fetched = previews_fetched
    run.previews_failed = previews_failed
    run.failed_count = failed_count
    run.error = error


async def get_last_full_sync(session: AsyncSession) -> datetime | None:
    return (
        await session.execute(
            select(SyncRun.finished_at)
            .where(SyncRun.kind == "full", SyncRun.status == "completed")
            .order_by(SyncRun.finished_at.desc())
            .limit(1)
        )
    ).scalar()
