import asyncio
import time
from collections.abc import Callable

import httpx

from pixiv_archive.pixiv.errors import AuthError, NetworkError
from pixiv_archive.pixiv.ratelimit import retry_async

TOKEN_URL = "https://oauth.secure.pixiv.net/auth/token"
CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"

APP_HEADERS = {
    "User-Agent": "PixivIOSApp/7.13.1 (iOS 14.6; iPhone13,2)",
    "App-OS": "ios",
    "App-OS-Version": "14.6",
    "App-Version": "7.13.1",
    "Accept-Language": "zh-CN",
}

_REFRESH_MARGIN_SECONDS = 300


class TokenProvider:
    """Exchanges a refresh token for short-lived access tokens, with caching."""

    def __init__(
        self,
        refresh_token: str,
        *,
        proxy: str | None = None,
        on_refresh_token: Callable[[str], None] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._refresh_token = refresh_token
        self._on_refresh_token = on_refresh_token or (lambda _t: None)
        self._client = client or httpx.AsyncClient(proxy=proxy, timeout=30.0)
        self._owns_client = client is None
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client

    def invalidate(self) -> None:
        self._access_token = None
        self._expires_at = 0.0

    async def get_access_token(self) -> str:
        async with self._lock:
            if self._access_token is not None and time.monotonic() < self._expires_at:
                return self._access_token
            await self._refresh()
            assert self._access_token is not None
            return self._access_token

    async def _refresh(self) -> None:
        async def _exchange() -> httpx.Response:
            try:
                return await self._client.post(
                    TOKEN_URL,
                    data={
                        "client_id": CLIENT_ID,
                        "client_secret": CLIENT_SECRET,
                        "grant_type": "refresh_token",
                        "include_policy": "true",
                        "refresh_token": self._refresh_token,
                    },
                    headers=APP_HEADERS,
                )
            except httpx.HTTPError as exc:
                raise NetworkError(f"token request failed: {exc}") from exc

        response = await retry_async(_exchange, attempts=3, base_delay=0.6)
        if response.status_code >= 400:
            raise AuthError(
                f"token exchange failed with HTTP {response.status_code}: {response.text[:200]}"
            )
        payload = response.json().get("response") or {}
        access_token = payload.get("access_token")
        if not access_token:
            raise AuthError(f"token response missing access_token: {response.text[:200]}")

        new_refresh = payload.get("refresh_token")
        if new_refresh and new_refresh != self._refresh_token:
            self._refresh_token = new_refresh
            self._on_refresh_token(new_refresh)

        self._access_token = access_token
        expires_in = payload.get("expires_in", 3600)
        self._expires_at = time.monotonic() + expires_in - _REFRESH_MARGIN_SECONDS

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
