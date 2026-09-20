from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from pixiv_archive.download.scope import DownloadScope
from pixiv_archive.sync.factory import open_download_worker, open_sync_service
from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_events, get_tasks
from pixiv_archive.web.schemas import DownloadRequest, SyncRequest, TaskOut
from pixiv_archive.web.sse import EventBus, event_stream
from pixiv_archive.web.tasks import TaskContext, TaskManager

router = APIRouter(
    prefix="/api",
    tags=["tasks"],
    dependencies=[Depends(require_auth)],  # noqa: B008
)

_SCOPE_ALIASES = {
    "all-missing": "all_missing",
    "all_missing": "all_missing",
    "author": "author",
    "selected": "selected",
    "rank-range": "rank_range",
    "rank_range": "rank_range",
    "filter": "filter",
}


def _scope_from_request(payload: DownloadRequest) -> DownloadScope:
    kind = _SCOPE_ALIASES.get(payload.scope)
    if kind is None:
        raise HTTPException(status_code=422, detail=f"unknown scope {payload.scope}")
    return DownloadScope(
        kind=kind,
        pids=payload.pids,
        author_id=payload.author_id,
        start=payload.start,
        count=payload.count,
        x_restrict=payload.x_restrict,
        type=payload.type,
    )


def _task_out(tasks: TaskManager, task_id: str) -> TaskOut:
    record = tasks.get(task_id)
    assert record is not None
    return TaskOut(**record.to_dict())


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED, response_model=TaskOut)
async def start_sync(
    payload: SyncRequest,
    request: Request,
    tasks: TaskManager = Depends(get_tasks),  # noqa: B008
) -> TaskOut:
    settings = request.app.state.settings
    if payload.mode not in ("incremental", "full"):
        raise HTTPException(status_code=422, detail="mode must be incremental or full")

    async def run(context: TaskContext) -> dict[str, Any]:
        async with open_sync_service(settings) as service:
            service._on_progress = context.progress
            if payload.mode == "full":
                result = await service.run_full()
            else:
                result = await service.run_incremental()
            return {
                "status": result.status,
                "new_count": result.new_count,
                "unbookmarked_count": result.unbookmarked_count,
                "deleted_count": result.deleted_count,
                "rank_rebuilt_count": result.rank_rebuilt_count,
                "pages_fetched": result.pages_fetched,
                "previews_fetched": result.previews_fetched,
                "previews_failed": result.previews_failed,
                "failed_count": result.failed_count,
            }

    try:
        task_id = tasks.start("sync", run)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _task_out(tasks, task_id)


@router.post("/downloads", status_code=status.HTTP_202_ACCEPTED, response_model=TaskOut)
async def start_download(
    payload: DownloadRequest,
    request: Request,
    tasks: TaskManager = Depends(get_tasks),  # noqa: B008
) -> TaskOut:
    settings = request.app.state.settings
    scope = _scope_from_request(payload)

    async def run(context: TaskContext) -> dict[str, Any]:
        async with open_download_worker(settings) as worker:
            if not payload.with_thumbs:
                worker.set_thumb_enabled(False)
            report = await worker.run_scope(scope)
            return {
                "status": report.status,
                "pages_done": report.pages_done,
                "pages_failed": report.pages_failed,
                "thumbs_done": report.thumbs_done,
                "ugoira_done": report.ugoira_done,
                "failed": report.failed,
                "batch_id": report.batch_id,
            }

    try:
        task_id = tasks.start("download", run)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _task_out(tasks, task_id)


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(tasks: TaskManager = Depends(get_tasks)) -> list[TaskOut]:  # noqa: B008
    return [TaskOut(**record.to_dict()) for record in tasks.all()]


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: str,
    tasks: TaskManager = Depends(get_tasks),  # noqa: B008
) -> TaskOut:
    record = tasks.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskOut(**record.to_dict())


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: str,
    tasks: TaskManager = Depends(get_tasks),  # noqa: B008
) -> TaskOut:
    record = tasks.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="task not found")
    if not tasks.cancel(task_id):
        raise HTTPException(status_code=409, detail="task is not running")
    return TaskOut(**record.to_dict())


@router.get("/events")
async def events(
    bus: EventBus = Depends(get_events),  # noqa: B008
) -> StreamingResponse:
    queue = bus.subscribe(replay=True)
    return StreamingResponse(event_stream(bus, queue), media_type="text/event-stream")
