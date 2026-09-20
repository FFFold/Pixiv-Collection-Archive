"""Live integration tests against the real pixiv API.

Run manually with:
    uv run pytest tests/test_integration_live.py -m integration -v -s
These require PIXIV_REFRESH_TOKEN, PIXIV_USER_ID and network/proxy access.
"""

import pytest

from pixiv_archive.pixiv.client import PixivClient

pytestmark = pytest.mark.integration


@pytest.fixture
def live_settings():
    from pixiv_archive.config import Settings

    return Settings(_env_file=None)  # type: ignore[call-arg]


async def test_live_bookmark_page_parses_with_urls(live_settings):
    client = PixivClient(
        refresh_token=live_settings.pixiv_refresh_token,
        user_id=live_settings.pixiv_user_id,
        proxy=live_settings.pixiv_proxy,
        min_interval_ms=live_settings.api_min_interval_ms,
    )
    try:
        page = await client.list_bookmarks(restrict="public")
    finally:
        await client.aclose()

    assert len(page.illusts) > 0
    first = page.illusts[0]
    assert first.pid > 0
    assert first.original_urls, "bookmark list must carry original urls"
    assert first.preview_url
    print(f"\nfirst pid={first.pid} title={first.title!r} pages={first.page_count}")
    print(f"original={first.original_urls[0]}")
    print(f"next_bookmark_id={page.next_bookmark_id}")


async def test_live_pagination_is_descending_by_bookmark_time(live_settings):
    """The lists are ordered by bookmark time; ensure the cursor advances strictly."""
    client = PixivClient(
        refresh_token=live_settings.pixiv_refresh_token,
        user_id=live_settings.pixiv_user_id,
        proxy=live_settings.pixiv_proxy,
        min_interval_ms=live_settings.api_min_interval_ms,
    )
    try:
        first = await client.list_bookmarks(restrict="public")
        assert first.next_bookmark_id is not None
        second = await client.list_bookmarks(
            restrict="public", max_bookmark_id=first.next_bookmark_id
        )
    finally:
        await client.aclose()

    first_ids = {i.pid for i in first.illusts}
    second_ids = {i.pid for i in second.illusts}
    assert not (first_ids & second_ids), "pages must not overlap"


async def test_live_illust_detail_and_ugoira(live_settings):
    client = PixivClient(
        refresh_token=live_settings.pixiv_refresh_token,
        user_id=live_settings.pixiv_user_id,
        proxy=live_settings.pixiv_proxy,
        min_interval_ms=live_settings.api_min_interval_ms,
    )
    try:
        page = await client.list_bookmarks(restrict="public")
        detail = await client.get_illust_detail(page.illusts[0].pid)
        assert detail.illust.pid == page.illusts[0].pid

        search = await client._request(
            "GET",
            "https://app-api.pixiv.net/v1/search/illust",
            params={
                "word": "うごイラ",
                "search_target": "partial_match_for_tags",
                "sort": "date_desc",
                "filter": "for_ios",
            },
        )
        ugoira_id = next(i["id"] for i in search.get("illusts", []) if i.get("type") == "ugoira")
        meta = await client.get_ugoira_metadata(ugoira_id)
        assert meta.zip_url
        assert len(meta.frames) > 0
        print(f"\nugoira {ugoira_id}: {len(meta.frames)} frames, zip={meta.zip_url}")
    finally:
        await client.aclose()
