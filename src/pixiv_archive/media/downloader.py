import asyncio
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from pixiv_archive.media.storage import atomic_write_bytes
from pixiv_archive.pixiv.auth import APP_HEADERS
from pixiv_archive.pixiv.errors import NetworkError, NotFoundError, PixivError
from pixiv_archive.pixiv.ratelimit import retry_async

PIXIV_IMAGE_HOSTS = frozenset({"i.pximg.net", "i-f.pximg.net", "s.pximg.net"})
_SCHEME_RE = re.compile(r"^https?://")
_REFERER = "https://www.pixiv.net/"


def _normalize_mirror(mirror: str | None) -> str | None:
    if not mirror:
        return None
    value = _SCHEME_RE.sub("", mirror.strip()).strip().rstrip("/")
    if not value or re.search(r"\s", value):
        return None
    return value


def apply_image_mirror(url: str, mirror: str | None) -> str:
    """Rewrite official pixiv image hosts to a configured mirror host."""
    normalized = _normalize_mirror(mirror)
    if not normalized or not url:
        return url
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    if (parsed.hostname or "").lower() not in PIXIV_IMAGE_HOSTS:
        return url
    suffix = f"?{parsed.query}" if parsed.query else ""
    return f"https://{normalized}{parsed.path}{suffix}"


class ImageDownloader:
    """Fetches image bytes with retry, mirror fallback and a concurrency cap."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        mirror: str | None = None,
        concurrency: int = 4,
        on_error: Callable[[str, str], None] | None = None,
    ) -> None:
        self._client = client
        self._mirror = _normalize_mirror(mirror)
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._on_error = on_error

    def _candidates(self, url: str) -> list[str]:
        mirrored = apply_image_mirror(url, self._mirror)
        if mirrored != url:
            return [mirrored, url]
        return [url]

    async def fetch_bytes(self, url: str) -> bytes | None:
        async with self._semaphore:
            for candidate in self._candidates(url):
                data = await self._fetch_once(candidate)
                if data is not None:
                    return data
            return None

    async def _fetch_once(self, url: str) -> bytes | None:
        async def _attempt() -> httpx.Response:
            try:
                response = await self._client.get(
                    url, headers={"Referer": _REFERER, "User-Agent": APP_HEADERS["User-Agent"]}
                )
            except httpx.HTTPError as exc:
                raise NetworkError(str(exc)) from exc
            if response.status_code >= 500 or response.status_code == 429:
                raise NetworkError(f"HTTP {response.status_code}")
            return response

        try:
            response = await retry_async(_attempt, attempts=3, base_delay=0.6)
        except NotFoundError:
            return None
        except NetworkError:
            return None
        except PixivError:
            return None
        if response.status_code >= 300:
            return None
        return response.content

    async def fetch_to_file(self, url: str, dest: Path) -> bool:
        data = await self.fetch_bytes(url)
        if data is None:
            return False
        atomic_write_bytes(dest, data)
        return True
