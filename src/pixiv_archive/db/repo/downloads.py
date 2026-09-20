from datetime import datetime

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import DownloadBatch, DownloadJob


async def create_batch(
    session: AsyncSession, *, scope: str, filter_json: str | None, now: datetime
) -> int:
    batch = DownloadBatch(scope=scope, filter_json=filter_json, created_at=now)
    session.add(batch)
    await session.flush()
    return batch.id


async def get_batch(session: AsyncSession, batch_id: int) -> DownloadBatch | None:
    return await session.get(DownloadBatch, batch_id)


async def enqueue_jobs(
    session: AsyncSession,
    *,
    batch_id: int,
    jobs: list[tuple[int, str, str]],
    now: datetime,
) -> int:
    """Insert ``(pid, kind, target)`` jobs, ignoring duplicates. Returns rows added.

    Existing jobs that are finished or failed are reset to pending so that a
    re-requested download actually re-runs.
    """
    added = 0
    for pid, kind, target in jobs:
        existing = (
            await session.execute(
                select(DownloadJob).where(
                    DownloadJob.pid == pid,
                    DownloadJob.kind == kind,
                    DownloadJob.target == target,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                DownloadJob(
                    batch_id=batch_id, pid=pid, kind=kind, target=target, created_at=now
                )
            )
            added += 1
        elif existing.status in ("done", "failed", "skipped"):
            existing.status = "pending"
            existing.batch_id = batch_id
            existing.last_error = None
            added += 1
    await session.flush()
    batch = await session.get(DownloadBatch, batch_id)
    if batch is not None:
        batch.total = (
            await session.execute(
                select(func.count())
                .select_from(DownloadJob)
                .where(DownloadJob.batch_id == batch_id)
            )
        ).scalar_one()
    return added


async def claim_pending_jobs(session: AsyncSession, *, limit: int) -> list[DownloadJob]:
    rows = await session.execute(
        select(DownloadJob)
        .where(DownloadJob.status == "pending")
        .order_by(DownloadJob.id)
        .limit(limit)
    )
    jobs = list(rows.scalars().all())
    for job in jobs:
        job.status = "running"
        job.attempts += 1
    await session.flush()
    return jobs


async def finish_job(
    session: AsyncSession, job_id: int, *, now: datetime, status: str = "done"
) -> None:
    job = await session.get(DownloadJob, job_id)
    if job is None:
        return
    job.status = status
    job.last_error = None
    job.updated_at = now


async def fail_job(session: AsyncSession, job_id: int, *, error: str, now: datetime) -> None:
    job = await session.get(DownloadJob, job_id)
    if job is None:
        return
    job.status = "failed"
    job.last_error = error[:500]
    job.updated_at = now


async def count_jobs_by_status(session: AsyncSession, batch_id: int) -> dict[str, int]:
    rows = await session.execute(
        select(DownloadJob.status, func.count())
        .where(DownloadJob.batch_id == batch_id)
        .group_by(DownloadJob.status)
    )
    return {status: count for status, count in rows}


async def reset_running_jobs(session: AsyncSession) -> int:
    """Return orphaned running jobs (e.g. from a crashed process) to pending."""
    result = await session.execute(
        update(DownloadJob).where(DownloadJob.status == "running").values(status="pending")
    )
    assert isinstance(result, CursorResult)
    return result.rowcount or 0


async def retry_failed_jobs(session: AsyncSession, *, batch_id: int | None = None) -> int:
    stmt = update(DownloadJob).where(DownloadJob.status == "failed")
    if batch_id is not None:
        stmt = stmt.where(DownloadJob.batch_id == batch_id)
    result = await session.execute(stmt.values(status="pending", last_error=None))
    assert isinstance(result, CursorResult)
    count = result.rowcount or 0
    if batch_id is not None:
        batch = await session.get(DownloadBatch, batch_id)
        if batch is not None:
            batch.failed = 0
            batch.status = "running"
            batch.finished_at = None
    return count


async def finalize_batch_if_done(session: AsyncSession, batch_id: int, *, now: datetime) -> bool:
    counts = await count_jobs_by_status(session, batch_id)
    pending = counts.get("pending", 0) + counts.get("running", 0)
    if pending > 0 or not counts:
        return False
    batch = await session.get(DownloadBatch, batch_id)
    if batch is None:
        return False
    batch.finished = counts.get("done", 0) + counts.get("skipped", 0)
    batch.failed = counts.get("failed", 0)
    batch.status = "completed" if batch.failed == 0 else "completed_with_failures"
    batch.finished_at = now
    return True


async def pending_job_count(session: AsyncSession) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(DownloadJob).where(DownloadJob.status == "pending")
        )
    ).scalar_one()


async def missing_pids(session: AsyncSession) -> list[int]:
    """Pids that have at least one pending/failed job, ordered by pid."""
    rows = await session.execute(
        select(DownloadJob.pid)
        .where(DownloadJob.status.in_(("pending", "failed")))
        .distinct()
        .order_by(DownloadJob.pid)
    )
    return [row[0] for row in rows]


async def jobs_for_pid(session: AsyncSession, pid: int) -> list[DownloadJob]:
    rows = await session.execute(
        select(DownloadJob).where(DownloadJob.pid == pid).order_by(DownloadJob.id)
    )
    return list(rows.scalars().all())
