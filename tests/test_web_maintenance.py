import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust, IllustPage
from pixiv_archive.web.auth import SessionSigner
from pixiv_archive.web.routers.maintenance import router as maintenance_router
from pixiv_archive.web.routers.tasks import router as tasks_router
from pixiv_archive.web.tasks import TaskManager


@pytest.fixture
async def client(tmp_path):
    database = Database(tmp_path / "mt.db")
    await database.create_all()
    works = tmp_path / "works"
    original = works / "1" / "original"
    original.mkdir(parents=True)
    (original / "000_p0.jpg").write_bytes(b"a" * 10)
    (works / "1" / "thumb.webp").write_bytes(b"t" * 5)

    async with database.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=1, title="t", author_id=1, page_count=1))
        await session.commit()
    async with database.session() as session:
        session.add(
            IllustPage(pid=1, page_index=0, original_url="x", ext=".jpg", download_state="done")
        )
        session.add(Bookmark(pid=1, restrict="public", rank=0, state="active"))
        await session.commit()

    app = FastAPI()
    app.state.db = database
    app.state.session_signer = SessionSigner("secret")
    app.state.tasks = TaskManager()
    app.state.events = app.state.tasks.events
    app.state.settings = type("S", (), {"works_dir": works, "data_dir": tmp_path})()
    app.include_router(maintenance_router)
    app.include_router(tasks_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as http:
        http.cookies.set("session", app.state.session_signer.sign("ok"))
        yield http
    await database.dispose()


async def _wait(client) -> dict:
    for _ in range(100):
        await asyncio.sleep(0.02)
        listing = (await client.get("/api/tasks")).json()
        if listing and listing[0]["status"] != "running":
            return listing[0]
    raise AssertionError("task did not finish")


async def test_rebuild_stats_task_updates_columns(client):
    response = await client.post("/api/maintenance/rebuild-stats")
    assert response.status_code == 202
    record = await _wait(client)
    assert record["kind"] == "maintenance"
    assert record["status"] == "completed"
    assert record["detail"]["works"] == 1

    from sqlalchemy import select

    from pixiv_archive.db.models import Illust

    database = client._transport.app.state.db  # type: ignore[union-attr]
    async with database.session() as session:
        illust = (await session.execute(select(Illust))).scalar_one()
    assert illust.byte_size == 15
    assert illust.thumb_ready is True


async def test_repair_preview_and_run(client):
    preview = await client.get("/api/maintenance/repair-download-state/preview")
    assert preview.status_code == 200
    assert preview.json()["works_to_fix"] == 0

    response = await client.post("/api/maintenance/repair-download-state")
    assert response.status_code == 202
    record = await _wait(client)
    assert record["status"] == "completed"


async def test_db_check_returns_report(client):
    response = await client.post("/api/maintenance/db-check")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["issues"] == []
