import pytest
from sqlalchemy import select

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Illust, IllustPage, IllustTag, Tag
from pixiv_archive.db.repo import illusts
from pixiv_archive.pixiv.models import Illust as PixivIllust


def make_illust(**overrides) -> PixivIllust:
    payload = {
        "id": 100,
        "title": "hello",
        "description": "desc",
        "type": "illust",
        "page_count": 2,
        "width": 1000,
        "height": 2000,
        "x_restrict": 1,
        "sanity_level": 6,
        "illust_ai_type": 2,
        "total_view": 10,
        "total_bookmarks": 20,
        "create_date": "2026-01-02T03:04:05+09:00",
        "user": {"id": 7, "name": "artist", "account": "acct"},
        "tags": [
            {"name": "R-18", "translated_name": None},
            {"name": "オリジナル", "translated_name": "原创"},
        ],
        "meta_pages": [
            {"image_urls": {"original": "https://i.pximg.net/a_p0.jpg"}},
            {"image_urls": {"original": "https://i.pximg.net/a_p1.png"}},
        ],
        "image_urls": {"square_medium": "https://i.pximg.net/a_sq.jpg"},
    }
    payload.update(overrides)
    return PixivIllust.model_validate(payload)


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "repo.db")
    await database.create_all()
    yield database
    await database.dispose()


async def test_url_ext():
    assert illusts.url_ext("https://i.pximg.net/img/a_p0.jpg") == ".jpg"
    assert illusts.url_ext("https://i.pximg.net/img/a_p1.PNG?x=1") == ".png"
    assert illusts.url_ext("https://i.pximg.net/img/noext") == ".jpg"


async def test_upsert_illust_inserts_everything(db):
    illust = make_illust()
    async with db.session() as session:
        await illusts.upsert_illust(session, illust, meta_json='{"id": 100}')
        await session.commit()

    async with db.session() as session:
        row = (await session.execute(select(Illust))).scalar_one()
        assert row.title == "hello"
        assert row.author_id == 7
        assert row.x_restrict == 1
        assert row.meta_json == '{"id": 100}'

        pages = (
            (await session.execute(select(IllustPage).order_by(IllustPage.page_index)))
            .scalars()
            .all()
        )
        assert [p.original_url for p in pages] == [
            "https://i.pximg.net/a_p0.jpg",
            "https://i.pximg.net/a_p1.png",
        ]
        assert [p.ext for p in pages] == [".jpg", ".png"]
        assert all(p.download_state == "pending" for p in pages)

        tag_rows = (
            await session.execute(select(Tag.name, Tag.translated_name).order_by(Tag.id))
        ).all()
        assert ("R-18", None) in tag_rows
        assert ("オリジナル", "原创") in tag_rows

        links = (
            (
                await session.execute(
                    select(IllustTag.position)
                    .where(IllustTag.pid == 100)
                    .order_by(IllustTag.position)
                )
            )
            .scalars()
            .all()
        )
        assert links == [0, 1]


async def test_upsert_illust_updates_without_duplicating(db):
    async with db.session() as session:
        await illusts.upsert_illust(session, make_illust(), meta_json=None)
        await session.commit()
    async with db.session() as session:
        await illusts.upsert_illust(
            session, make_illust(title="renamed", total_bookmarks=999), meta_json=None
        )
        await session.commit()

    async with db.session() as session:
        rows = (await session.execute(select(Illust))).scalars().all()
        assert len(rows) == 1
        assert rows[0].title == "renamed"
        assert rows[0].total_bookmarks == 999
        tags = (await session.execute(select(Tag))).scalars().all()
        assert len(tags) == 2  # tags are replaced, not duplicated


async def test_upsert_illust_preserves_page_download_state(db):
    async with db.session() as session:
        await illusts.upsert_illust(session, make_illust(), meta_json=None)
        await session.commit()
    async with db.session() as session:
        page = (
            await session.execute(select(IllustPage).where(IllustPage.page_index == 0))
        ).scalar_one()
        page.download_state = "done"
        page.attempts = 2
        await session.commit()
    async with db.session() as session:
        await illusts.upsert_illust(
            session,
            make_illust(
                meta_pages=[
                    {"image_urls": {"original": "https://i.pximg.net/a_p0_v2.jpg"}},
                    {"image_urls": {"original": "https://i.pximg.net/a_p1.png"}},
                ]
            ),
            meta_json=None,
        )
        await session.commit()
    async with db.session() as session:
        page = (
            await session.execute(select(IllustPage).where(IllustPage.page_index == 0))
        ).scalar_one()
    assert page.original_url == "https://i.pximg.net/a_p0_v2.jpg"
    assert page.download_state == "done"  # preserved
    assert page.attempts == 2  # preserved


async def test_upsert_illust_handles_single_page(db):
    illust = make_illust(
        page_count=1,
        meta_pages=[],
        meta_single_page={"original_image_url": "https://i.pximg.net/single.jpg"},
    )
    async with db.session() as session:
        await illusts.upsert_illust(session, illust, meta_json=None)
        await session.commit()
    async with db.session() as session:
        pages = (await session.execute(select(IllustPage))).scalars().all()
    assert len(pages) == 1
    assert pages[0].original_url == "https://i.pximg.net/single.jpg"


async def test_get_known_pids(db):
    async with db.session() as session:
        await illusts.upsert_illust(session, make_illust(), meta_json=None)
        await session.commit()
    async with db.session() as session:
        known = await illusts.get_known_pids(session)
    assert known == {100}


async def test_upsert_ugoira_meta(db):
    async with db.session() as session:
        await illusts.upsert_illust(session, make_illust(type="ugoira"), meta_json=None)
        await illusts.upsert_ugoira_meta(
            session,
            pid=100,
            zip_url="https://i.pximg.net/u.zip",
            frames_json='[{"file": "000000.jpg", "delay": 33}]',
            frame_count=1,
        )
        await session.commit()
    async with db.session() as session:
        await illusts.upsert_ugoira_meta(
            session, pid=100, zip_url="https://i.pximg.net/u2.zip", frames_json="[]", frame_count=0
        )
        await session.commit()
    from pixiv_archive.db.models import UgoiraMeta

    async with db.session() as session:
        row = (await session.execute(select(UgoiraMeta))).scalar_one()
    assert row.zip_url == "https://i.pximg.net/u2.zip"
    assert row.frame_count == 0
