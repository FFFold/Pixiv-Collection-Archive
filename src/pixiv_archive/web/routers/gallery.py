from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_session
from pixiv_archive.web.gallery_query import GalleryFilters, query_gallery
from pixiv_archive.web.schemas import GalleryResponse

router = APIRouter(
    prefix="/api",
    tags=["gallery"],
    dependencies=[Depends(require_auth)],  # noqa: B008
)


@router.get("/gallery", response_model=GalleryResponse)
async def gallery(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=200),
    sort: str = Query(default="rank", pattern="^(rank|create_date|bookmarks|views)$"),
    author_id: int | None = None,
    tag: str | None = None,
    q: str | None = None,
    type: str | None = Query(default=None, pattern="^(illust|ugoira)$"),
    x_restrict: int | None = Query(default=None, ge=0, le=2),
    downloaded: bool | None = None,
    restrict: str | None = Query(default=None, pattern="^(public|private)$"),
    only_unbookmarked: bool = False,
    include_unbookmarked: bool = False,
    only_deleted: bool = False,
    include_deleted: bool = False,
    rank_start: int | None = Query(default=None, ge=0),
    rank_count: int | None = Query(default=None, ge=1),
) -> GalleryResponse:
    filters = GalleryFilters(
        sort=sort,
        author_id=author_id,
        tag=tag,
        q=q,
        type=type,
        x_restrict=x_restrict,
        downloaded=downloaded,
        restrict=restrict,
        only_unbookmarked=only_unbookmarked,
        include_unbookmarked=include_unbookmarked,
        only_deleted=only_deleted,
        include_deleted=include_deleted,
        rank_start=rank_start,
        rank_count=rank_count,
    )
    return await query_gallery(session, filters, offset=offset, limit=limit)
