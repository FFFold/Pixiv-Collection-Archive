import os
from urllib.parse import urlsplit

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import (
    Author,
    Illust,
    IllustPage,
    IllustTag,
    Tag,
    UgoiraMeta,
    utcnow,
)
from pixiv_archive.pixiv.models import Illust as PixivIllust

_DEFAULT_EXT = ".jpg"


def url_ext(url: str) -> str:
    ext = os.path.splitext(urlsplit(url).path)[1].lower()
    return ext or _DEFAULT_EXT


async def upsert_illust(
    session: AsyncSession, illust: PixivIllust, *, meta_json: str | None
) -> None:
    """Insert or refresh one illust with its author, tags and pages.

    Existing rows keep their ``page.download_state``/``attempts``; only
    metadata columns are refreshed.
    """
    await _upsert_author(session, illust)
    values = {
        "pid": illust.pid,
        "title": illust.title,
        "description": illust.description,
        "author_id": illust.user.id,
        "create_date": illust.create_date.replace(tzinfo=None) if illust.create_date else None,
        "page_count": illust.page_count,
        "width": illust.width,
        "height": illust.height,
        "type": illust.type,
        "x_restrict": illust.x_restrict,
        "sanity_level": illust.sanity_level,
        "illust_ai_type": illust.illust_ai_type,
        "total_view": illust.total_view,
        "total_bookmarks": illust.total_bookmarks,
        "state": "active",
        "meta_json": meta_json,
        "updated_at": utcnow(),
    }
    stmt = insert(Illust).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Illust.pid],
        set_={key: value for key, value in values.items() if key != "pid"},
    )
    await session.execute(stmt)
    await _replace_tags(session, illust)
    await _upsert_pages(session, illust)


async def _upsert_author(session: AsyncSession, illust: PixivIllust) -> None:
    stmt = insert(Author).values(
        id=illust.user.id, name=illust.user.name, account=illust.user.account
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Author.id],
        set_={"name": illust.user.name, "account": illust.user.account},
    )
    await session.execute(stmt)


async def _replace_tags(session: AsyncSession, illust: PixivIllust) -> None:
    await session.execute(delete(IllustTag).where(IllustTag.pid == illust.pid))
    for position, tag in enumerate(illust.tags):
        if not tag.name:
            continue
        tag_id = await _ensure_tag(session, tag.name, tag.translated_name)
        link = insert(IllustTag).values(pid=illust.pid, tag_id=tag_id, position=position)
        link = link.on_conflict_do_nothing(index_elements=[IllustTag.pid, IllustTag.tag_id])
        await session.execute(link)


async def _ensure_tag(session: AsyncSession, name: str, translated_name: str | None) -> int:
    existing = (await session.execute(select(Tag.id).where(Tag.name == name))).scalar_one_or_none()
    if existing is not None:
        if translated_name:
            await session.execute(
                update(Tag).where(Tag.id == existing).values(translated_name=translated_name)
            )
        return existing
    tag = Tag(name=name, translated_name=translated_name)
    session.add(tag)
    await session.flush()
    return tag.id


async def _upsert_pages(session: AsyncSession, illust: PixivIllust) -> None:
    for index, url in enumerate(illust.original_urls):
        ext = url_ext(url)
        stmt = insert(IllustPage).values(
            pid=illust.pid, page_index=index, original_url=url, ext=ext
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[IllustPage.pid, IllustPage.page_index],
            set_={"original_url": url, "ext": ext},
        )
        await session.execute(stmt)


async def upsert_ugoira_meta(
    session: AsyncSession,
    *,
    pid: int,
    zip_url: str,
    frames_json: str,
    frame_count: int,
) -> None:
    stmt = insert(UgoiraMeta).values(
        pid=pid, zip_url=zip_url, frames_json=frames_json, frame_count=frame_count
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[UgoiraMeta.pid],
        set_={"zip_url": zip_url, "frames_json": frames_json, "frame_count": frame_count},
    )
    await session.execute(stmt)


async def get_known_pids(session: AsyncSession) -> set[int]:
    rows = await session.execute(select(Illust.pid))
    return {row[0] for row in rows}


async def get_illust_state(session: AsyncSession, pid: int) -> str | None:
    return (
        await session.execute(select(Illust.state).where(Illust.pid == pid))
    ).scalar_one_or_none()


async def create_placeholder_illust(session: AsyncSession, *, pid: int) -> None:
    """Insert a bare illust row for a work that is already deleted on pixiv.

    No title, tags, pages or meta_json: there is nothing real to store, and a
    later sync can still restore it once the work is visible again.
    """
    author = insert(Author).values(id=0, name="", account="")
    author = author.on_conflict_do_nothing(index_elements=[Author.id])
    await session.execute(author)
    stmt = insert(Illust).values(pid=pid, author_id=0, state="deleted")
    stmt = stmt.on_conflict_do_nothing(index_elements=[Illust.pid])
    await session.execute(stmt)


async def mark_illust_deleted(session: AsyncSession, pid: int) -> bool:
    """Flag a work as deleted without touching any of its other columns.

    Returns True when a row was updated. A work that never existed is ignored;
    its bookmark row is still written by the caller.
    """
    result = await session.execute(
        update(Illust)
        .where(Illust.pid == pid, Illust.state != "deleted")
        .values(state="deleted", updated_at=utcnow())
    )
    assert isinstance(result, CursorResult)
    return (result.rowcount or 0) > 0
