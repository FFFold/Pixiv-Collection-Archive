from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust, IllustTag, Tag
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


async def test_gallery_status_filter(client):
    _login(client)
    database = client._transport.app.state.db  # type: ignore[union-attr]
    async with database.session() as session:
        session.add(Illust(pid=30, title="已失效", author_id=1, page_count=0, state="deleted"))
        await session.commit()
    async with database.session() as session:
        session.add(Bookmark(pid=30, restrict="public", rank=2048, state="active"))
        await session.commit()

    default = await client.get("/api/gallery")
    assert [item["pid"] for item in default.json()["items"]] == [10, 20]

    only = await client.get("/api/gallery", params={"only_deleted": True})
    payload = only.json()
    assert [item["pid"] for item in payload["items"]] == [30]
    assert payload["items"][0]["state"] == "deleted"

    everything = await client.get("/api/gallery", params={"include_deleted": True})
    assert [item["pid"] for item in everything.json()["items"]] == [10, 20, 30]


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


async def test_gallery_multi_tag_and_author_filters(client):
    _login(client)
    database = client._transport.app.state.db  # type: ignore[union-attr]

    async with database.session() as session:
        cat = Tag(name="cat")
        cute = Tag(name="cute")
        session.add(cat)
        session.add(cute)
        await session.flush()
        session.add(IllustTag(pid=10, tag_id=cat.id, position=0))
        session.add(IllustTag(pid=10, tag_id=cute.id, position=1))
        session.add(IllustTag(pid=20, tag_id=cat.id, position=0))
        await session.commit()

    both = await client.get("/api/gallery", params=[("tag", "cat"), ("tag", "cute")])
    assert both.status_code == 200
    assert [item["pid"] for item in both.json()["items"]] == [10]

    same_author = await client.get("/api/gallery", params=[("author_id", 1)])
    assert same_author.status_code == 200
    assert same_author.json()["total"] == 2

    union_authors = await client.get("/api/gallery", params=[("author_id", 1), ("author_id", 99)])
    assert union_authors.status_code == 200
    assert union_authors.json()["total"] == 2

    other_author = await client.get("/api/gallery", params=[("author_id", 99)])
    assert other_author.status_code == 200
    assert other_author.json()["total"] == 0


async def test_gallery_range_filters(client):
    _login(client)
    database = client._transport.app.state.db  # type: ignore[union-attr]
    async with database.session() as session:
        await session.execute(
            Illust.__table__.update()
            .where(Illust.pid == 10)
            .values(total_view=5, total_bookmarks=1)
        )
        await session.execute(
            Illust.__table__.update()
            .where(Illust.pid == 20)
            .values(total_view=5000, total_bookmarks=900)
        )
        await session.commit()

    pages = await client.get("/api/gallery", params={"page_min": 2})
    assert pages.status_code == 200
    assert [item["pid"] for item in pages.json()["items"]] == [10]

    pages_none = await client.get("/api/gallery", params={"page_min": 5})
    assert pages_none.status_code == 200
    assert pages_none.json()["items"] == []

    books = await client.get("/api/gallery", params={"bookmarks_min": 500})
    assert books.status_code == 200
    assert [item["pid"] for item in books.json()["items"]] == [20]

    views = await client.get("/api/gallery", params={"views_max": 100})
    assert views.status_code == 200
    assert [item["pid"] for item in views.json()["items"]] == [10]


async def test_gallery_empty_tag_is_ignored(client):
    """`?tag=` must behave like no tag filter (pre-refactor behavior)."""
    _login(client)
    response = await client.get("/api/gallery", params={"tag": ""})
    assert response.status_code == 200
    assert response.json()["total"] == 2


async def test_gallery_limit_accepts_240(client):
    _login(client)
    response = await client.get("/api/gallery", params={"limit": 240})
    assert response.status_code == 200
    assert response.json()["limit"] == 240

    too_large = await client.get("/api/gallery", params={"limit": 501})
    assert too_large.status_code == 422
