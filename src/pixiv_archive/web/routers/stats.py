from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Author, Bookmark, Illust, IllustPage, UgoiraMeta
from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_session
from pixiv_archive.web.schemas import StatsOut

router = APIRouter(prefix="/api", tags=["stats"], dependencies=[Depends(require_auth)])  # noqa: B008


@router.get("/stats", response_model=StatsOut)
async def stats(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> StatsOut:
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
    total_bytes = (
        await session.execute(select(func.coalesce(func.sum(Illust.byte_size), 0)))
    ).scalar_one()
    thumbs_ready = (
        await session.execute(select(func.count()).where(Illust.thumb_ready.is_(True)))
    ).scalar_one()
    animation_ready = (
        await session.execute(select(func.count()).where(Illust.animation_ready.is_(True)))
    ).scalar_one()

    by_type_bytes = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(
                select(Illust.type, func.coalesce(func.sum(Illust.byte_size), 0)).group_by(
                    Illust.type
                )
            )
        ).all()
    }
    by_restrict_bytes = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(
                select(Bookmark.restrict, func.coalesce(func.sum(Illust.byte_size), 0))
                .join(Illust, Illust.pid == Bookmark.pid)
                .group_by(Bookmark.restrict)
            )
        ).all()
    }
    top_authors_bytes = [
        {
            "id": int(row[0]),
            "name": str(row[1]),
            "bytes": int(row[2]),
            "illust_count": int(row[3]),
        }
        for row in (
            await session.execute(
                select(
                    Author.id,
                    Author.name,
                    func.coalesce(func.sum(Illust.byte_size), 0).label("bytes"),
                    func.count(Illust.pid),
                )
                .join(Illust, Illust.author_id == Author.id)
                .group_by(Author.id)
                .order_by(func.coalesce(func.sum(Illust.byte_size), 0).desc())
                .limit(10)
            )
        ).all()
    ]
    stale = (
        await session.execute(
            select(func.count())
            .select_from(Illust)
            .where(Illust.has_original.is_(True), Illust.byte_size == 0)
        )
    ).scalar_one()

    return StatsOut(
        total_illusts=total_illusts,
        unbookmarked=unbookmarked,
        total_pages=sum(page_counts.values()),
        downloaded_pages=page_counts.get("done", 0),
        failed_pages=page_counts.get("failed", 0),
        pending_pages=page_counts.get("pending", 0),
        total_bytes=int(total_bytes),
        thumbs_ready=int(thumbs_ready),
        ugoira_count=ugoira_count,
        animation_ready=int(animation_ready),
        by_type=by_type,
        by_restrict=by_restrict,
        by_type_bytes=by_type_bytes,
        by_restrict_bytes=by_restrict_bytes,
        top_authors_bytes=top_authors_bytes,
        stats_stale=bool(stale),
    )
