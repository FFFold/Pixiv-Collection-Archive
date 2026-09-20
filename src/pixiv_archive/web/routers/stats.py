from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Bookmark, Illust, IllustPage, UgoiraMeta
from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_session, get_settings
from pixiv_archive.web.schemas import StatsOut

router = APIRouter(prefix="/api", tags=["stats"], dependencies=[Depends(require_auth)])  # noqa: B008


def _sum_sizes(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


@router.get("/stats", response_model=StatsOut)
async def stats(
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> StatsOut:
    settings = get_settings(request)

    total_illusts = (
        await session.execute(
            select(func.count()).select_from(Illust).where(Illust.state == "active")
        )
    ).scalar_one()
    unbookmarked = (
        await session.execute(
            select(func.count()).select_from(Bookmark).where(Bookmark.state == "unbookmarked")
        )
    ).scalar_one()
    page_counts: dict[str, int] = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(
                select(IllustPage.download_state, func.count()).group_by(IllustPage.download_state)
            )
        ).all()
    }
    by_type: dict[str, int] = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(select(Illust.type, func.count()).group_by(Illust.type))
        ).all()
    }
    by_restrict: dict[str, int] = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(
                select(Bookmark.restrict, func.count()).group_by(Bookmark.restrict)
            )
        ).all()
    }
    ugoira_count = (
        await session.execute(select(func.count()).select_from(UgoiraMeta))
    ).scalar_one()

    works_root = settings.works_dir
    thumbs_ready = len(list(works_root.glob("*/thumb.webp"))) if works_root.is_dir() else 0
    animation_ready = len(list(works_root.glob("*/animation.mp4"))) if works_root.is_dir() else 0

    return StatsOut(
        total_illusts=total_illusts,
        unbookmarked=unbookmarked,
        total_pages=sum(page_counts.values()),
        downloaded_pages=page_counts.get("done", 0),
        failed_pages=page_counts.get("failed", 0),
        pending_pages=page_counts.get("pending", 0),
        total_bytes=_sum_sizes(works_root),
        thumbs_ready=thumbs_ready,
        ugoira_count=ugoira_count,
        animation_ready=animation_ready,
        by_type=by_type,
        by_restrict=by_restrict,
    )
