import pytest
from httpx import ASGITransport, AsyncClient

from pixiv_archive.config import Settings
from pixiv_archive.web.app import create_app


@pytest.fixture
def settings(monkeypatch, tmp_path) -> Settings:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PIXIV_REFRESH_TOKEN", "tok")
    monkeypatch.setenv("PIXIV_USER_ID", "1")
    monkeypatch.setenv("AUTH_TOKEN", "sesame")
    return Settings(_env_file=None)


async def test_root_serves_spa_shell(settings):
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_unknown_spa_route_falls_back_to_shell(settings):
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/gallery/anything")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_unknown_api_route_returns_404_json(settings):
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"] == "not found"


async def test_api_docs_are_not_shadowed_by_spa(settings):
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/docs")).status_code == 200
        assert (await client.get("/openapi.json")).status_code == 200
