import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import (
    Author,
    Bookmark,
    Illust,
    IllustPage,
    UgoiraMeta,
)
from pixiv_archive.web.auth import SessionSigner
from pixiv_archive.web.routers.export import router as export_router
from pixiv_archive.web.routers.stats import router as stats_router
from pixiv_archive.web.tasks import TaskManager


@pytest.fixture
async def client(tmp_path):
    database = Database(tmp_path / "se.db")
    await database.create_all()
    works = tmp_path / "works"
    (works / "10" / "original").mkdir(parents=True)
    (works / "10" / "original" / "000_p0.jpg").write_bytes(b"jpeg-bytes")
    (works / "10" / "thumb.webp").write_bytes(b"webp-bytes")
    (works / "10" / "animation.mp4").write_bytes(b"mp4-bytes")
    (works / "10" / "meta.json").write_text('{"id": 10}', encoding="utf-8")

    async with database.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(
            Illust(
                pid=10,
                title="t",
                author_id=1,
                type="ugoira",
                has_original=True,
                page_downloaded_count=1,
            )
        )
        session.add(Illust(pid=20, title="u", author_id=1, has_original=False))
        await session.commit()
    async with database.session() as session:
        session.add(
            IllustPage(pid=10, page_index=0, original_url="x", ext=".jpg", download_state="done")
        )
        session.add(
            IllustPage(pid=20, page_index=0, original_url="y", ext=".jpg", download_state="pending")
        )
        session.add(UgoiraMeta(pid=10, zip_url="z", frames_json="[]", frame_count=5))
        await session.commit()
    async with database.session() as session:
        session.add(Bookmark(pid=10, restrict="public", rank=0, state="active"))
        session.add(Bookmark(pid=20, restrict="private", rank=1024, state="active"))
        await session.commit()

    app = FastAPI()
    app.state.db = database
    app.state.session_signer = SessionSigner("secret")
    app.state.tasks = TaskManager()
    app.state.events = app.state.tasks.events
    app.state.settings = type(
        "S",
        (),
        {"works_dir": works, "data_dir": tmp_path},
    )()
    app.include_router(stats_router)
    app.include_router(export_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as http:
        http.cookies.set("session", app.state.session_signer.sign("ok"))
        yield http
    await database.dispose()


async def test_stats_endpoint(client):
    response = await client.get("/api/stats")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_illusts"] == 2
    assert payload["total_pages"] == 2
    assert payload["downloaded_pages"] == 1
    assert payload["pending_pages"] == 1
    assert payload["by_type"] == {"ugoira": 1, "illust": 1}
    assert payload["by_restrict"] == {"public": 1, "private": 1}
    assert payload["ugoira_count"] == 1
    assert payload["animation_ready"] == 1
    assert payload["total_bytes"] > 0


async def test_export_metadata_zip(client):
    response = await client.post(
        "/api/export",
        json={"include_metadata": True, "include_originals": False, "pids": [10]},
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    tasks = client._transport.app.state.tasks  # type: ignore[union-attr]
    await tasks.wait(task_id)
    record = tasks.get(task_id)
    assert record is not None
    assert record.status == "completed"

    download = await client.get(f"/api/export/{task_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"


async def test_export_originals_zip(client):
    import io
    import zipfile

    response = await client.post(
        "/api/export",
        json={
            "include_metadata": False,
            "include_originals": True,
            "pids": [10],
            "only_downloaded": True,
        },
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    await client._transport.app.state.tasks.wait(task_id)  # type: ignore[union-attr]

    download = await client.get(f"/api/export/{task_id}/download")
    assert download.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(download.content))
    names = archive.namelist()
    assert any("000_p0.jpg" in name for name in names)


async def test_export_rejects_empty_selection(client):
    response = await client.post(
        "/api/export",
        json={"include_metadata": True, "pids": [999999]},
    )
    assert response.status_code == 422


async def test_export_includes_deleted_works(client):
    import io
    import zipfile

    from pixiv_archive.db.models import Illust

    database = client._transport.app.state.db  # type: ignore[union-attr]
    async with database.session() as session:
        session.add(Illust(pid=30, title="gone", author_id=1, state="deleted"))
        await session.commit()
    async with database.session() as session:
        session.add(Bookmark(pid=30, restrict="public", rank=2048, state="active"))
        await session.commit()

    response = await client.post(
        "/api/export",
        json={"include_metadata": True, "include_originals": False, "pids": [30]},
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    await client._transport.app.state.tasks.wait(task_id)  # type: ignore[union-attr]
    download = await client.get(f"/api/export/{task_id}/download")
    archive = zipfile.ZipFile(io.BytesIO(download.content))
    assert "metadata/30.json" in archive.namelist()


async def test_export_download_404_for_unknown(client):
    response = await client.get("/api/export/nope/download")
    assert response.status_code == 404
