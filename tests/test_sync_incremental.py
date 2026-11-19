import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update

from fakes import FakeClient, FakeDownloader, make_illust, page
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Illust, UgoiraMeta
from pixiv_archive.db.repo import bookmarks, sync_runs
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.pixiv.errors import NetworkError
from pixiv_archive.sync.orchestrator import (
    PREVIEW_ATTEMPTS_LIMIT,
    UGOIRA_META_ATTEMPTS_LIMIT,
    MetadataSyncService,
)


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "sync.db")
    await database.create_all()
    yield database
    await database.dispose()


def build_service(db, tmp_path, client, downloader, *, previews=True) -> MetadataSyncService:
    return MetadataSyncService(
        db=db,
        client=client,
        storage=WorksStorage(tmp_path / "works"),
        downloader=downloader,
        download_previews=previews,
    )


async def test_incremental_inserts_new_bookmarks_with_ordered_ranks(db, tmp_path):
    client = FakeClient(
        {
            "public": [page([make_illust(101), make_illust(102)], cursor=None)],
            "private": [],
        }
    )
    downloader = FakeDownloader()
    service = build_service(db, tmp_path, client, downloader)

    result = await service.run_incremental()

    assert result.status == "completed"
    assert result.new_count == 2
    assert result.pages_fetched == 2  # one public page + one empty private page
    async with db.session() as session:
        pids = await bookmarks.ordered_pids(session)
        ranks = await bookmarks.get_rank_map(session)
        metadata = (await session.execute(select(Illust).order_by(Illust.pid))).scalars().all()
    assert pids == [101, 102]  # listing order preserved
    assert ranks[101] < ranks[102]
    assert [m.pid for m in metadata] == [101, 102]
    assert downloader.urls == [
        "https://i.pximg.net/101_sq.jpg",
        "https://i.pximg.net/102_sq.jpg",
    ]
    assert result.previews_fetched == 2
    assert (WorksStorage(tmp_path / "works").preview_path(101)).exists()
    assert (WorksStorage(tmp_path / "works").meta_path(101)).exists()


async def test_incremental_stops_at_all_known_page(db, tmp_path):
    first = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    await build_service(db, tmp_path, first, FakeDownloader()).run_incremental()

    second = FakeClient(
        {
            "public": [page([make_illust(1)], cursor=None)],
            "private": [],
        }
    )
    result = await build_service(db, tmp_path, second, FakeDownloader()).run_incremental()
    assert result.new_count == 0
    # public page 1 was all known -> stop; private still queried once
    assert second.page_requests == [("public", None), ("private", None)]


async def test_incremental_follows_cursor_until_known_page(db, tmp_path):
    client = FakeClient(
        {
            "public": [
                page([make_illust(3)], cursor=999),
                page([make_illust(2)], cursor=888),
                page([make_illust(1)], cursor=None),
            ],
            "private": [],
        }
    )
    result = await build_service(db, tmp_path, client, FakeDownloader()).run_incremental()
    assert result.new_count == 3
    assert [req for req in client.page_requests if req[0] == "public"] == [
        ("public", None),
        ("public", 999),
        ("public", 888),
    ]
    async with db.session() as session:
        assert await bookmarks.ordered_pids(session) == [3, 2, 1]


async def test_incremental_second_batch_goes_to_front(db, tmp_path):
    first = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    await build_service(db, tmp_path, first, FakeDownloader()).run_incremental()
    second = FakeClient(
        {
            "public": [
                page([make_illust(3), make_illust(1)], cursor=None),
            ],
            "private": [],
        }
    )
    await build_service(db, tmp_path, second, FakeDownloader()).run_incremental()
    async with db.session() as session:
        assert await bookmarks.ordered_pids(session) == [3, 1]


async def test_incremental_reactivates_unbookmarked(db, tmp_path):
    setup = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    await build_service(db, tmp_path, setup, FakeDownloader()).run_incremental()
    async with db.session() as session:
        await bookmarks.mark_unbookmarked(session, [1], now=datetime.now(UTC))
        await session.commit()

    again = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, again, FakeDownloader()).run_incremental()
    assert result.new_count == 1
    async with db.session() as session:
        assert await bookmarks.get_bookmark_states(session) == {1: "active"}


async def test_incremental_fetches_ugoira_metadata(db, tmp_path):
    client = FakeClient(
        {
            "public": [page([make_illust(50, type_="ugoira")], cursor=None)],
            "private": [],
        }
    )
    client.ugoira_frames = [{"file": "000000.jpg", "delay": 33}]
    result = await build_service(db, tmp_path, client, FakeDownloader()).run_incremental()
    assert client.ugoira_calls == [50]
    assert result.ugoira_meta_fetched == 1
    async with db.session() as session:
        row = (await session.execute(select(UgoiraMeta))).scalar_one()
    assert row.zip_url == "https://i.pximg.net/50.zip"
    assert row.frame_count == 1
    assert "000000.jpg" in row.frames_json


async def test_incremental_counts_ugoira_failure_without_aborting(db, tmp_path):
    client = FakeClient(
        {
            "public": [page([make_illust(60, type_="ugoira"), make_illust(61)], cursor=None)],
            "private": [],
        }
    )
    client.ugoira_error = NetworkError("boom")
    result = await build_service(db, tmp_path, client, FakeDownloader()).run_incremental()
    assert result.status == "completed"
    assert result.new_count == 2
    assert result.failed_count == 1
    assert result.ugoira_meta_fetched == 0


async def test_incremental_counts_preview_failures(db, tmp_path):
    client = FakeClient({"public": [page([make_illust(70)], cursor=None)], "private": []})
    downloader = FakeDownloader(fail_urls={"https://i.pximg.net/70_sq.jpg"})
    result = await build_service(db, tmp_path, client, downloader).run_incremental()
    assert result.previews_fetched == 0
    assert result.previews_failed == 1
    assert result.status == "completed"


async def test_incremental_respects_max_pages(db, tmp_path):
    client = FakeClient(
        {
            "public": [
                page([make_illust(3)], cursor=999),
                page([make_illust(2)], cursor=888),
                page([make_illust(1)], cursor=None),
            ],
            "private": [],
        }
    )
    result = await build_service(db, tmp_path, client, FakeDownloader()).run_incremental(
        max_pages=2
    )
    assert result.new_count == 2
    assert result.status == "completed"


async def test_incremental_records_sync_run_row(db, tmp_path):
    client = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, client, FakeDownloader()).run_incremental()
    async with db.session() as session:
        row = (await session.execute(select(sync_runs.SyncRun))).scalar_one()
        last_full = await sync_runs.get_last_full_sync(session)
    assert row.id == result.run_id
    assert row.status == "completed"
    assert row.new_count == 1
    assert last_full is None


async def test_incremental_skips_previews_when_disabled(db, tmp_path):
    client = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    downloader = FakeDownloader()
    service = build_service(db, tmp_path, client, downloader, previews=False)
    result = await service.run_incremental()
    assert downloader.urls == []
    assert result.previews_fetched == 0
    assert result.previews_pending == 1


async def test_incremental_writes_readable_meta_json(db, tmp_path):
    client = FakeClient({"public": [page([make_illust(90)], cursor=None)], "private": []})
    await build_service(db, tmp_path, client, FakeDownloader()).run_incremental()
    payload = json.loads((WorksStorage(tmp_path / "works").meta_path(90)).read_text("utf-8"))
    assert payload["id"] == 90
    assert payload["title"] == "t90"
    assert payload["user"]["name"] == "artist"


async def test_incremental_retries_missing_preview_on_next_run(db, tmp_path):
    url = "https://i.pximg.net/70_sq.jpg"
    first = FakeClient({"public": [page([make_illust(70)], cursor=None)], "private": []})
    r1 = await build_service(db, tmp_path, first, FakeDownloader(fail_urls={url})).run_incremental()
    assert r1.previews_failed == 1
    assert r1.previews_pending == 1

    second = FakeClient({"public": [page([make_illust(70)], cursor=None)], "private": []})
    d2 = FakeDownloader()
    r2 = await build_service(db, tmp_path, second, d2).run_incremental()
    assert r2.new_count == 0
    assert d2.urls == [url]
    assert r2.previews_fetched == 1
    assert r2.previews_pending == 0
    async with db.session() as session:
        row = await session.get(Illust, 70)
    assert row.preview_state == "ready"


async def test_incremental_marks_existing_preview_ready_without_download(db, tmp_path):
    setup = FakeClient({"public": [page([make_illust(71)], cursor=None)], "private": []})
    await build_service(db, tmp_path, setup, FakeDownloader()).run_incremental()
    async with db.session() as session:
        await session.execute(
            update(Illust).where(Illust.pid == 71).values(preview_state="pending")
        )
        await session.commit()

    again = FakeClient({"public": [page([make_illust(71)], cursor=None)], "private": []})
    downloader = FakeDownloader()
    result = await build_service(db, tmp_path, again, downloader).run_incremental()
    assert downloader.urls == []
    assert result.previews_fetched == 0
    async with db.session() as session:
        row = await session.get(Illust, 71)
    assert row.preview_state == "ready"


async def test_preview_failures_stop_at_attempt_limit(db, tmp_path):
    url = "https://i.pximg.net/72_sq.jpg"
    for _ in range(PREVIEW_ATTEMPTS_LIMIT):
        client = FakeClient({"public": [page([make_illust(72)], cursor=None)], "private": []})
        await build_service(db, tmp_path, client, FakeDownloader(fail_urls={url})).run_incremental()
    async with db.session() as session:
        row = await session.get(Illust, 72)
    assert (row.preview_state, row.preview_attempts) == ("failed", PREVIEW_ATTEMPTS_LIMIT)

    again = FakeClient({"public": [page([make_illust(72)], cursor=None)], "private": []})
    downloader = FakeDownloader()
    result = await build_service(db, tmp_path, again, downloader).run_incremental()
    assert downloader.urls == []
    assert result.previews_pending == 1


async def test_repair_assets_reset_requeues_ready_rows_with_missing_files(db, tmp_path):
    url = "https://i.pximg.net/73_sq.jpg"
    client = FakeClient({"public": [page([make_illust(73)], cursor=None)], "private": []})
    service = build_service(db, tmp_path, client, FakeDownloader())
    await service.run_incremental()
    storage = WorksStorage(tmp_path / "works")
    storage.preview_path(73).unlink()

    downloader = FakeDownloader()
    again = FakeClient({"public": [], "private": []})
    repair = await build_service(db, tmp_path, again, downloader).repair_assets(reset_failed=True)
    assert repair.reset == 1
    assert downloader.urls == [url]
    assert storage.preview_path(73).exists()


def test_preview_url_prefers_square_medium():
    payload = (
        '{"image_urls": {"medium": "https://i/medium.jpg", "square_medium": "https://i/sq.jpg"}}'
    )
    assert MetadataSyncService._preview_url(payload) == "https://i/sq.jpg"
    assert MetadataSyncService._preview_url(
        '{"image_urls": {"medium": "https://i/medium.jpg"}}'
    ) == ("https://i/medium.jpg")
    assert MetadataSyncService._preview_url(None) is None


async def test_invalid_preview_bytes_are_not_marked_ready(db, tmp_path):
    url = "https://i.pximg.net/80_sq.jpg"
    client = FakeClient({"public": [page([make_illust(80)], cursor=None)], "private": []})
    result = await build_service(
        db, tmp_path, client, FakeDownloader(corrupt_urls={url})
    ).run_incremental()
    assert result.previews_failed == 1
    assert not WorksStorage(tmp_path / "works").preview_path(80).exists()
    async with db.session() as session:
        row = await session.get(Illust, 80)
    assert row.preview_state == "pending"
    assert row.preview_attempts == 1
    assert "invalid" in (row.preview_error or "")


async def test_one_failing_preview_does_not_abort_the_batch(db, tmp_path):
    worst = "https://i.pximg.net/81_sq.jpg"
    client = FakeClient(
        {"public": [page([make_illust(81), make_illust(82)], cursor=None)], "private": []}
    )
    result = await build_service(
        db, tmp_path, client, FakeDownloader(error_urls={worst})
    ).run_incremental()
    assert result.status == "completed"
    assert result.previews_fetched == 1
    assert result.previews_failed == 1
    assert WorksStorage(tmp_path / "works").preview_path(82).exists()


async def test_ugoira_metadata_failure_is_retried_on_next_run(db, tmp_path):
    first = FakeClient(
        {"public": [page([make_illust(50, type_="ugoira")], cursor=None)], "private": []}
    )
    first.ugoira_error = NetworkError("boom")
    r1 = await build_service(db, tmp_path, first, FakeDownloader()).run_incremental()
    assert r1.ugoira_meta_fetched == 0
    async with db.session() as session:
        meta = await session.get(UgoiraMeta, 50)
    assert (meta.zip_url, meta.meta_attempts) == ("", 1)

    second = FakeClient(
        {"public": [page([make_illust(50, type_="ugoira")], cursor=None)], "private": []}
    )
    r2 = await build_service(db, tmp_path, second, FakeDownloader()).run_incremental()
    assert second.ugoira_calls == [50]
    assert r2.ugoira_meta_fetched == 1
    async with db.session() as session:
        meta = await session.get(UgoiraMeta, 50)
    assert (meta.zip_url, meta.meta_attempts) == ("https://i.pximg.net/50.zip", 0)


async def test_ugoira_metadata_without_zip_counts_as_failure(db, tmp_path):
    client = FakeClient(
        {"public": [page([make_illust(51, type_="ugoira")], cursor=None)], "private": []}
    )
    client.ugoira_has_zip = False
    result = await build_service(db, tmp_path, client, FakeDownloader()).run_incremental()
    assert result.status == "completed"
    assert result.ugoira_meta_fetched == 0
    assert result.failed_count == 1
    async with db.session() as session:
        meta = await session.get(UgoiraMeta, 51)
    assert (meta.zip_url, meta.meta_attempts) == ("", 1)


async def test_ugoira_metadata_without_zip_stops_after_limit(db, tmp_path):
    for _ in range(UGOIRA_META_ATTEMPTS_LIMIT):
        client = FakeClient(
            {"public": [page([make_illust(53, type_="ugoira")], cursor=None)], "private": []}
        )
        client.ugoira_has_zip = False
        await build_service(db, tmp_path, client, FakeDownloader()).run_incremental()

    again = FakeClient({"public": [], "private": []})
    await build_service(db, tmp_path, again, FakeDownloader()).run_incremental()
    assert again.ugoira_calls == []
    async with db.session() as session:
        meta = await session.get(UgoiraMeta, 53)
    assert meta.meta_attempts == UGOIRA_META_ATTEMPTS_LIMIT


async def test_ugoira_unexpected_error_does_not_abort_sync(db, tmp_path):
    client = FakeClient(
        {"public": [page([make_illust(52, type_="ugoira")], cursor=None)], "private": []}
    )
    client.ugoira_error = ValueError("bad payload")
    result = await build_service(db, tmp_path, client, FakeDownloader()).run_incremental()
    assert result.status == "completed"
    assert result.failed_count == 1
    async with db.session() as session:
        meta = await session.get(UgoiraMeta, 52)
    assert (meta.zip_url, meta.meta_attempts) == ("", 1)
