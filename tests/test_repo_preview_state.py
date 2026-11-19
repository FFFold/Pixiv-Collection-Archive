import pytest

from fakes import make_illust
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Illust, UgoiraMeta
from pixiv_archive.db.repo import illusts


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "preview.db")
    await database.create_all()
    yield database
    await database.dispose()


async def _seed(
    db,
    pid,
    *,
    state="active",
    type_="illust",
    preview_state="pending",
    preview_attempts=0,
    meta_json=None,
):
    async with db.session() as session:
        if await session.get(Author, 1) is None:
            session.add(Author(id=1, name="a"))
        session.add(
            Illust(
                pid=pid,
                title="t",
                author_id=1,
                type=type_,
                state=state,
                preview_state=preview_state,
                preview_attempts=preview_attempts,
                meta_json=meta_json,
            )
        )
        await session.commit()


async def test_preview_backlog_only_active_unready_under_limit(db):
    await _seed(db, 1, preview_state="pending", preview_attempts=0)
    await _seed(db, 2, preview_state="ready")
    await _seed(db, 3, preview_state="failed", preview_attempts=5)
    await _seed(db, 4, state="deleted")
    async with db.session() as session:
        assert await illusts.get_preview_backlog(session, max_attempts=5) == [1]


async def test_record_preview_failure_marks_failed_at_limit(db):
    await _seed(db, 1, preview_attempts=4)
    async with db.session() as session:
        await illusts.record_preview_failure(session, 1, error="boom", max_attempts=5)
        await session.commit()
        row = await session.get(Illust, 1)
    assert (row.preview_state, row.preview_attempts, row.preview_error) == ("failed", 5, "boom")


async def test_mark_ready_count_and_reset(db):
    await _seed(db, 1, preview_state="failed", preview_attempts=5)
    await _seed(db, 2)
    async with db.session() as session:
        await illusts.mark_previews_ready(session, [2])
        await session.commit()
        assert await illusts.count_previews_missing(session) == 1
        assert await illusts.get_ready_preview_pids(session) == [2]
        assert await illusts.reset_failed_previews(session) == 1
        await session.commit()
        row = await session.get(Illust, 1)
    assert (row.preview_state, row.preview_attempts, row.preview_error) == ("pending", 0, None)


async def test_mark_pending_requeues(db):
    await _seed(db, 1, preview_state="ready")
    async with db.session() as session:
        assert await illusts.mark_previews_pending(session, [1]) == 1
        await session.commit()
        row = await session.get(Illust, 1)
    assert (row.preview_state, row.preview_attempts, row.preview_error) == ("pending", 0, None)


async def test_upsert_illust_preserves_preview_state(db):
    await _seed(db, 1, preview_state="ready")
    async with db.session() as session:
        await illusts.upsert_illust(session, make_illust(1), meta_json="{}")
        await session.commit()
        row = await session.get(Illust, 1)
    assert row.preview_state == "ready"


async def test_meta_json_map_reads_rows(db):
    await _seed(db, 1, meta_json='{"a": 1}')
    await _seed(db, 2, meta_json=None)
    async with db.session() as session:
        mapping = await illusts.get_meta_json_map(session, [1, 2, 3])
    assert mapping == {1: '{"a": 1}', 2: None}


async def test_ugoira_backlog_and_failure_recording(db):
    await _seed(db, 1, type_="ugoira")
    await _seed(db, 2, type_="ugoira")
    await _seed(db, 3, type_="illust")
    async with db.session() as session:
        session.add(UgoiraMeta(pid=2, zip_url="", frames_json="[]", frame_count=0))
        await session.commit()
    async with db.session() as session:
        assert await illusts.get_ugoira_meta_backlog(session, max_attempts=5) == [1, 2]
        await illusts.record_ugoira_meta_failure(session, 1, error="boom")
        await session.commit()
        meta = await session.get(UgoiraMeta, 1)
    assert (meta.zip_url, meta.meta_attempts, meta.meta_error) == ("", 1, "boom")
    async with db.session() as session:
        assert await illusts.count_ugoira_meta_missing(session) == 2


async def test_upsert_ugoira_meta_resets_attempts(db):
    await _seed(db, 1, type_="ugoira")
    async with db.session() as session:
        await illusts.record_ugoira_meta_failure(session, 1, error="boom")
        await illusts.upsert_ugoira_meta(
            session, pid=1, zip_url="https://x/1.zip", frames_json="[]", frame_count=3
        )
        await session.commit()
        meta = await session.get(UgoiraMeta, 1)
    assert (meta.zip_url, meta.frame_count, meta.meta_attempts, meta.meta_error) == (
        "https://x/1.zip",
        3,
        0,
        None,
    )
    async with db.session() as session:
        assert await illusts.count_ugoira_meta_missing(session) == 0


async def test_ugoira_backlog_skips_ready_rows(db):
    await _seed(db, 1, type_="ugoira")
    async with db.session() as session:
        session.add(UgoiraMeta(pid=1, zip_url="https://x/1.zip", frames_json="[]", frame_count=3))
        await session.commit()
    async with db.session() as session:
        assert await illusts.get_ugoira_meta_backlog(session, max_attempts=5) == []
