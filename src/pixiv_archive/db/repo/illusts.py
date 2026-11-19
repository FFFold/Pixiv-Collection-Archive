import os
from urllib.parse import urlsplit

from sqlalchemy import CursorResult, case, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

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
        "preview_state": "pending",
        "updated_at": utcnow(),
    }
    stmt = insert(Illust).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Illust.pid],
        set_={key: value for key, value in values.items() if key not in ("pid", "preview_state")},
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
        pid=pid,
        zip_url=zip_url,
        frames_json=frames_json,
        frame_count=frame_count,
        meta_attempts=0,
        meta_error=None,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[UgoiraMeta.pid],
        set_={
            "zip_url": zip_url,
            "frames_json": frames_json,
            "frame_count": frame_count,
            "meta_attempts": 0,
            "meta_error": None,
        },
    )
    await session.execute(stmt)


_PID_CHUNK = 500


def _chunks(pids: list[int], size: int = _PID_CHUNK) -> list[list[int]]:
    return [pids[index : index + size] for index in range(0, len(pids), size)]


async def get_preview_backlog(session: AsyncSession, *, max_attempts: int) -> list[int]:
    """Active illusts whose preview is not ready and still has retries left."""
    rows = await session.execute(
        select(Illust.pid)
        .where(
            Illust.state == "active",
            Illust.preview_state != "ready",
            Illust.preview_attempts < max_attempts,
        )
        .order_by(Illust.pid)
    )
    return [int(row[0]) for row in rows]


async def get_meta_json_map(session: AsyncSession, pids: list[int]) -> dict[int, str | None]:
    result: dict[int, str | None] = {}
    for chunk in _chunks(pids):
        rows = await session.execute(
            select(Illust.pid, Illust.meta_json).where(Illust.pid.in_(chunk))
        )
        for pid, meta_json in rows:
            result[int(pid)] = meta_json
    return result


async def mark_previews_ready(session: AsyncSession, pids: list[int]) -> int:
    changed = 0
    for chunk in _chunks(pids):
        result = await session.execute(
            update(Illust)
            .where(Illust.pid.in_(chunk))
            .values(preview_state="ready", preview_error=None)
        )
        assert isinstance(result, CursorResult)
        changed += result.rowcount or 0
    return changed


async def mark_previews_pending(session: AsyncSession, pids: list[int]) -> int:
    changed = 0
    for chunk in _chunks(pids):
        result = await session.execute(
            update(Illust)
            .where(Illust.pid.in_(chunk))
            .values(preview_state="pending", preview_attempts=0, preview_error=None)
        )
        assert isinstance(result, CursorResult)
        changed += result.rowcount or 0
    return changed


async def get_ready_preview_pids(session: AsyncSession) -> list[int]:
    rows = await session.execute(
        select(Illust.pid)
        .where(Illust.state == "active", Illust.preview_state == "ready")
        .order_by(Illust.pid)
    )
    return [int(row[0]) for row in rows]


async def record_preview_failure(
    session: AsyncSession, pid: int, *, error: str, max_attempts: int
) -> None:
    next_attempts = Illust.preview_attempts + 1
    await session.execute(
        update(Illust)
        .where(Illust.pid == pid)
        .values(
            preview_attempts=next_attempts,
            preview_error=error[:500],
            preview_state=case((next_attempts >= max_attempts, "failed"), else_="pending"),
        )
    )


async def count_previews_missing(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Illust)
                .where(Illust.state == "active", Illust.preview_state != "ready")
            )
        ).scalar_one()
    )


async def reset_failed_previews(session: AsyncSession) -> int:
    result = await session.execute(
        update(Illust)
        .where(Illust.preview_state == "failed")
        .values(preview_state="pending", preview_attempts=0, preview_error=None)
    )
    assert isinstance(result, CursorResult)
    return result.rowcount or 0


def _ugoira_pending_condition() -> ColumnElement[bool]:
    return or_(
        UgoiraMeta.pid.is_(None),
        UgoiraMeta.zip_url == "",
    )


async def get_ugoira_meta_backlog(session: AsyncSession, *, max_attempts: int) -> list[int]:
    rows = await session.execute(
        select(Illust.pid)
        .outerjoin(UgoiraMeta, UgoiraMeta.pid == Illust.pid)
        .where(
            Illust.state == "active",
            Illust.type == "ugoira",
            _ugoira_pending_condition(),
            func.coalesce(UgoiraMeta.meta_attempts, 0) < max_attempts,
        )
        .order_by(Illust.pid)
    )
    return [int(row[0]) for row in rows]


async def count_ugoira_meta_missing(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Illust)
                .outerjoin(UgoiraMeta, UgoiraMeta.pid == Illust.pid)
                .where(
                    Illust.state == "active",
                    Illust.type == "ugoira",
                    _ugoira_pending_condition(),
                )
            )
        ).scalar_one()
    )


async def record_ugoira_meta_failure(session: AsyncSession, pid: int, *, error: str) -> None:
    stmt = insert(UgoiraMeta).values(
        pid=pid,
        zip_url="",
        frames_json="[]",
        frame_count=0,
        meta_attempts=1,
        meta_error=error[:500],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[UgoiraMeta.pid],
        set_={
            "meta_attempts": UgoiraMeta.meta_attempts + 1,
            "meta_error": error[:500],
        },
    )
    await session.execute(stmt)


async def get_known_pids(session: AsyncSession) -> set[int]:
    rows = await session.execute(select(Illust.pid))
    return {row[0] for row in rows}


async def get_illust_states(session: AsyncSession) -> dict[int, str]:
    rows = await session.execute(select(Illust.pid, Illust.state))
    return {pid: state for pid, state in rows}


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
    stmt = insert(Illust).values(pid=pid, author_id=0, state="deleted", page_count=0)
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
