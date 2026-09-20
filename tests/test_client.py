import httpx
import pytest
import respx

from pixiv_archive.pixiv.client import (
    BOOKMARKS_URL,
    CLIENT_UA,
    ILLUST_DETAIL_URL,
    UGOIRA_URL,
    PixivClient,
)
from pixiv_archive.pixiv.errors import NotFoundError, PixivError

TOKEN_RESPONSE = {"response": {"access_token": "tok", "expires_in": 3600, "refresh_token": "r"}}


def _bookmark_page(ids: list[int], cursor: int | None = None) -> dict:
    next_url = (
        f"https://app-api.pixiv.net/v1/user/bookmarks/illust?user_id=1&max_bookmark_id={cursor}"
        if cursor
        else None
    )
    return {
        "illusts": [
            {
                "id": pid,
                "title": f"t{pid}",
                "type": "illust",
                "page_count": 1,
                "user": {"id": 9, "name": "author"},
                "meta_single_page": {"original_image_url": f"https://i.pximg.net/{pid}.jpg"},
                "image_urls": {"square_medium": f"https://i.pximg.net/{pid}_sq.jpg"},
            }
            for pid in ids
        ],
        "next_url": next_url,
    }


@pytest.fixture
async def client():
    c = PixivClient(
        refresh_token="r",
        user_id=1,
        proxy=None,
        min_interval_ms=0,
        client=httpx.AsyncClient(),
    )
    yield c
    await c.aclose()


@respx.mock
async def test_list_bookmarks_uses_bearer_and_restrict(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    route = respx.get(BOOKMARKS_URL).mock(
        return_value=httpx.Response(200, json=_bookmark_page([101, 102], cursor=555))
    )
    page = await client.list_bookmarks(restrict="public")
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer tok"
    assert request.headers["user-agent"] == CLIENT_UA
    assert "restrict=public" in str(request.url)
    assert "user_id=1" in str(request.url)
    assert [i.pid for i in page.illusts] == [101, 102]
    assert page.next_bookmark_id == 555


@respx.mock
async def test_list_bookmarks_passes_cursor(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    route = respx.get(BOOKMARKS_URL).mock(
        return_value=httpx.Response(200, json=_bookmark_page([103]))
    )
    await client.list_bookmarks(restrict="private", max_bookmark_id=555)
    assert "max_bookmark_id=555" in str(route.calls[0].request.url)


@respx.mock
async def test_bookmarks_404_raises_not_found(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    respx.get(BOOKMARKS_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(NotFoundError):
        await client.list_bookmarks(restrict="public")


@respx.mock
async def test_bookmarks_retries_on_500(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    route = respx.get(BOOKMARKS_URL).mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, json=_bookmark_page([42])),
        ]
    )
    page = await client.list_bookmarks(restrict="public")
    assert page.illusts[0].pid == 42
    assert route.call_count == 2


@respx.mock
async def test_bookmarks_reauthenticates_on_401(client):
    routes = respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(
            200, json={"response": {"access_token": "tok2", "expires_in": 3600}}
        )
    )
    respx.get(BOOKMARKS_URL).mock(
        side_effect=[
            httpx.Response(401, json={"error": {"user_message": "unauthorized"}}),
            httpx.Response(200, json=_bookmark_page([7])),
        ]
    )
    page = await client.list_bookmarks(restrict="public")
    assert page.illusts[0].pid == 7
    assert routes.call_count == 2


@respx.mock
async def test_bookmarks_api_error_payload_raises(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    respx.get(BOOKMARKS_URL).mock(
        return_value=httpx.Response(
            200, json={"error": {"user_message": "不正确的请求。"}, "illusts": []}
        )
    )
    with pytest.raises(PixivError):
        await client.list_bookmarks(restrict="public")


@respx.mock
async def test_get_illust_detail(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    respx.get(ILLUST_DETAIL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "illust": {
                    "id": 77,
                    "title": "x",
                    "type": "illust",
                    "page_count": 1,
                    "user": {"id": 1, "name": "n"},
                    "meta_single_page": {"original_image_url": "https://i.pximg.net/77.jpg"},
                    "image_urls": {},
                }
            },
        )
    )
    detail = await client.get_illust_detail(77)
    assert detail.illust.pid == 77


@respx.mock
async def test_get_illust_detail_deleted(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    respx.get(ILLUST_DETAIL_URL).mock(
        return_value=httpx.Response(404, json={"error": {"user_message": "作品已删除"}})
    )
    with pytest.raises(NotFoundError):
        await client.get_illust_detail(77)


@respx.mock
async def test_get_ugoira_metadata(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    respx.get(UGOIRA_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "ugoira_metadata": {
                    "zip_urls": {"medium": "https://i.pximg.net/u.zip"},
                    "frames": [{"file": "000000.jpg", "delay": 33}],
                }
            },
        )
    )
    meta = await client.get_ugoira_metadata(5)
    assert meta.zip_url == "https://i.pximg.net/u.zip"
    assert meta.frames[0].delay == 33


async def test_pixiv_client_uses_injected_http_client():
    """The injected httpx client must be the one performing requests."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=TOKEN_RESPONSE)

    c = PixivClient(
        refresh_token="r",
        user_id=1,
        proxy=None,
        min_interval_ms=0,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        token = await c.get_access_token_for_test()
    finally:
        await c.aclose()
    assert token == "tok"
    assert seen and seen[0].startswith("https://oauth.secure.pixiv.net/")
