from datetime import timedelta

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from pixiv_archive.sync.scheduler import create_scheduler, parse_interval


def test_parse_interval_supported_units():
    assert parse_interval("30s") == timedelta(seconds=30)
    assert parse_interval("15m") == timedelta(minutes=15)
    assert parse_interval("6h") == timedelta(hours=6)
    assert parse_interval("1d") == timedelta(days=1)
    assert parse_interval(" 12H ") == timedelta(hours=12)


@pytest.mark.parametrize("value", ["", "6", "h", "6x", "-1h", "0h", "6 h"])
def test_parse_interval_rejects_invalid(value):
    with pytest.raises(ValueError):
        parse_interval(value)


def test_create_scheduler_registers_incremental_job():
    scheduler = create_scheduler(lambda: None, interval="6h")
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"sync-incremental"}
    assert isinstance(jobs["sync-incremental"].trigger, IntervalTrigger)
    assert jobs["sync-incremental"].max_instances == 1


def test_create_scheduler_registers_cron_job_when_configured():
    scheduler = create_scheduler(lambda: None, interval="6h", full_cron="0 3 * * 0")
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"sync-incremental", "sync-full"}
    assert isinstance(jobs["sync-full"].trigger, CronTrigger)


def test_create_scheduler_skips_cron_when_absent():
    scheduler = create_scheduler(lambda: None, interval="1h", full_cron=None)
    assert {job.id for job in scheduler.get_jobs()} == {"sync-incremental"}


def test_create_scheduler_returns_async_scheduler():
    scheduler = create_scheduler(lambda: None, interval="1h")
    assert isinstance(scheduler, AsyncIOScheduler)
