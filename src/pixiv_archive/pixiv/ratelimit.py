import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pixiv_archive.pixiv.errors import NetworkError, NotFoundError, PixivError, RateLimited

T = TypeVar("T")


class RateLimiter:
    """Serializes callers and enforces a minimum interval between acquisitions."""

    def __init__(self, min_interval_ms: int) -> None:
        self._min_interval = min_interval_ms / 1000.0
        self._lock = asyncio.Lock()
        self._last_at: float | None = None

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._last_at is not None:
                wait = self._min_interval - (now - self._last_at)
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_at = time.monotonic()


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.6,
    jitter: float = 0.3,
) -> T:
    """Run ``operation`` with exponential backoff on transient errors only.

    NotFoundError and other non-retryable PixivErrors propagate immediately.
    RateLimited sleeps for the server-provided Retry-After when present.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return await operation()
        except RateLimited as exc:
            last = exc
            delay = exc.retry_after if exc.retry_after is not None else base_delay * (2**attempt)
        except NetworkError as exc:
            last = exc
            delay = base_delay * (2**attempt) + random.uniform(0, jitter)
        except NotFoundError:
            raise
        except PixivError:
            raise
        if attempt == attempts - 1:
            break
        await asyncio.sleep(delay)
    assert last is not None
    raise last
