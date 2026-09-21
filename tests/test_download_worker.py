from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from fakes import FakeDownloader
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust, IllustPage, UgoiraMeta
from pixiv_archive.db.repo import downloads
from pixiv_archive.download.scope import DownloadScope
from pixiv_archive.download.worker import DownloadReport, DownloadWorker, DownloadWorkerConfig
from pixiv_archive.media.storage import WorksStorage


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "worker.db")
    await database.create_all()
    yield database
    await database.dispose()


async def _seed(db, pid: int, *, pages: int = 1, type_: str = "illust", rank: int = 0) -> None:
    async with db.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=pid, title=f"t{pid}", author_id=1, page_count=pages, type=type_))
        await session.commit()
    async with db.session() as session:
        for index in range(pages):
            session.add(
                IllustPage(
                    pid=pid,
                    page_index=index,
                    original_url=f"https://i.pximg.net/{pid}_p{index}.jpg",
                    ext=".jpg",
                )
            )
        if type_ == "ugoira":
            session.add(
                UgoiraMeta(
                    pid=pid,
                    zip_url="https://i.pximg.net/u.zip",
                    frames_json='[{"file": "000000.jpg", "delay": 100}]',
                    frame_count=1,
                )
            )
        await session.commit()
    async with db.session() as session:
        session.add(Bookmark(pid=pid, restrict="public", rank=rank, state="active"))
        await session.commit()


def make_worker(db, tmp_path, downloader, *, transcode=None) -> DownloadWorker:
    config = DownloadWorkerConfig(concurrency=2, max_attempts=3, transcode=transcode)
    return DownloadWorker(
        db=db,
        storage=WorksStorage(tmp_path / "works"),
        downloader=downloader,
        config=config,
    )


async def test_worker_downloads_images_and_marks_done(db, tmp_path):
    await _seed(db, 1, pages=2)
    downloader = FakeDownloader()
    worker = make_worker(db, tmp_path, downloader)

    report = await worker.run_scope(DownloadScope(kind="all_missing"))

    assert report.status == "completed"
    assert report.pages_done == 2
    assert report.failed == 0
    storage = WorksStorage(tmp_path / "works")
    assert (storage.original_dir(1) / "000_p0.jpg").exists()
    assert (storage.original_dir(1) / "001_p1.jpg").exists()
    async with db.session() as session:
        rows = (
            (await session.execute(select(IllustPage).order_by(IllustPage.page_index)))
            .scalars()
            .all()
        )
        illust = (await session.execute(select(Illust))).scalar_one()
    assert [row.download_state for row in rows] == ["done", "done"]
    assert illust.has_original is True
    assert illust.page_downloaded_count == 2


async def test_worker_records_failed_page_with_error(db, tmp_path):
    await _seed(db, 1, pages=2)
    downloader = FakeDownloader(fail_urls={"https://i.pximg.net/1_p1.jpg"})
    worker = make_worker(db, tmp_path, downloader)

    report = await worker.run_scope(DownloadScope(kind="all_missing"))

    assert report.failed >= 1
    async with db.session() as session:
        rows = (
            (await session.execute(select(IllustPage).order_by(IllustPage.page_index)))
            .scalars()
            .all()
        )
        illust = (await session.execute(select(Illust))).scalar_one()
    assert rows[0].download_state == "done"
    assert rows[1].download_state == "failed"
    assert rows[1].last_error
    assert illust.has_original is False


async def test_worker_records_invalid_image_as_failed(db, tmp_path):
    await _seed(db, 1, pages=1)
    downloader = FakeDownloader()
    downloader.fetch_bytes = _garbage_bytes  # type: ignore[method-assign]
    worker = make_worker(db, tmp_path, downloader)

    await worker.run_scope(DownloadScope(kind="all_missing"))

    async with db.session() as session:
        page = (await session.execute(select(IllustPage))).scalar_one()
    assert page.download_state == "failed"
    assert page.last_error == "invalid image data"


async def _garbage_bytes(url: str) -> bytes:
    return b"definitely not an image"


async def test_worker_generates_thumbnail_from_downloaded_page(db, tmp_path):
    await _seed(db, 2, pages=1)
    downloader = FakeDownloader()
    worker = make_worker(db, tmp_path, downloader)

    report = await worker.run_scope(DownloadScope(kind="all_missing"))

    assert report.pages_done == 1
    assert report.thumbs_done == 1
    assert (WorksStorage(tmp_path / "works").thumb_path(2)).exists()
    assert (WorksStorage(tmp_path / "works").original_dir(2) / "000_p0.jpg").exists()


async def test_worker_transcodes_ugoira_when_enabled(db, tmp_path):
    await _seed(db, 5, pages=1, type_="ugoira")
    downloader = FakeDownloader()
    calls: list[dict] = []

    async def fake_transcode(**kwargs) -> bool:
        calls.append(kwargs)
        kwargs["dest"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["dest"].write_bytes(b"mp4")
        return True

    worker = make_worker(db, tmp_path, downloader, transcode=fake_transcode)
    report = await worker.run_scope(DownloadScope(kind="all_missing"))

    assert report.status == "completed"
    assert len(calls) == 1
    assert (WorksStorage(tmp_path / "works").animation_path(5)).exists()
    async with db.session() as session:
        kinds = {
            job.kind for job in (await session.execute(select(downloads.DownloadJob))).scalars()
        }
    assert kinds == {"image", "ugoira_zip", "ugoira_mp4", "thumb"}


async def test_worker_marks_ugoira_mp4_skipped_without_ffmpeg(db, tmp_path):
    await _seed(db, 6, pages=1, type_="ugoira")
    downloader = FakeDownloader()

    async def no_transcode(**_kwargs) -> bool:
        return False

    worker = make_worker(db, tmp_path, downloader, transcode=no_transcode)
    report = await worker.run_scope(DownloadScope(kind="all_missing"))

    assert report.status in ("completed", "completed_with_failures")
    async with db.session() as session:
        jobs = (await session.execute(select(downloads.DownloadJob))).scalars().all()
        by_kind = {job.kind: job.status for job in jobs}
    assert by_kind["ugoira_mp4"] == "skipped"
    assert by_kind["ugoira_zip"] == "done"


async def test_worker_recovers_running_jobs(db, tmp_path):
    await _seed(db, 7, pages=1)
    downloader = FakeDownloader()
    worker = make_worker(db, tmp_path, downloader)
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        await downloads.enqueue_jobs(
            session, batch_id=batch_id, jobs=[(7, "image", "000_p0.jpg")], now=datetime.now(UTC)
        )
        await session.commit()
    async with db.session() as session:
        await downloads.claim_pending_jobs(session, limit=1)
        await session.commit()

    report = await worker.run_scope(DownloadScope(kind="all_missing"))
    assert report.pages_done == 1


async def test_worker_skips_thumbs_when_disabled(db, tmp_path):
    await _seed(db, 8, pages=1)
    downloader = FakeDownloader()
    worker = make_worker(db, tmp_path, downloader)
    worker.set_thumb_enabled(False)

    await worker.run_scope(DownloadScope(kind="all_missing"))

    assert not (WorksStorage(tmp_path / "works").thumb_path(8)).exists()
    async with db.session() as session:
        jobs = (await session.execute(select(downloads.DownloadJob))).scalars().all()
        statuses = {job.kind: job.status for job in jobs}
    assert statuses["thumb"] == "skipped"


async def test_worker_transcodes_ugoira_even_when_zip_job_runs_later(db, tmp_path):
    """The mp4 job must not depend on the zip job having run first."""
    await _seed(db, 11, pages=1, type_="ugoira")
    downloader = FakeDownloader()
    calls: list[dict] = []

    async def fake_transcode(**kwargs) -> bool:
        calls.append(kwargs)
        assert kwargs["zip_path"].exists(), "zip must be fetched on demand"
        kwargs["dest"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["dest"].write_bytes(b"mp4")
        return True

    worker = make_worker(db, tmp_path, downloader, transcode=fake_transcode)
    # only enqueue the mp4 job, simulating it being claimed before the zip job
    from pixiv_archive.media.storage import WorksStorage as _Storage

    storage = _Storage(tmp_path / "works")
    storage.work_dir(11).mkdir(parents=True, exist_ok=True)
    await worker._handle_ugoira_mp4(11, "animation.mp4", DownloadReport(batch_id=1))
    assert len(calls) == 1
    assert storage.animation_path(11).exists()


async def test_worker_retry_failed_resets_jobs(db, tmp_path):
    await _seed(db, 9, pages=1)
    downloader = FakeDownloader(fail_urls={"https://i.pximg.net/9_p0.jpg"})
    worker = make_worker(db, tmp_path, downloader)
    first = await worker.run_scope(DownloadScope(kind="all_missing"))
    assert first.failed >= 1

    retried = await worker.retry_failed()
    assert retried >= 1

    downloader.fail_urls.clear()
    second = await worker.run_scope(DownloadScope(kind="all_missing"))
    assert second.pages_done == 1
    assert second.failed == 0


async def test_worker_tracks_byte_size_and_flags(db, tmp_path):
    await _seed(db, 12, pages=1, type_="ugoira")
    downloader = FakeDownloader()

    async def fake_transcode(**kwargs) -> bool:
        kwargs["dest"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["dest"].write_bytes(b"mp4-bytes")
        return True

    worker = make_worker(db, tmp_path, downloader, transcode=fake_transcode)
    await worker.run_scope(DownloadScope(kind="all_missing"))

    storage = WorksStorage(tmp_path / "works")
    expected = (
        (storage.original_dir(12) / "000_p0.jpg").stat().st_size
        + storage.thumb_path(12).stat().st_size
        + (storage.work_dir(12) / "source.zip").stat().st_size
        + storage.animation_path(12).stat().st_size
    )
    async with db.session() as session:
        illust = (await session.execute(select(Illust))).scalar_one()
    assert illust.byte_size == expected
    assert illust.thumb_ready is True
    assert illust.animation_ready is True


async def test_worker_ignores_repeat_download_for_byte_size(db, tmp_path):
    await _seed(db, 13, pages=1)
    downloader = FakeDownloader()
    worker = make_worker(db, tmp_path, downloader)
    await worker.run_scope(DownloadScope(kind="all_missing"))
    async with db.session() as session:
        first = (await session.execute(select(Illust))).scalar_one().byte_size

    await worker.run_scope(DownloadScope(kind="all_missing"))
    async with db.session() as session:
        second = (await session.execute(select(Illust))).scalar_one().byte_size
    assert second == first


async def test_worker_marks_page_failed_and_keeps_thumb_flag_false(db, tmp_path):
    await _seed(db, 14, pages=1)
    downloader = FakeDownloader(fail_urls={"https://i.pximg.net/14_p0.jpg"})
    worker = make_worker(db, tmp_path, downloader)
    await worker.run_scope(DownloadScope(kind="all_missing"))
    async with db.session() as session:
        illust = (await session.execute(select(Illust))).scalar_one()
    assert illust.byte_size == 0
    assert illust.thumb_ready is False
