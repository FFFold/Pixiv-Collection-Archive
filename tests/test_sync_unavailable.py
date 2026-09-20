import pytest
from sqlalchemy import select

from fakes import make_illust, make_stub_illust
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import DownloadJob, Illust, IllustPage
from pixiv_archive.db.repo import downloads, illusts
from pixiv_archive.sync.unavailable import is_unavailable


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "unavail.db")
    await database.create_all()
    yield database
    await database.dispose()


def test_stub_by_url_is_unavailable():
    illust = make_stub_illust(123)
    assert is_unavailable(illust) is True


def test_stub_by_zero_author_is_unavailable():
    illust = make_illust(456, user={"id": 0, "name": "", "account": ""})
    assert is_unavailable(illust) is True


def test_normal_illust_is_available():
    assert is_unavailable(make_illust(789)) is False


def test_placeholder_in_meta_pages_is_detected():
    illust = make_illust(
        790,
        meta_pages=[
            {
                "image_urls": {
                    "original": "https://s.pximg.net/common/images/limit_mypixiv_360.png"
                }
            }
        ],
    )
    assert is_unavailable(illust) is True


async def test_mark_illust_deleted_keeps_metadata(db):
    async with db.session() as session:
        await illusts.upsert_illust(session, make_illust(1, title="keep me"), meta_json="{}")
        await session.commit()
    async with db.session() as session:
        changed = await illusts.mark_illust_deleted(session, 1)
        await session.commit()
    assert changed is True
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert row.state == "deleted"
    assert row.title == "keep me"


async def test_skip_pending_and_failed_jobs_for_pid(db):
    async with db.session() as session:
        await illusts.upsert_illust(session, make_illust(7), meta_json="{}")
        session.add(DownloadJob(pid=7, kind="image", target="000_p0.jpg", status="pending"))
        session.add(DownloadJob(pid=7, kind="thumb", target="thumb.webp", status="failed"))
        session.add(DownloadJob(pid=7, kind="image", target="001_p1.jpg", status="done"))
        await session.commit()
    async with db.session() as session:
        skipped = await downloads.skip_jobs_for_pid(session, 7)
        await session.commit()
    assert skipped == 2
    async with db.session() as session:
        rows = (await session.execute(select(DownloadJob))).scalars().all()
    by_target = {row.target: row.status for row in rows}
    assert by_target["000_p0.jpg"] == "skipped"
    assert by_target["thumb.webp"] == "skipped"
    assert by_target["001_p1.jpg"] == "done"
