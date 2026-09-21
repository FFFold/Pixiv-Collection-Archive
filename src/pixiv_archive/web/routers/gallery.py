from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.query import IllustFilters
from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_session
from pixiv_archive.web.gallery_query import query_gallery
from pixiv_archive.web.schemas import GalleryResponse

router = APIRouter(
    prefix="/api",
    tags=["gallery"],
    dependencies=[Depends(require_auth)],  # noqa: B008
)


@router.get("/gallery", response_model=GalleryResponse)
async def gallery(
    session: Annotated[AsyncSession, Depends(get_session)],  # noqa: B008
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 60,
    sort: Annotated[str, Query(pattern="^(rank|create_date|bookmarks|views)$")] = "rank",
    author_id: Annotated[list[int] | None, Query()] = None,
    tag: Annotated[list[str] | None, Query()] = None,
    q: str | None = None,
    type: Annotated[str | None, Query(pattern="^(illust|ugoira)$")] = None,
    x_restrict: Annotated[int | None, Query(ge=0, le=2)] = None,
    downloaded: bool | None = None,
    restrict: Annotated[str | None, Query(pattern="^(public|private)$")] = None,
    only_unbookmarked: bool = False,
    include_unbookmarked: bool = False,
    only_deleted: bool = False,
    include_deleted: bool = False,
    page_min: Annotated[int | None, Query(ge=1)] = None,
    page_max: Annotated[int | None, Query(ge=1)] = None,
    bookmarks_min: Annotated[int | None, Query(ge=0)] = None,
    bookmarks_max: Annotated[int | None, Query(ge=0)] = None,
    views_min: Annotated[int | None, Query(ge=0)] = None,
    views_max: Annotated[int | None, Query(ge=0)] = None,
    rank_start: Annotated[int | None, Query(ge=0)] = None,
    rank_count: Annotated[int | None, Query(ge=1)] = None,
) -> GalleryResponse:
    filters = IllustFilters(
        sort=sort,
        tags=tag or [],
        author_ids=author_id or [],
        q=q,
        type=type,
        x_restrict=x_restrict,
        downloaded=downloaded,
        restrict=restrict,
        only_unbookmarked=only_unbookmarked,
        include_unbookmarked=include_unbookmarked,
        only_deleted=only_deleted,
        include_deleted=include_deleted,
        page_min=page_min,
        page_max=page_max,
        bookmarks_min=bookmarks_min,
        bookmarks_max=bookmarks_max,
        views_min=views_min,
        views_max=views_max,
        rank_start=rank_start,
        rank_count=rank_count,
    )
    return await query_gallery(session, filters, offset=offset, limit=limit)
