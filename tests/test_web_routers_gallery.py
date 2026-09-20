from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust
from pixiv_archive.web.auth import SessionSigner
from pixiv_archive.web.routers.auth import protected
from pixiv_archive.web.routers.auth import router as auth_router
from pixiv_archive.web.routers.gallery import router as gallery_router


@pytest.fixture
async def client(tmp_path):
    database = Database(tmp_path / "api.db")
    await database.create_all()
    async with database.session() as session:
        session.add(Author(id=1, name="画师", account="acct"))
        await session.commit()
    async with database.session() as session:
        session.add(
            Illust(
                pid=10,
                title="作品十",
                author_id=1,
                page_count=2,
                create_date=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        session.add(
            Illust(
                pid=20,
                title="作品二十",
                author_id=1,
                page_count=1,
                create_date=datetime(2026, 2, 1, tzinfo=UTC),
            )
        )
        await session.commit()
    async with database.session() as session:
        session.add(Bookmark(pid=10, restrict="public", rank=0, state="active"))
        session.add(Bookmark(pid=20, restrict="public", rank=1024, state="active"))
        await session.commit()

    app = FastAPI()
    signer = SessionSigner("secret")
    app.state.db = database
    app.state.session_signer = signer
    app.state.settings = type("S", (), {"auth_token": "sesame"})()
    app.include_router(auth_router)
    app.include_router(protected)
    app.include_router(gallery_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as http:
        http._signer = signer  # type: ignore[attr-defined]
        yield http
    await database.dispose()


def _login(client: AsyncClient) -> None:
    client.cookies.set("session", client._signer.sign("ok"))  # type: ignore[attr-defined]


async def test_gallery_requires_auth(client):
    response = await client.get("/api/gallery")
    assert response.status_code == 401


async def test_gallery_returns_items(client):
    _login(client)
    response = await client.get("/api/gallery")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert [item["pid"] for item in payload["items"]] == [10, 20]
    assert [item["index"] for item in payload["items"]] == [1, 2]
    assert payload["items"][0]["author_name"] == "画师"


async def test_gallery_filters_and_search(client):
    _login(client)
    filtered = await client.get("/api/gallery", params={"q": "二十"})
    assert [item["pid"] for item in filtered.json()["items"]] == [20]

    typed = await client.get("/api/gallery", params={"type": "ugoira"})
    assert typed.json()["total"] == 0


async def test_gallery_sort_and_rank_range(client):
    _login(client)
    by_date = await client.get("/api/gallery", params={"sort": "create_date"})
    assert [item["pid"] for item in by_date.json()["items"]] == [20, 10]

    ranged = await client.get("/api/gallery", params={"rank_start": 1, "rank_count": 1})
    assert [item["pid"] for item in ranged.json()["items"]] == [20]


async def test_authors_endpoint(client):
    _login(client)
    response = await client.get("/api/authors")
    assert response.status_code == 200
    authors = response.json()
    assert authors[0]["id"] == 1
    assert authors[0]["illust_count"] == 2


async def test_tags_endpoint(client):
    _login(client)
    response = await client.get("/api/tags")
    assert response.status_code == 200
    assert response.json() == []


async def test_login_and_logout(client):
    bad = await client.post("/api/auth/login", json={"token": "wrong"})
    assert bad.status_code == 401

    ok = await client.post("/api/auth/login", json={"token": "sesame"})
    assert ok.status_code == 200
    assert ok.json()["authenticated"] is True
    assert client.cookies.get("session")

    me = await client.get("/api/auth/me")
    assert me.json()["authenticated"] is True

    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 200
    client.cookies.clear()
    assert (await client.get("/api/auth/me")).json()["authenticated"] is False


async def test_login_unavailable_without_token(client):
    client._transport.app.state.settings = type("S", (), {"auth_token": None})()  # type: ignore[union-attr]
    response = await client.post("/api/auth/login", json={"token": "x"})
    assert response.status_code == 503
