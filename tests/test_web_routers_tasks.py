import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust, IllustPage
from pixiv_archive.web.auth import SessionSigner
from pixiv_archive.web.routers.tasks import router as tasks_router
from pixiv_archive.web.tasks import TaskManager


@pytest.fixture
async def client(tmp_path):
    database = Database(tmp_path / "t.db")
    await database.create_all()
    async with database.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=1, title="t", author_id=1, page_count=1))
        await session.commit()
    async with database.session() as session:
        session.add(IllustPage(pid=1, page_index=0, original_url="https://x/0.jpg", ext=".jpg"))
        await session.commit()
    async with database.session() as session:
        session.add(Bookmark(pid=1, restrict="public", rank=0, state="active"))
        await session.commit()

    app = FastAPI()
    app.state.db = database
    app.state.session_signer = SessionSigner("secret")
    app.state.tasks = TaskManager()
    app.state.events = app.state.tasks.events
    app.state.settings = type("S", (), {})()
    app.include_router(tasks_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as http:
        http.cookies.set("session", app.state.session_signer.sign("ok"))
        yield http
    await database.dispose()


async def test_tasks_empty_initially(client):
    response = await client.get("/api/tasks")
    assert response.status_code == 200
    assert response.json() == []


async def test_sync_endpoint_starts_task(client, monkeypatch):
    import pixiv_archive.web.routers.tasks as tasks_module

    class FakeResult:
        status = "completed"
        new_count = 3
        unbookmarked_count = 0
        rank_rebuilt_count = 0
        pages_fetched = 2
        previews_fetched = 3
        previews_failed = 0
        failed_count = 0

    class FakeService:
        async def run_incremental(self, max_pages=None):
            return FakeResult()

        async def run_full(self, max_pages=None):
            return FakeResult()

        def set_download_previews(self, enabled):
            pass

    @asynccontextmanager
    async def fake_open(settings):
        yield FakeService()

    monkeypatch.setattr(tasks_module, "open_sync_service", fake_open)

    response = await client.post("/api/sync", json={"mode": "incremental"})
    assert response.status_code == 202
    task_id = response.json()["id"]

    for _ in range(100):
        await asyncio.sleep(0.02)
        listing = (await client.get("/api/tasks")).json()
        if listing and listing[0]["status"] != "running":
            break
    listing = (await client.get("/api/tasks")).json()
    assert listing[0]["id"] == task_id
    assert listing[0]["status"] == "completed"
    assert listing[0]["detail"]["new_count"] == 3

    single = (await client.get(f"/api/tasks/{task_id}")).json()
    assert single["id"] == task_id


async def test_download_endpoint_starts_task(client, monkeypatch):
    import pixiv_archive.web.routers.tasks as tasks_module

    class FakeReport:
        status = "completed"
        pages_done = 1
        thumbs_done = 1
        failed = 0
        pages_failed = 0
        ugoira_done = 0
        batch_id = 1

    class FakeWorker:
        def set_thumb_enabled(self, enabled):
            pass

        async def retry_failed(self):
            return 0

        async def run_scope(self, scope):
            return FakeReport()

    @asynccontextmanager
    async def fake_open(settings):
        yield FakeWorker()

    monkeypatch.setattr(tasks_module, "open_download_worker", fake_open)

    response = await client.post(
        "/api/downloads", json={"scope": "all_missing", "pids": [], "with_thumbs": True}
    )
    assert response.status_code == 202
    for _ in range(100):
        await asyncio.sleep(0.02)
        listing = (await client.get("/api/tasks")).json()
        if listing and listing[0]["status"] != "running":
            break
    listing = (await client.get("/api/tasks")).json()
    assert listing[0]["kind"] == "download"
    assert listing[0]["status"] == "completed"


async def test_invalid_scope_rejected(client):
    response = await client.post("/api/downloads", json={"scope": "bogus"})
    assert response.status_code == 422


async def test_duplicate_sync_rejected(client, monkeypatch):
    import pixiv_archive.web.routers.tasks as tasks_module

    release = asyncio.Event()

    class SlowService:
        async def run_incremental(self, max_pages=None):
            await release.wait()
            return type(
                "R",
                (),
                {
                    "status": "completed",
                    "new_count": 0,
                    "unbookmarked_count": 0,
                    "rank_rebuilt_count": 0,
                    "pages_fetched": 0,
                    "previews_fetched": 0,
                    "previews_failed": 0,
                    "failed_count": 0,
                },
            )()

        async def run_full(self, max_pages=None):
            return await self.run_incremental()

        def set_download_previews(self, enabled):
            pass

    @asynccontextmanager
    async def fake_open(settings):
        yield SlowService()

    monkeypatch.setattr(tasks_module, "open_sync_service", fake_open)

    first = await client.post("/api/sync", json={"mode": "incremental"})
    assert first.status_code == 202
    second = await client.post("/api/sync", json={"mode": "incremental"})
    assert second.status_code == 409
    release.set()
    for _ in range(100):
        await asyncio.sleep(0.02)
        listing = (await client.get("/api/tasks")).json()
        if listing and listing[0]["status"] != "running":
            break


async def test_cancel_unknown_task_404(client):
    response = await client.post("/api/tasks/nope/cancel")
    assert response.status_code == 404


async def test_events_endpoint_is_reachable(client):
    """The SSE stream is long-lived and therefore not consumed here.

    Streaming internals are unit-tested in tests/test_web_tasks.py. This test
    verifies the endpoint is registered by inspecting the router's routes.
    """
    bus = client._transport.app.state.events  # type: ignore[union-attr]
    bus.publish("task", {"task_id": "abc", "status": "running"})
    assert bus.recent()[-1]["payload"]["task_id"] == "abc"

    from pixiv_archive.web.routers import tasks as tasks_module

    paths = {getattr(route, "path", None) for route in tasks_module.router.routes}
    assert "/api/events" in paths
