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


async def _client(app):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _cm():
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://t") as client:
                yield client

    return _cm()


async def test_health_is_public(settings):
    app = create_app(settings)
    async with await _client(app) as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_api_routes_require_auth(settings):
    app = create_app(settings)
    async with await _client(app) as client:
        for path in ("/api/gallery", "/api/stats", "/api/tasks", "/api/authors"):
            assert (await client.get(path)).status_code == 401, path


async def test_login_then_access(settings):
    app = create_app(settings)
    async with await _client(app) as client:
        login = await client.post("/api/auth/login", json={"token": "sesame"})
        assert login.status_code == 200
        assert (await client.get("/api/gallery")).status_code == 200
        assert (await client.get("/api/stats")).status_code == 200
        assert (await client.get("/api/tasks")).status_code == 200


async def test_openapi_is_public(settings):
    app = create_app(settings)
    async with await _client(app) as client:
        assert (await client.get("/openapi.json")).status_code == 200


async def test_unknown_api_route_returns_404_json(settings):
    app = create_app(settings)
    async with await _client(app) as client:
        response = await client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"] == "not found"


async def test_lifespan_starts_and_stops_scheduler(settings):
    app = create_app(settings)
    async with await _client(app) as client:
        await client.get("/api/health")
        scheduler = app.state.scheduler
        assert scheduler is not None
        jobs = {job.id for job in scheduler.get_jobs()}
        assert "sync-incremental" in jobs


async def test_scheduled_sync_registers_task_and_skips_while_busy(settings, monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager

    import pixiv_archive.sync.factory as sync_factory
    from pixiv_archive.sync.orchestrator import SyncResult
    from pixiv_archive.web.app import _make_incremental_job

    release = asyncio.Event()

    class FakeService:
        async def run_incremental(self):
            await release.wait()
            return SyncResult(run_id=1, kind="incremental")

        async def run_full(self):
            return await self.run_incremental()

    @asynccontextmanager
    async def fake_open(_settings):
        yield FakeService()

    monkeypatch.setattr(sync_factory, "open_sync_service", fake_open)

    app = create_app(settings)
    tasks = app.state.tasks
    job = _make_incremental_job(app)

    await asyncio.wait_for(job(), timeout=1)
    active = tasks.list_active()
    assert [record.kind for record in active] == ["sync"]

    await asyncio.wait_for(job(), timeout=1)
    assert len(tasks.list_active()) == 1

    sync_id = active[0].id
    release.set()
    await tasks.wait(sync_id)
    assert tasks.list_active() == []

    maint_release = asyncio.Event()

    async def maint(_context):
        await maint_release.wait()
        return {}

    maint_id = tasks.start("maintenance", maint)
    await asyncio.wait_for(job(), timeout=1)
    assert [record.kind for record in tasks.list_active()] == ["maintenance"]
    maint_release.set()
    await tasks.wait(maint_id)
