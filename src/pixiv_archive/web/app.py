from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pixiv_archive import __version__
from pixiv_archive.config import Settings
from pixiv_archive.db.engine import Database
from pixiv_archive.sync.factory import _ensure_schema
from pixiv_archive.sync.scheduler import create_scheduler
from pixiv_archive.web.auth import SessionSigner
from pixiv_archive.web.routers import auth, export, gallery, illust, stats, tasks
from pixiv_archive.web.sse import EventBus
from pixiv_archive.web.tasks import TaskManager


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings(_env_file=None)
    settings.ensure_dirs()

    database = Database(settings.db_path)
    events = EventBus()
    task_manager = TaskManager(events)
    signer = SessionSigner(settings.session_secret)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await _ensure_schema(settings)
        scheduler = create_scheduler(
            _make_incremental_job(app),
            interval=settings.sync_interval,
            full_cron=settings.sync_full_cron,
            full_job=_make_full_job(app),
        )
        app.state.scheduler = scheduler
        scheduler.start()
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
            await database.dispose()

    app = FastAPI(title="Pixiv Archive", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = database
    app.state.events = events
    app.state.tasks = task_manager
    app.state.session_signer = signer

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(auth.protected)
    app.include_router(gallery.router)
    app.include_router(illust.router)
    app.include_router(tasks.router)
    app.include_router(stats.router)
    app.include_router(export.router)

    _mount_spa(app)

    @app.exception_handler(404)
    async def _not_found(_request, _exc) -> JSONResponse:  # type: ignore[no-untyped-def]
        return JSONResponse(status_code=404, content={"detail": "not found"})

    return app


def _mount_spa(app: FastAPI) -> None:
    from pathlib import Path

    static_dir = Path(__file__).parent / "static"
    if not static_dir.is_dir():
        return
    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_shell(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(static_dir / "index.html")


def _make_incremental_job(app: FastAPI) -> Callable[[], Awaitable[None]]:
    async def job() -> None:
        from pixiv_archive.sync.factory import open_sync_service

        if any(record.kind == "sync" for record in app.state.tasks.list_active()):
            return
        async with open_sync_service(app.state.settings) as service:
            await service.run_incremental()

    return job


def _make_full_job(app: FastAPI) -> Callable[[], Awaitable[None]]:
    async def job() -> None:
        from pixiv_archive.sync.factory import open_sync_service

        if any(record.kind == "sync" for record in app.state.tasks.list_active()):
            return
        async with open_sync_service(app.state.settings) as service:
            await service.run_full()

    return job
