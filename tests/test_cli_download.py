import pytest
from sqlalchemy import select

from fakes import FakeDownloader
from pixiv_archive.cli import build_parser, run_download
from pixiv_archive.config import Settings
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust, IllustPage
from pixiv_archive.db.repo import downloads
from pixiv_archive.download.worker import DownloadReport, DownloadWorker, DownloadWorkerConfig
from pixiv_archive.media.storage import WorksStorage


def test_build_parser_download_defaults():
    args = build_parser().parse_args(["download"])
    assert args.command == "download"
    assert args.scope == "all-missing"
    assert args.author is None
    assert args.pids is None
    assert args.limit is None


def test_build_parser_download_options():
    args = build_parser().parse_args(
        ["download", "--scope", "author", "--author", "42", "--limit", "5", "--no-thumbs"]
    )
    assert args.scope == "author"
    assert args.author == 42
    assert args.limit == 5
    assert args.no_thumbs is True


def test_build_parser_download_rejects_unknown_scope():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["download", "--scope", "nope"])


def _settings(monkeypatch, tmp_path) -> Settings:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PIXIV_REFRESH_TOKEN", "tok")
    monkeypatch.setenv("PIXIV_USER_ID", "1")
    monkeypatch.setenv("API_MIN_INTERVAL_MS", "0")
    return Settings(_env_file=None)


async def _seed(db) -> None:
    async with db.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=1, title="t", author_id=1, page_count=1))
        await session.commit()
    async with db.session() as session:
        session.add(
            IllustPage(pid=1, page_index=0, original_url="https://i.pximg.net/1_p0.jpg", ext=".jpg")
        )
        session.add(Bookmark(pid=1, restrict="public", rank=0, state="active"))
        await session.commit()


def _fake_worker_context(settings, downloader):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _cm():
        db = Database(settings.db_path)
        worker = DownloadWorker(
            db=db,
            storage=WorksStorage(settings.works_dir),
            downloader=downloader,
            config=DownloadWorkerConfig(concurrency=2),
        )
        try:
            yield worker
        finally:
            await db.dispose()

    return _cm()


async def test_run_download_with_fakes(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path)
    db = Database(settings.db_path)
    await db.create_all()
    await _seed(db)
    await db.dispose()

    fake_downloader = FakeDownloader()
    import pixiv_archive.cli as cli

    monkeypatch.setattr(
        cli, "open_download_worker", lambda s: _fake_worker_context(s, fake_downloader)
    )

    exit_code = await run_download(["download"], settings=settings)
    assert exit_code == 0

    db = Database(settings.db_path)
    async with db.session() as session:
        job = (await session.execute(select(downloads.DownloadJob))).scalars().first()
        assert job is not None
        counts = await downloads.count_jobs_by_status(session, job.batch_id)
    await db.dispose()
    assert counts.get("done", 0) >= 1
    # the original is fetched by the image job; the thumbnail job may re-use it
    assert "https://i.pximg.net/1_p0.jpg" in fake_downloader.urls
    assert len(fake_downloader.urls) <= 2


def _stub_context(worker):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _cm():
        yield worker

    return _cm()


async def test_run_download_reports_report(monkeypatch, tmp_path, capsys):
    settings = _settings(monkeypatch, tmp_path)

    class StubWorker:
        async def run_scope(self, scope) -> DownloadReport:
            return DownloadReport(batch_id=1, pages_done=1, thumbs_done=1)

        def set_thumb_enabled(self, enabled: bool) -> None:
            return None

        async def retry_failed(self) -> int:
            return 0

    import pixiv_archive.cli as cli

    monkeypatch.setattr(cli, "open_download_worker", lambda s: _stub_context(StubWorker()))
    exit_code = await run_download(["download"], settings=settings)
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "download" in captured.out


async def test_run_download_retry_failed_flag(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path)
    calls: list[str] = []

    class StubWorker:
        async def run_scope(self, scope) -> DownloadReport:
            return DownloadReport(batch_id=1)

        def set_thumb_enabled(self, enabled: bool) -> None:
            return None

        async def retry_failed(self) -> int:
            calls.append("retry")
            return 2

    import pixiv_archive.cli as cli

    monkeypatch.setattr(cli, "open_download_worker", lambda s: _stub_context(StubWorker()))
    await run_download(["download", "--retry-failed"], settings=settings)
    assert calls == ["retry"]
