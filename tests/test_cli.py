import pytest
from sqlalchemy import select

from fakes import FakeClient, FakeDownloader, make_illust, page
from pixiv_archive.cli import build_parser, run_sync
from pixiv_archive.config import Settings
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Illust
from pixiv_archive.db.repo import sync_runs
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.sync.factory import open_sync_service
from pixiv_archive.sync.orchestrator import MetadataSyncService


def test_build_parser_defaults():
    args = build_parser().parse_args(["sync"])
    assert args.command == "sync"
    assert args.mode == "incremental"
    assert args.max_pages is None
    assert args.no_previews is False


def test_build_parser_full_mode():
    args = build_parser().parse_args(
        ["sync", "--mode", "full", "--max-pages", "3", "--no-previews"]
    )
    assert args.mode == "full"
    assert args.max_pages == 3
    assert args.no_previews is True


def test_build_parser_rejects_unknown_mode():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["sync", "--mode", "whatever"])


def _settings(monkeypatch, tmp_path) -> Settings:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PIXIV_REFRESH_TOKEN", "tok")
    monkeypatch.setenv("PIXIV_USER_ID", "1")
    monkeypatch.setenv("API_MIN_INTERVAL_MS", "0")
    return Settings(_env_file=None)


async def test_open_sync_service_reopens_cleanly(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path)

    async with open_sync_service(settings) as service:
        assert service is not None
    assert settings.db_path.exists()

    async with open_sync_service(settings) as service:
        assert service is not None


def _fake_service_context(settings, fake_client, fake_downloader):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _cm():
        db = Database(settings.db_path)
        await db.create_all()
        service = MetadataSyncService(
            db=db,
            client=fake_client,
            storage=WorksStorage(settings.works_dir),
            downloader=fake_downloader,
            download_previews=settings.download_previews,
        )
        try:
            yield service
        finally:
            await db.dispose()

    return _cm()


async def test_run_sync_incremental_with_fakes(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path)
    fake_client = FakeClient(
        {"public": [page([make_illust(1), make_illust(2)], cursor=None)], "private": []}
    )
    fake_downloader = FakeDownloader()

    import pixiv_archive.cli as cli

    monkeypatch.setattr(
        cli, "open_sync_service", lambda s: _fake_service_context(s, fake_client, fake_downloader)
    )

    exit_code = await run_sync(["sync"], settings=settings)
    assert exit_code == 0

    db = Database(settings.db_path)
    async with db.session() as session:
        pids = (await session.execute(select(Illust.pid).order_by(Illust.pid))).scalars().all()
        run = (await session.execute(select(sync_runs.SyncRun))).scalar_one()
    await db.dispose()
    assert pids == [1, 2]
    assert run.status == "completed"
    assert run.new_count == 2
    assert fake_downloader.urls == [
        "https://i.pximg.net/1_sq.jpg",
        "https://i.pximg.net/2_sq.jpg",
    ]


async def test_run_sync_propagates_failures(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path)

    class ExplodingClient(FakeClient):
        async def list_bookmarks(self, restrict, *, max_bookmark_id=None):
            raise RuntimeError("upstream exploded")

    import pixiv_archive.cli as cli

    monkeypatch.setattr(
        cli,
        "open_sync_service",
        lambda s: _fake_service_context(s, ExplodingClient({}), FakeDownloader()),
    )
    with pytest.raises(RuntimeError):
        await run_sync(["sync"], settings=settings)


def test_build_parser_maintain_defaults():
    args = build_parser().parse_args(["maintain", "db-check"])
    assert args.command == "maintain"
    assert args.action == "db-check"
    assert args.yes is False


def test_build_parser_maintain_rejects_unknown_action():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["maintain", "nope"])


async def test_run_maintain_rebuild_stats(monkeypatch, tmp_path, capsys):
    from pixiv_archive.cli import run_maintain

    settings = _settings(monkeypatch, tmp_path)

    exit_code = await run_maintain(["maintain", "rebuild-stats"], settings=settings)
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "重建完成" in captured.out


async def test_run_maintain_repair_requires_yes(monkeypatch, tmp_path, capsys):
    from pixiv_archive.cli import run_maintain

    settings = _settings(monkeypatch, tmp_path)

    exit_code = await run_maintain(["maintain", "repair-download-state"], settings=settings)
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "预览" in captured.out
    assert "--yes" in captured.out
