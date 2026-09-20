import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import (
    Author,
    Bookmark,
    Illust,
    IllustPage,
    IllustTag,
    Tag,
    UgoiraMeta,
)
from pixiv_archive.web.auth import SessionSigner
from pixiv_archive.web.routers.illust import router as illust_router

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xd2\xcf \xff\xd9"
)


@pytest.fixture
async def client(tmp_path):
    database = Database(tmp_path / "ill.db")
    await database.create_all()
    works = tmp_path / "works"
    (works / "10" / "original").mkdir(parents=True)
    (works / "10" / "original" / "000_p0.jpg").write_bytes(JPEG)
    (works / "10" / "thumb.webp").write_bytes(b"RIFFxxxxWEBP")
    (works / "10" / "animation.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")

    async with database.session() as session:
        session.add(Author(id=1, name="画师", account="acct"))
        session.add(
            Illust(
                pid=10,
                title="作品十",
                description="描述",
                author_id=1,
                page_count=2,
                type="ugoira",
                has_original=False,
                page_downloaded_count=1,
            )
        )
        await session.commit()
    async with database.session() as session:
        session.add(
            IllustPage(
                pid=10,
                page_index=0,
                original_url="https://x/0.jpg",
                ext=".jpg",
                download_state="done",
            )
        )
        session.add(
            IllustPage(
                pid=10,
                page_index=1,
                original_url="https://x/1.jpg",
                ext=".jpg",
                download_state="pending",
            )
        )
        session.add(
            UgoiraMeta(pid=10, zip_url="https://x/u.zip", frames_json="[]", frame_count=126)
        )
        session.add(Bookmark(pid=10, restrict="private", rank=0, state="active"))
        tag = Tag(name="猫")
        session.add(tag)
        await session.flush()
        session.add(IllustTag(pid=10, tag_id=tag.id, position=0))
        await session.commit()

    app = FastAPI()
    app.state.db = database
    app.state.settings = type("S", (), {"works_dir": works})()
    app.state.session_signer = SessionSigner("secret")
    app.include_router(illust_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as http:
        http.cookies.set("session", app.state.session_signer.sign("ok"))
        yield http
    await database.dispose()


async def test_illust_detail(client):
    response = await client.get("/api/illust/10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["pid"] == 10
    assert payload["title"] == "作品十"
    assert payload["tags"] == ["猫"]
    assert payload["page_count"] == 2
    assert payload["page_downloaded_count"] == 1
    assert payload["restrict"] == "private"
    assert payload["rank"] == 0
    assert payload["index"] == 1
    assert payload["pixiv_url"] == "https://www.pixiv.net/artworks/10"
    assert payload["animation_available"] is True
    assert payload["frame_count"] == 126
    assert payload["pages"][0]["download_state"] == "done"
    assert payload["pages"][1]["download_state"] == "pending"


async def test_illust_detail_404(client):
    response = await client.get("/api/illust/999")
    assert response.status_code == 404


async def test_illust_file_serves_local_original(client):
    response = await client.get("/api/illust/10/file/0")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert "ETag" in response.headers


async def test_illust_file_404_when_missing(client):
    response = await client.get("/api/illust/10/file/1")
    assert response.status_code == 404


async def test_illust_file_supports_range(client):
    response = await client.get("/api/illust/10/file/0", headers={"Range": "bytes=0-9"})
    assert response.status_code == 206
    assert response.headers["content-range"].startswith("bytes 0-9/")


async def test_illust_file_etag_304(client):
    first = await client.get("/api/illust/10/file/0")
    etag = first.headers["ETag"]
    second = await client.get("/api/illust/10/file/0", headers={"If-None-Match": etag})
    assert second.status_code == 304


async def test_illust_thumb_prefers_local_webp(client):
    response = await client.get("/api/illust/10/thumb")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"


async def test_illust_thumb_placeholder_when_missing(client):
    response = await client.get("/api/illust/999/thumb")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg")


async def test_illust_animation(client):
    response = await client.get("/api/illust/10/animation")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"


async def test_illust_ugoira_zip_missing(client):
    response = await client.get("/api/illust/10/ugoira.zip")
    assert response.status_code == 404
