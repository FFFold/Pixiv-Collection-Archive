import dataclasses

import pytest

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust, IllustPage, IllustTag, Tag, UgoiraMeta
from pixiv_archive.db.repo import bookmarks
from pixiv_archive.download.scope import (
    DownloadScope,
    build_illust_filter,
    empty_scope_matches_nothing,
    resolve_scope,
)
from pixiv_archive.web.schemas import DownloadRequest


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "scope.db")
    await database.create_all()
    yield database
    await database.dispose()


async def _seed_illust(
    db,
    pid: int,
    *,
    author_id: int = 1,
    type_: str = "illust",
    x_restrict: int = 0,
    page_count: int = 1,
    rank: int | None = None,
    state: str = "active",
    page_download_state: str = "pending",
) -> None:
    async with db.session() as session:
        if await session.get(Author, author_id) is None:
            session.add(Author(id=author_id, name=f"a{author_id}"))
        session.add(
            Illust(
                pid=pid,
                title=f"t{pid}",
                author_id=author_id,
                type=type_,
                x_restrict=x_restrict,
                page_count=page_count,
            )
        )
        for index in range(page_count):
            session.add(
                IllustPage(
                    pid=pid,
                    page_index=index,
                    original_url=f"https://i.pximg.net/{pid}_p{index}.jpg",
                    ext=".jpg",
                    download_state=page_download_state,
                )
            )
        if rank is not None:
            await session.commit()
            session.add(bookmarks.Bookmark(pid=pid, restrict="public", rank=rank, state=state))
        await session.commit()


async def test_scope_all_missing_selects_pending_pages(db):
    await _seed_illust(db, 1, rank=0, page_download_state="pending")
    await _seed_illust(db, 2, rank=10, page_download_state="done")
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="all_missing"))
    assert plan.pids == [1, 2]
    assert plan.jobs == [
        (1, "image", "000_p0.jpg"),
        (1, "thumb", "thumb.webp"),
        (2, "thumb", "thumb.webp"),
    ]


async def test_scope_author_filters_by_author(db):
    await _seed_illust(db, 1, author_id=1, rank=0)
    await _seed_illust(db, 2, author_id=2, rank=10)
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="author", author_id=2))
    assert plan.pids == [2]


async def test_scope_selected_uses_explicit_pids(db):
    await _seed_illust(db, 1, rank=0)
    await _seed_illust(db, 2, rank=10)
    await _seed_illust(db, 3, rank=20)
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="selected", pids=[3, 1, 999]))
    assert plan.pids == [1, 3]  # ordered by rank, unknown pids dropped


async def test_scope_rank_range_selects_by_position(db):
    for index, pid in enumerate([10, 20, 30, 40]):
        await _seed_illust(db, pid, rank=index * 1024)
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="rank_range", start=1, count=2))
    assert plan.pids == [20, 30]


async def test_scope_filter_combines_flags(db):
    await _seed_illust(db, 1, rank=0, x_restrict=0, type_="illust")
    await _seed_illust(db, 2, rank=10, x_restrict=1, type_="ugoira")
    await _seed_illust(db, 3, rank=20, x_restrict=1, type_="illust")
    async with db.session() as session:
        plan = await resolve_scope(
            session,
            DownloadScope(kind="filter", x_restrict=1, type="illust"),
        )
    assert plan.pids == [3]


async def test_scope_filter_author_and_restrict(db):
    await _seed_illust(db, 1, author_id=5, rank=0)
    await _seed_illust(db, 2, author_id=5, rank=10)
    await _seed_illust(db, 3, author_id=6, rank=20)
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="filter", author_id=5, pids=[2]))
    assert plan.pids == [2]


async def test_scope_skips_unbookmarked_and_deleted(db):
    await _seed_illust(db, 1, rank=0, state="unbookmarked")
    await _seed_illust(db, 2, rank=10)
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update().where(Illust.pid == 2).values(state="deleted")
        )
        await session.commit()
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="all_missing"))
    assert plan.pids == []


async def test_scope_includes_thumb_job_when_missing(db):
    await _seed_illust(db, 1, rank=0, page_download_state="done")
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="all_missing"))
    assert plan.pids == [1]
    assert plan.jobs == [(1, "thumb", "thumb.webp")]


async def test_scope_ugoira_includes_animation_and_zip_jobs(db):
    await _seed_illust(db, 5, rank=0, type_="ugoira", page_download_state="done")
    async with db.session() as session:
        session.add(
            UgoiraMeta(pid=5, zip_url="https://i.pximg.net/u.zip", frames_json="[]", frame_count=0)
        )
        await session.commit()
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="all_missing"))
    kinds = {kind for _, kind, _ in plan.jobs}
    assert kinds == {"ugoira_zip", "ugoira_mp4", "thumb"}


def test_empty_scope_matches_nothing():
    assert empty_scope_matches_nothing(DownloadScope(kind="filter")) is True
    assert empty_scope_matches_nothing(DownloadScope(kind="all_missing")) is False


async def test_build_illust_filter_expression(db):
    await _seed_illust(db, 1, rank=0, x_restrict=0, type_="illust")
    await _seed_illust(db, 2, rank=10, x_restrict=2, type_="ugoira")
    async with db.session() as session:
        stmt = build_illust_filter(DownloadScope(kind="filter", x_restrict=2, type="ugoira"))
        rows = (await session.execute(stmt)).scalars().all()
    assert rows == [2]


async def test_resolve_scope_marks_ugoira_page_targets(db):
    await _seed_illust(db, 7, rank=0, type_="ugoira", page_count=1, page_download_state="pending")
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="all_missing"))
    assert plan.jobs == [
        (7, "image", "000_p0.jpg"),
        (7, "thumb", "thumb.webp"),
    ]


async def test_scope_multi_page_targets_include_all_pages(db):
    await _seed_illust(db, 9, rank=0, page_count=3, page_download_state="pending")
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="all_missing"))
    assert plan.jobs == [
        (9, "image", "000_p0.jpg"),
        (9, "image", "001_p1.jpg"),
        (9, "image", "002_p2.jpg"),
        (9, "thumb", "thumb.webp"),
    ]


async def test_scope_rank_range_without_count_takes_all_after_start(db):
    for index, pid in enumerate([10, 20, 30]):
        await _seed_illust(db, pid, rank=index * 1024)
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="rank_range", start=1))
    assert plan.pids == [20, 30]


async def test_scope_filter_honours_page_and_tag_filters(db):
    await _seed_illust(db, 10, rank=0, page_count=1)
    await _seed_illust(db, 20, rank=10, page_count=6)
    await _seed_illust(db, 30, rank=20, page_count=2)
    async with db.session() as session:
        tag = Tag(name="cat")
        session.add(tag)
        await session.flush()
        session.add(IllustTag(pid=20, tag_id=tag.id, position=0))
        await session.commit()
    async with db.session() as session:
        by_min = await resolve_scope(session, DownloadScope(kind="filter", page_min=2))
        by_max = await resolve_scope(session, DownloadScope(kind="filter", page_max=1))
        in_range = await resolve_scope(
            session, DownloadScope(kind="filter", page_min=2, page_max=2)
        )
        by_tag = await resolve_scope(session, DownloadScope(kind="filter", tags=["cat"]))
    assert by_min.pids == [20, 30]
    assert by_max.pids == [10]
    # in_range drops pid 20 via page_max and pid 10 via page_min, so both
    # bounds are load-bearing.
    assert in_range.pids == [30]
    assert by_tag.pids == [20]


async def test_scope_filter_honours_views_and_bookmarks_range(db):
    await _seed_illust(db, 1, rank=0)
    await _seed_illust(db, 2, rank=10)
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update().where(Illust.pid == 1).values(total_view=5, total_bookmarks=1)
        )
        await session.execute(
            Illust.__table__.update()
            .where(Illust.pid == 2)
            .values(total_view=5000, total_bookmarks=900)
        )
        await session.commit()
    async with db.session() as session:
        popular = await resolve_scope(session, DownloadScope(kind="filter", bookmarks_min=500))
        rare = await resolve_scope(session, DownloadScope(kind="filter", views_max=100))
    assert popular.pids == [2]
    assert rare.pids == [1]


async def test_scope_filter_honours_restrict_and_unbookmarked(db):
    """Unbookmarked works are excluded from the default filter set.

    ``include_unbookmarked`` widens the bookmark condition; work 1 stays
    excluded while the flag is absent, and appears once the bookmark state
    condition is relaxed.
    """
    await _seed_illust(db, 1, rank=0, state="unbookmarked")
    await _seed_illust(db, 2, rank=10, state="active")
    async with db.session() as session:
        await session.execute(
            Bookmark.__table__.update().where(Bookmark.pid == 1).values(restrict="private")
        )
        await session.commit()
    async with db.session() as session:
        private_default = await resolve_scope(
            session, DownloadScope(kind="filter", restrict="private")
        )
        private_widened = await resolve_scope(
            session,
            DownloadScope(kind="filter", restrict="private", include_unbookmarked=True),
        )
        unbookmarked = await resolve_scope(
            session,
            DownloadScope(kind="filter", only_unbookmarked=True),
        )
        default = await resolve_scope(session, DownloadScope(kind="filter", type="illust"))
    assert private_default.pids == []
    assert private_widened.pids == [1]
    assert unbookmarked.pids == [1]
    assert default.pids == [2]


def test_download_request_fields_match_scope_fields():
    request_fields = set(DownloadRequest.model_fields) - {"scope", "with_thumbs"}
    scope_fields = {f.name for f in dataclasses.fields(DownloadScope)} - {"kind"}
    assert request_fields == scope_fields
