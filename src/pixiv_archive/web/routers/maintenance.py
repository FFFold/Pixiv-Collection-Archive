from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.maintenance.service import (
    db_check,
    preview_repair_download_state,
    rebuild_storage_stats,
    repair_download_state,
)
from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_session, get_settings, get_tasks
from pixiv_archive.web.schemas import MaintenanceResultOut, TaskOut
from pixiv_archive.web.tasks import TaskContext, TaskManager

router = APIRouter(
    prefix="/api/maintenance",
    tags=["maintenance"],
    dependencies=[Depends(require_auth)],  # noqa: B008
)


def _works_dir(request: Request) -> Path:
    return get_settings(request).works_dir


@router.post("/rebuild-stats", status_code=status.HTTP_202_ACCEPTED, response_model=TaskOut)
async def start_rebuild_stats(
    request: Request,
    tasks: Annotated[TaskManager, Depends(get_tasks)],  # noqa: B008
) -> TaskOut:
    works = _works_dir(request)
    database = request.app.state.db

    async def run(context: TaskContext) -> dict[str, Any]:
        async with database.session() as session:
            context.progress("rebuild", 0, 1, "重建存储统计")
            result = await rebuild_storage_stats(session, works)
            context.progress("rebuild", 1, 1, "完成")
            return dict(result)

    try:
        task_id = tasks.start("maintenance", run)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record = tasks.get(task_id)
    assert record is not None
    return TaskOut(**record.to_dict())


@router.get("/repair-download-state/preview")
async def repair_preview(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],  # noqa: B008
) -> dict[str, int]:
    return await preview_repair_download_state(session, _works_dir(request))


@router.post("/repair-download-state", status_code=status.HTTP_202_ACCEPTED, response_model=TaskOut)
async def start_repair(
    request: Request,
    tasks: Annotated[TaskManager, Depends(get_tasks)],  # noqa: B008
) -> TaskOut:
    works = _works_dir(request)
    database = request.app.state.db

    async def run(context: TaskContext) -> dict[str, Any]:
        async with database.session() as session:
            context.progress("repair", 0, 1, "修复下载状态")
            result = await repair_download_state(session, works)
            context.progress("repair", 1, 1, "完成")
            return dict(result)

    try:
        task_id = tasks.start("maintenance", run)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record = tasks.get(task_id)
    assert record is not None
    return TaskOut(**record.to_dict())


@router.post("/db-check", response_model=MaintenanceResultOut)
async def run_db_check(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],  # noqa: B008
) -> MaintenanceResultOut:
    report = await db_check(session, _works_dir(request))
    return MaintenanceResultOut(**report)
