from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.query import IllustFilters, build_illust_query, sort_order
from pixiv_archive.web.schemas import GalleryItem, GalleryResponse


async def query_gallery(
    session: AsyncSession, filters: IllustFilters, *, offset: int, limit: int
) -> GalleryResponse:
    """Run the filtered/sorted query and compute absolute display indexes.

    Display indexes are 1-based positions within the *whole* filtered set, so
    they stay stable while paginating. A window function computes them in the
    database, avoiding a second full scan.
    """
    base = build_illust_query(filters)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    order = sort_order(filters)
    indexed = base.order_by(*order).add_columns(
        func.row_number().over(order_by=order).label("display_index")
    )
    rows = (await session.execute(indexed.offset(offset).limit(limit))).all()

    items = [
        GalleryItem(
            pid=illust.pid,
            index=int(display_index),
            title=illust.title,
            author_id=author.id,
            author_name=author.name,
            page_count=illust.page_count,
            type=illust.type,
            x_restrict=illust.x_restrict,
            width=illust.width,
            height=illust.height,
            create_date=illust.create_date,
            rank=bookmark.rank,
            has_original=illust.has_original,
            page_downloaded_count=illust.page_downloaded_count,
            preview_url=f"/api/illust/{illust.pid}/thumb",
            thumb_url=f"/api/illust/{illust.pid}/thumb",
            restrict=bookmark.restrict,
            unbookmarked=bookmark.state == "unbookmarked",
            state=illust.state,
        )
        for illust, bookmark, author, display_index in rows
    ]
    return GalleryResponse(items=items, total=total, offset=offset, limit=limit)
