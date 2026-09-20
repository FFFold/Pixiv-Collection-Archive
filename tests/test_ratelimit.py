import asyncio

import pytest

from pixiv_archive.pixiv.errors import NetworkError, NotFoundError, RateLimited
from pixiv_archive.pixiv.ratelimit import RateLimiter, retry_async


async def test_retry_succeeds_after_transient_failure():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise NetworkError("boom")
        return "ok"

    result = await retry_async(flaky, attempts=3, base_delay=0.01)
    assert result == "ok"
    assert calls["n"] == 3


async def test_retry_gives_up_after_attempts():
    async def always_fail():
        raise NetworkError("nope")

    with pytest.raises(NetworkError):
        await retry_async(always_fail, attempts=2, base_delay=0.01)


async def test_retry_does_not_retry_not_found():
    calls = {"n": 0}

    async def not_found():
        calls["n"] += 1
        raise NotFoundError("gone")

    with pytest.raises(NotFoundError):
        await retry_async(not_found, attempts=3, base_delay=0.01)
    assert calls["n"] == 1


async def test_rate_limited_respects_retry_after(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("pixiv_archive.pixiv.ratelimit.asyncio.sleep", fake_sleep)
    calls = {"n": 0}

    async def limited():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimited("slow down", retry_after=2.5)
        return "ok"

    assert await retry_async(limited, attempts=3, base_delay=0.01) == "ok"
    assert slept and slept[0] == 2.5


async def test_rate_limiter_enforces_min_interval(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("pixiv_archive.pixiv.ratelimit.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("pixiv_archive.pixiv.ratelimit.time.monotonic", lambda: 100.0)

    limiter = RateLimiter(min_interval_ms=800)
    await limiter.acquire()
    assert slept == []  # first call never waits
    await limiter.acquire()
    assert slept == [pytest.approx(0.8)]


async def test_rate_limiter_serializes_concurrent_callers(monkeypatch):
    order: list[str] = []
    now = {"t": 0.0}

    async def fake_sleep(seconds: float) -> None:
        now["t"] += seconds

    monkeypatch.setattr("pixiv_archive.pixiv.ratelimit.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("pixiv_archive.pixiv.ratelimit.time.monotonic", lambda: now["t"])

    limiter = RateLimiter(min_interval_ms=100)

    async def worker(name: str) -> None:
        await limiter.acquire()
        order.append(name)

    await asyncio.gather(worker("a"), worker("b"), worker("c"))
    assert order == ["a", "b", "c"]


def test_error_hierarchy():
    assert issubclass(NotFoundError, Exception)
    e = RateLimited("x", retry_after=1.0)
    assert e.retry_after == 1.0
