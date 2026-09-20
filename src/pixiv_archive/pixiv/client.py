from collections.abc import Callable
from typing import Any

import httpx

from pixiv_archive.pixiv.auth import APP_HEADERS, TokenProvider
from pixiv_archive.pixiv.errors import (
    AuthError,
    NetworkError,
    NotFoundError,
    PixivError,
    RateLimited,
)
from pixiv_archive.pixiv.models import BookmarkPage, IllustDetail, UgoiraMetadata
from pixiv_archive.pixiv.ratelimit import RateLimiter, retry_async

API_BASE = "https://app-api.pixiv.net"
BOOKMARKS_URL = f"{API_BASE}/v1/user/bookmarks/illust"
ILLUST_DETAIL_URL = f"{API_BASE}/v1/illust/detail"
UGOIRA_URL = f"{API_BASE}/v1/ugoira/metadata"

CLIENT_UA = APP_HEADERS["User-Agent"]


class PixivClient:
    """Minimal async client for the pixiv app API."""

    def __init__(
        self,
        refresh_token: str,
        user_id: int,
        *,
        proxy: str | None = None,
        min_interval_ms: int = 800,
        on_refresh_token: Callable[[str], None] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.user_id = user_id
        self._owns_client = client is None
        self._http = client or httpx.AsyncClient(proxy=proxy, timeout=30.0)
        self._tokens = TokenProvider(
            refresh_token,
            proxy=proxy,
            on_refresh_token=on_refresh_token,
            client=self._http,
        )
        self._limiter = RateLimiter(min_interval_ms)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def get_access_token_for_test(self) -> str:
        return await self._tokens.get_access_token()

    async def _request(
        self, method: str, url: str, *, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        async def _once() -> dict[str, Any]:
            await self._limiter.acquire()
            token = await self._tokens.get_access_token()
            headers = dict(APP_HEADERS)
            headers["Authorization"] = f"Bearer {token}"
            try:
                response = await self._http.request(method, url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                raise NetworkError(f"request to {url} failed: {exc}") from exc

            if response.status_code == 401:
                self._tokens.invalidate()
                raise AuthError("access token rejected (401)")
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                raise RateLimited(
                    "rate limited (429)",
                    retry_after=float(retry_after) if retry_after else None,
                )
            if response.status_code >= 500:
                raise NetworkError(f"server error {response.status_code}")
            if response.status_code == 404:
                raise NotFoundError(f"not found: {url}")
            if response.status_code >= 400:
                raise PixivError(f"HTTP {response.status_code}: {response.text[:200]}")

            payload: dict[str, Any] = response.json()
            if payload.get("error"):
                raise PixivError(str(payload["error"])[:300])
            return payload

        try:
            return await retry_async(_once, attempts=3, base_delay=0.6)
        except AuthError:
            # One retry after forced re-authentication.
            await self._tokens.get_access_token()
            return await retry_async(_once, attempts=2, base_delay=0.6)

    async def list_bookmarks(
        self, restrict: str, *, max_bookmark_id: int | None = None
    ) -> BookmarkPage:
        params: dict[str, str | int] = {"user_id": self.user_id, "restrict": restrict}
        if max_bookmark_id is not None:
            params["max_bookmark_id"] = max_bookmark_id
        payload = await self._request("GET", BOOKMARKS_URL, params=params)
        return BookmarkPage.model_validate(payload)

    async def get_illust_detail(self, illust_id: int) -> IllustDetail:
        payload = await self._request("GET", ILLUST_DETAIL_URL, params={"illust_id": illust_id})
        return IllustDetail.model_validate(payload)

    async def get_ugoira_metadata(self, illust_id: int) -> UgoiraMetadata:
        payload = await self._request("GET", UGOIRA_URL, params={"illust_id": illust_id})
        return UgoiraMetadata.from_response(payload)
