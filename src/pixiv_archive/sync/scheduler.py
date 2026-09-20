import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

_INTERVAL_RE = re.compile(r"^(\d+)([smhd])$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_interval(value: str) -> timedelta:
    """Parse "30m" / "6h" / "1d" style intervals."""
    match = _INTERVAL_RE.match((value or "").strip())
    if not match:
        raise ValueError(f"invalid interval {value!r}; expected e.g. '6h', '30m', '1d'")
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError(f"interval must be positive: {value!r}")
    return timedelta(seconds=amount * _UNIT_SECONDS[match.group(2).lower()])


def create_scheduler(
    incremental_job: Callable[[], Any],
    *,
    interval: str,
    full_cron: str | None = None,
    full_job: Callable[[], Any] | None = None,
) -> AsyncIOScheduler:
    """Build an AsyncIOScheduler with the incremental (and optional cron) sync jobs.

    Jobs are registered with ``max_instances=1`` so a slow sync run can never
    overlap with the next scheduled one.
    """
    scheduler = AsyncIOScheduler()
    delta = parse_interval(interval)
    scheduler.add_job(
        incremental_job,
        IntervalTrigger(seconds=delta.total_seconds()),
        id="sync-incremental",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    if full_cron:
        scheduler.add_job(
            full_job or incremental_job,
            CronTrigger.from_crontab(full_cron),
            id="sync-full",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
    return scheduler
