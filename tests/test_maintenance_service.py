from pathlib import Path

import pytest
from sqlalchemy import select

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust, IllustPage
from pixiv_archive.maintenance.service import (
    db_check,
    preview_repair_download_state,
    rebuild_storage_stats,
    repair_download_state,
)


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "m.db")
    await database.create_all()
    yield database
    await database.dispose()


def _write_work(works: Path, pid: int, *, pages: int = 1, thumb: bool = True) -> int:
    original = works / str(pid) / "original"
    original.mkdir(parents=True)
    total = 0
    for index in range(pages):
        payload = b"x" * (100 + index)
        (original / f"{index:03d}_p{index}.jpg").write_bytes(payload)
        total += len(payload)
    if thumb:
        payload = b"t" * 50
        (works / str(pid) / "thumb.webp").write_bytes(payload)
        total += len(payload)
    return total


async def _seed(db, pid: int, *, pages: int = 1) -> None:
    async with db.session() as session:
        if await session.get(Author, 1) is None:
            session.add(Author(id=1, name="a"))
        session.add(Illust(pid=pid, title=f"t{pid}", author_id=1, page_count=pages))
        for index in range(pages):
            session.add(
                IllustPage(
                    pid=pid,
                    page_index=index,
                    original_url=f"https://i.pximg.net/{pid}_p{index}.jpg",
                    ext=".jpg",
                )
            )
        await session.commit()
    async with db.session() as session:
        session.add(Bookmark(pid=pid, restrict="public", rank=pid, state="active"))
        await session.commit()


async def test_rebuild_storage_stats_sets_size_and_flags(db, tmp_path):
    await _seed(db, 1, pages=2)
    await _seed(db, 2, pages=1)
    works = tmp_path / "works"
    expected1 = _write_work(works, 1, pages=2, thumb=True)
    expected2 = _write_work(works, 2, pages=1, thumb=False)

    async with db.session() as session:
        result = await rebuild_storage_stats(session, works)
    assert result["works"] == 2

    async with db.session() as session:
        rows = {illust.pid: illust for illust in (await session.execute(select(Illust))).scalars()}
    assert rows[1].byte_size == expected1
    assert rows[1].thumb_ready is True
    assert rows[2].byte_size == expected2
    assert rows[2].thumb_ready is False


async def test_repair_preview_and_apply(db, tmp_path):
    await _seed(db, 5, pages=2)
    works = tmp_path / "works"
    _write_work(works, 5, pages=1, thumb=False)
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update()
            .where(Illust.pid == 5)
            .values(has_original=True, page_downloaded_count=2)
        )
        await session.execute(
            IllustPage.__table__.update().where(IllustPage.pid == 5).values(download_state="done")
        )
        await session.commit()

    async with db.session() as session:
        preview = await preview_repair_download_state(session, works)
    assert preview == {"pages_to_reset": 1, "works_to_fix": 1}

    async with db.session() as session:
        await repair_download_state(session, works)

    async with db.session() as session:
        pages = (
            (await session.execute(select(IllustPage).order_by(IllustPage.page_index)))
            .scalars()
            .all()
        )
        illust = (await session.execute(select(Illust))).scalar_one()
    assert [page.download_state for page in pages] == ["done", "pending"]
    assert illust.has_original is False
    assert illust.page_downloaded_count == 1


async def test_db_check_reports_orphans_and_mismatch(db, tmp_path):
    await _seed(db, 6, pages=1)
    works = tmp_path / "works"
    # DB says downloaded, but no files exist on disk
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update().where(Illust.pid == 6).values(has_original=True)
        )
        await session.commit()

    async with db.session() as session:
        report = await db_check(session, works)
    assert report["ok"] is False
    kinds = {issue["kind"] for issue in report["issues"]}
    assert "missing_files" in kinds


async def test_repair_ignores_stray_files_beyond_known_pages(db, tmp_path):
    """A stray file in original/ must not inflate counts or flip has_original."""
    await _seed(db, 7, pages=1)
    works = tmp_path / "works"
    _write_work(works, 7, pages=1, thumb=True)
    # stray file (not a known IllustPage index)
    (works / "7" / "original" / "999_p999.jpg").write_bytes(b"stray")
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update()
            .where(Illust.pid == 7)
            .values(has_original=True, page_downloaded_count=1)
        )
        await session.execute(
            IllustPage.__table__.update().where(IllustPage.pid == 7).values(download_state="done")
        )
        await session.commit()

    async with db.session() as session:
        await repair_download_state(session, works)

    async with db.session() as session:
        illust = await session.get(Illust, 7)
        page = (await session.execute(select(IllustPage))).scalar_one()
    assert page.download_state == "done"
    assert illust.page_downloaded_count == 1
    assert illust.has_original is True


async def test_db_check_handles_multi_row_integrity_output(db, tmp_path, monkeypatch):
    """A corrupt database returns several integrity_check rows, not one."""
    await _seed(db, 8, pages=1)
    works = tmp_path / "works"

    from pixiv_archive.maintenance import service as service_module

    real_execute = service_module.AsyncSession.execute

    async def fake_execute(self, statement, *args, **kwargs):  # noqa: ANN001
        if "integrity_check" in str(statement):

            class MultiRow:
                def scalars(self):
                    class S:
                        def all(self_inner):
                            return ["rowid 3 missing", "rowid 7 missing"]

                    return S()

            return MultiRow()
        return await real_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(service_module.AsyncSession, "execute", fake_execute)
    async with db.session() as session:
        report = await db_check(session, works)
    assert report["ok"] is False
    integrity = next(issue for issue in report["issues"] if issue["kind"] == "integrity")
    assert integrity["count"] == 2
