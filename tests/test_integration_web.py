"""Live web API verification against the real local archive.

Run with:
    uv run pytest tests/test_integration_web.py -m integration -v -s
Reads the configured DATA_DIR; the sync test additionally needs network access.
"""

from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from pixiv_archive.config import Settings
from pixiv_archive.web.app import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


@asynccontextmanager
async def _client(settings: Settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as http:
            yield http


async def test_live_gallery_requires_login_then_lists(settings):
    async with _client(settings) as client:
        assert (await client.get("/api/gallery")).status_code == 401
        login = await client.post("/api/auth/login", json={"token": settings.auth_token})
        assert login.status_code == 200

        response = await client.get("/api/gallery", params={"limit": 5})
        assert response.status_code == 200
        payload = response.json()
        print(f"\ntotal={payload['total']}")
        assert payload["total"] > 0
        first = payload["items"][0]
        print(f"first: #{first['index']} pid={first['pid']} {first['title'][:30]!r}")
        assert first["index"] == 1
        assert first["thumb_url"]


async def test_live_stats_detail_and_thumb(settings):
    async with _client(settings) as client:
        await client.post("/api/auth/login", json={"token": settings.auth_token})
        stats = (await client.get("/api/stats")).json()
        print(
            f"\nstats: total={stats['total_illusts']} pages={stats['total_pages']} "
            f"downloaded={stats['downloaded_pages']} bytes={stats['total_bytes']}"
        )
        assert stats["total_illusts"] > 0

        gallery = (await client.get("/api/gallery", params={"limit": 1})).json()
        pid = gallery["items"][0]["pid"]
        detail = (await client.get(f"/api/illust/{pid}")).json()
        assert detail["pid"] == pid
        assert detail["pixiv_url"].endswith(str(pid))

        thumb = await client.get(f"/api/illust/{pid}/thumb")
        assert thumb.status_code == 200
        print(f"thumb: {thumb.headers['content-type']} {len(thumb.content)} bytes")


async def test_live_filters_and_search(settings):
    async with _client(settings) as client:
        await client.post("/api/auth/login", json={"token": settings.auth_token})

        ugoira = (await client.get("/api/gallery", params={"type": "ugoira", "limit": 3})).json()
        print(f"\nugoira total={ugoira['total']}")
        assert ugoira["total"] > 0

        downloaded = (
            await client.get("/api/gallery", params={"downloaded": True, "limit": 3})
        ).json()
        print(f"downloaded total={downloaded['total']}")
        assert downloaded["total"] > 0

        authors = (await client.get("/api/authors", params={"limit": 3})).json()
        assert authors and authors[0]["illust_count"] > 0
        print(f"top author: {authors[0]['name']} ({authors[0]['illust_count']})")

        tags = (await client.get("/api/tags", params={"limit": 3})).json()
        print(f"top tag: {tags[0]['name'] if tags else 'n/a'}")


async def test_live_downloaded_file_served_with_range(settings):
    async with _client(settings) as client:
        await client.post("/api/auth/login", json={"token": settings.auth_token})
        gallery = (await client.get("/api/gallery", params={"limit": 1, "downloaded": True})).json()
        if not gallery["items"]:
            pytest.skip("no downloaded illusts available")
        pid = gallery["items"][0]["pid"]
        response = await client.get(f"/api/illust/{pid}/file/0", headers={"Range": "bytes=0-99"})
        assert response.status_code in (200, 206)
        if response.status_code == 206:
            assert response.headers["content-range"]
        assert len(response.content) > 0
        print(f"\nfile: pid={pid} status={response.status_code} bytes={len(response.content)}")


async def test_live_animation_served_for_ugoira(settings):
    async with _client(settings) as client:
        await client.post("/api/auth/login", json={"token": settings.auth_token})
        stats = (await client.get("/api/stats")).json()
        if stats["animation_ready"] == 0:
            pytest.skip("no transcoded ugoira available")
        gallery = (
            await client.get(
                "/api/gallery", params={"type": "ugoira", "downloaded": True, "limit": 10}
            )
        ).json()
        for item in gallery["items"]:
            response = await client.get(f"/api/illust/{item['pid']}/animation")
            if response.status_code == 200:
                assert response.headers["content-type"] == "video/mp4"
                print(f"\nanimation: pid={item['pid']} bytes={len(response.content)}")
                return
        pytest.skip("no animation file found among downloaded ugoira")
