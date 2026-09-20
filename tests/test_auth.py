import httpx
import pytest
import respx

from pixiv_archive.pixiv.auth import CLIENT_ID, TOKEN_URL, TokenProvider
from pixiv_archive.pixiv.errors import AuthError

TOKEN_RESPONSE = {
    "response": {
        "access_token": "access-1",
        "refresh_token": "refresh-0",
        "expires_in": 3600,
        "user": {"id": "56269851", "name": "Yu_daa"},
    }
}


@pytest.fixture
def written_tokens():
    return []


@respx.mock
async def test_auth_fetches_and_caches_token(written_tokens):
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    provider = TokenProvider(
        refresh_token="refresh-0",
        proxy=None,
        on_refresh_token=lambda t: written_tokens.append(t),
        client=httpx.AsyncClient(),
    )
    token = await provider.get_access_token()
    assert token == "access-1"
    assert route.call_count == 1
    assert written_tokens == []  # identical refresh token not written back

    token = await provider.get_access_token()
    assert token == "access-1"
    assert route.call_count == 1  # cached


@respx.mock
async def test_auth_requests_correct_payload(written_tokens):
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    provider = TokenProvider(
        refresh_token="refresh-0",
        proxy=None,
        on_refresh_token=lambda t: written_tokens.append(t),
        client=httpx.AsyncClient(),
    )
    await provider.get_access_token()
    request = route.calls[0].request
    body = request.content.decode()
    assert "grant_type=refresh_token" in body
    assert "refresh_token=refresh-0" in body
    assert f"client_id={CLIENT_ID}" in body
    assert request.headers["app-os"] == "ios"


@respx.mock
async def test_rotated_refresh_token_is_written_back(written_tokens):
    rotated = dict(TOKEN_RESPONSE)
    rotated["response"] = dict(TOKEN_RESPONSE["response"])
    rotated["response"]["refresh_token"] = "refresh-2"
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=rotated))
    provider = TokenProvider(
        refresh_token="refresh-0",
        proxy=None,
        on_refresh_token=lambda t: written_tokens.append(t),
        client=httpx.AsyncClient(),
    )
    await provider.get_access_token()
    assert written_tokens == ["refresh-2"]


@respx.mock
async def test_expired_token_is_refreshed(written_tokens, monkeypatch):
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    provider = TokenProvider(
        refresh_token="refresh-0",
        proxy=None,
        on_refresh_token=lambda t: written_tokens.append(t),
        client=httpx.AsyncClient(),
    )
    await provider.get_access_token()
    monkeypatch.setattr("pixiv_archive.pixiv.auth.time.monotonic", lambda: 10**9)
    await provider.get_access_token()
    assert route.call_count == 2


@respx.mock
async def test_auth_error_on_400(written_tokens):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    provider = TokenProvider(
        refresh_token="bad",
        proxy=None,
        on_refresh_token=lambda t: written_tokens.append(t),
        client=httpx.AsyncClient(),
    )
    with pytest.raises(AuthError):
        await provider.get_access_token()


@respx.mock
async def test_auth_network_error_is_retried(written_tokens):
    route = respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.ConnectTimeout("timeout"),
            httpx.Response(200, json=TOKEN_RESPONSE),
        ]
    )
    provider = TokenProvider(
        refresh_token="refresh-0",
        proxy=None,
        on_refresh_token=lambda t: written_tokens.append(t),
        client=httpx.AsyncClient(),
    )
    assert await provider.get_access_token() == "access-1"
    assert route.call_count == 2


async def test_invalidate_forces_refresh():
    provider = TokenProvider(
        refresh_token="r",
        proxy=None,
        on_refresh_token=lambda t: None,
        client=httpx.AsyncClient(),
    )
    provider._access_token = "stale"
    provider._expires_at = 10**12
    provider.invalidate()
    assert provider._access_token is None
