import json
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Author, Bookmark, Illust, IllustPage
from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_session, get_settings, get_tasks
from pixiv_archive.web.schemas import ExportOut, ExportRequest
from pixiv_archive.web.tasks import TaskContext, TaskManager

router = APIRouter(
    prefix="/api",
    tags=["export"],
    dependencies=[Depends(require_auth)],  # noqa: B008
)

_EXPORT_DIR_NAME = "exports"


def _export_dir(settings: Any) -> Path:
    data_dir: Path = settings.data_dir
    target = data_dir / _EXPORT_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


async def _selected_pids(session: AsyncSession, payload: ExportRequest) -> list[int]:
    if payload.pids:
        stmt = select(Illust.pid).join(Bookmark, Bookmark.pid == Illust.pid).order_by(Bookmark.rank)
        stmt = stmt.where(Illust.pid.in_(payload.pids))
        if payload.x_restrict is not None:
            stmt = stmt.where(Illust.x_restrict == payload.x_restrict)
        if payload.only_downloaded:
            stmt = stmt.where(Illust.has_original.is_(True))
        return list((await session.execute(stmt)).scalars().all())

    if payload.use_filter:
        from pixiv_archive.db.query import IllustFilters, build_filtered_pids

        filters = IllustFilters(
            tags=payload.tags,
            author_ids=payload.author_ids,
            q=payload.q,
            type=payload.type,
            x_restrict=payload.x_restrict,
            downloaded=payload.downloaded,
            restrict=payload.restrict,
            only_unbookmarked=payload.only_unbookmarked,
            include_unbookmarked=payload.include_unbookmarked,
            only_deleted=payload.only_deleted,
            include_deleted=payload.include_deleted,
            page_min=payload.page_min,
            page_max=payload.page_max,
            bookmarks_min=payload.bookmarks_min,
            bookmarks_max=payload.bookmarks_max,
            views_min=payload.views_min,
            views_max=payload.views_max,
        )
        if payload.only_downloaded and filters.downloaded is None:
            filters.downloaded = True
        return list((await session.execute(build_filtered_pids(filters))).scalars().all())

    stmt = select(Illust.pid).join(Bookmark, Bookmark.pid == Illust.pid).order_by(Bookmark.rank)
    if payload.x_restrict is not None:
        stmt = stmt.where(Illust.x_restrict == payload.x_restrict)
    if payload.only_downloaded:
        stmt = stmt.where(Illust.has_original.is_(True))
    return list((await session.execute(stmt)).scalars().all())


def _metadata_payload(illust: Illust, author: Author | None, tags: list[str]) -> dict[str, Any]:
    return {
        "id": illust.pid,
        "title": illust.title,
        "description": illust.description,
        "type": illust.type,
        "page_count": illust.page_count,
        "width": illust.width,
        "height": illust.height,
        "x_restrict": illust.x_restrict,
        "create_date": illust.create_date.isoformat() if illust.create_date else None,
        "author": (
            {"id": author.id, "name": author.name, "account": author.account} if author else None
        ),
        "tags": tags,
        "pixiv_url": f"https://www.pixiv.net/artworks/{illust.pid}",
    }


@router.post("/export", status_code=status.HTTP_202_ACCEPTED, response_model=ExportOut)
async def start_export(
    payload: ExportRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    tasks: TaskManager = Depends(get_tasks),  # noqa: B008
) -> ExportOut:
    settings = get_settings(request)
    pids = await _selected_pids(session, payload)
    if not pids:
        raise HTTPException(status_code=422, detail="no illusts match the export filter")

    filename = f"export-{len(pids)}-items.zip"
    destination = _export_dir(settings) / filename
    database = request.app.state.db

    async def run(context: TaskContext) -> dict[str, Any]:
        written = 0
        if destination.exists():
            destination.unlink()
        async with database.session() as export_session:
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for index, pid in enumerate(pids, start=1):
                    context.progress("export", index, len(pids), f"导出 {pid}")
                    illust = await export_session.get(Illust, pid)
                    if illust is None:
                        continue
                    author = await export_session.get(Author, illust.author_id)
                    metadata_prefix = (
                        f"{illust.author_id}/" if payload.group_by_author else "metadata/"
                    )
                    original_prefix = f"{illust.author_id}/" if payload.group_by_author else ""
                    if payload.include_metadata:
                        archive.writestr(
                            f"{metadata_prefix}{pid}.json",
                            json.dumps(
                                _metadata_payload(illust, author, []),
                                ensure_ascii=False,
                                indent=2,
                            ),
                        )
                    if payload.include_originals:
                        page_rows = (
                            (
                                await export_session.execute(
                                    select(IllustPage)
                                    .where(IllustPage.pid == pid)
                                    .order_by(IllustPage.page_index)
                                )
                            )
                            .scalars()
                            .all()
                        )
                        work_dir = settings.works_dir / str(pid)
                        for page in page_rows:
                            relative = f"{page.page_index:03d}_p{page.page_index}{page.ext}"
                            source = work_dir / "original" / relative
                            if source.is_file():
                                target = f"{original_prefix}{pid:012d}/original/{relative}"
                                archive.write(source, target)
                                written += 1
        return {"filename": filename, "pids": len(pids), "files": written}

    try:
        task_id = tasks.start("export", run)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ExportOut(task_id=task_id, filename=filename)


@router.get("/export/{task_id}/download")
async def download_export(
    task_id: str,
    request: Request,
    tasks: TaskManager = Depends(get_tasks),  # noqa: B008
) -> FileResponse:
    settings = get_settings(request)
    record = tasks.get(task_id)
    if record is None or record.kind != "export":
        raise HTTPException(status_code=404, detail="export task not found")
    filename = record.detail.get("filename")
    if not filename:
        raise HTTPException(status_code=409, detail="export is not finished")
    path = _export_dir(settings) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="export archive not found")
    return FileResponse(path, media_type="application/zip", filename=filename)
