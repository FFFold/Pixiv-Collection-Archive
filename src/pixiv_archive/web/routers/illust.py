from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import (
    Author,
    Bookmark,
    Illust,
    IllustPage,
    IllustTag,
    Tag,
    UgoiraMeta,
)
from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_session, get_settings
from pixiv_archive.web.files import file_response, placeholder_response, resolve_thumb
from pixiv_archive.web.schemas import IllustDetailOut, IllustPageOut

router = APIRouter(
    prefix="/api/illust",
    tags=["illust"],
    dependencies=[Depends(require_auth)],  # noqa: B008
)


async def _display_index(session: AsyncSession, pid: int) -> int:
    rank = (
        await session.execute(select(Bookmark.rank).where(Bookmark.pid == pid))
    ).scalar_one_or_none()
    if rank is None:
        return 0
    return (
        await session.execute(
            select(func.count())
            .select_from(Bookmark)
            .where(Bookmark.state == "active", Bookmark.rank < rank)
        )
    ).scalar_one() + 1


@router.get("/{pid}", response_model=IllustDetailOut)
async def illust_detail(
    pid: int,
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> IllustDetailOut:
    settings = get_settings(request)
    row = (
        await session.execute(
            select(Illust, Author, Bookmark)
            .join(Author, Author.id == Illust.author_id)
            .outerjoin(Bookmark, Bookmark.pid == Illust.pid)
            .where(Illust.pid == pid)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="illust not found")
    illust, author, bookmark = row

    tag_rows = (
        await session.execute(
            select(Tag.name, Tag.translated_name)
            .join(IllustTag, IllustTag.tag_id == Tag.id)
            .where(IllustTag.pid == pid)
            .order_by(IllustTag.position)
        )
    ).all()
    pages = (
        (
            await session.execute(
                select(IllustPage).where(IllustPage.pid == pid).order_by(IllustPage.page_index)
            )
        )
        .scalars()
        .all()
    )
    ugoira = await session.get(UgoiraMeta, pid)
    animation_path = settings.works_dir / str(pid) / "animation.mp4"

    return IllustDetailOut(
        pid=illust.pid,
        index=await _display_index(session, pid),
        title=illust.title,
        description=illust.description,
        author_id=author.id,
        author_name=author.name,
        author_account=author.account,
        page_count=illust.page_count,
        type=illust.type,
        x_restrict=illust.x_restrict,
        sanity_level=illust.sanity_level,
        width=illust.width,
        height=illust.height,
        create_date=illust.create_date,
        total_view=illust.total_view,
        total_bookmarks=illust.total_bookmarks,
        state=illust.state,
        has_original=illust.has_original,
        page_downloaded_count=illust.page_downloaded_count,
        tags=[name for name, _ in tag_rows],
        translated_tags=[t for _, t in tag_rows if t],
        pages=[
            IllustPageOut(
                page_index=page.page_index,
                download_state=page.download_state,
                ext=page.ext,
            )
            for page in pages
        ],
        restrict=bookmark.restrict if bookmark else "public",
        bookmark_state=bookmark.state if bookmark else "unbookmarked",
        rank=bookmark.rank if bookmark else None,
        pixiv_url=f"https://www.pixiv.net/artworks/{illust.pid}",
        animation_available=animation_path.is_file(),
        frame_count=ugoira.frame_count if ugoira else None,
        unbookmarked=(bookmark.state == "unbookmarked") if bookmark else True,
    )


@router.get("/{pid}/file/{page_index}")
async def illust_file(
    pid: int,
    page_index: int,
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Response:
    settings = get_settings(request)
    page = (
        await session.execute(
            select(IllustPage).where(IllustPage.pid == pid, IllustPage.page_index == page_index)
        )
    ).scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    target = (
        settings.works_dir / str(pid) / "original" / f"{page_index:03d}_p{page_index}{page.ext}"
    )
    if not target.is_file():
        raise HTTPException(status_code=404, detail="original not downloaded")
    filename = f"{pid}_p{page_index}{page.ext}"
    return file_response(request, target, download_name=filename)


@router.get("/{pid}/thumb")
async def illust_thumb(pid: int, request: Request) -> Response:
    settings = get_settings(request)
    thumb = resolve_thumb(settings.works_dir, pid)
    if thumb is None:
        return placeholder_response(pid)
    return file_response(request, thumb)


@router.get("/{pid}/animation")
async def illust_animation(pid: int, request: Request) -> Response:
    settings = get_settings(request)
    animation = settings.works_dir / str(pid) / "animation.mp4"
    if not animation.is_file():
        raise HTTPException(status_code=404, detail="animation not available")
    return file_response(request, animation)


@router.get("/{pid}/ugoira.zip")
async def illust_ugoira_zip(pid: int, request: Request) -> Response:
    settings = get_settings(request)
    archive = settings.works_dir / str(pid) / "source.zip"
    if not archive.is_file():
        raise HTTPException(status_code=404, detail="ugoira archive not available")
    return file_response(request, archive, download_name=f"{pid}_ugoira.zip")
