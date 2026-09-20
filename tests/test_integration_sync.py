"""Live stage A sync against the real pixiv API.

Run with:
    uv run pytest tests/test_integration_sync.py -m integration -v -s
Requires PIXIV_REFRESH_TOKEN / PIXIV_USER_ID and network access (PIXIV_PROXY).
"""

import pytest

from pixiv_archive.config import Settings
from pixiv_archive.db.engine import Database
from pixiv_archive.db.repo import bookmarks, illusts
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.sync.factory import open_sync_service

pytestmark = pytest.mark.integration


async def test_live_incremental_sync_orders_bookmarks(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings(_env_file=None)
    settings.ensure_dirs()

    async with open_sync_service(settings) as service:
        result = await service.run_incremental(max_pages=2)

    assert result.status == "completed"
    assert result.pages_fetched == 3  # 2 public pages + 1 empty private page
    assert result.new_count == 60  # 2 pages x 30
    print(
        f"\nnew={result.new_count} previews={result.previews_fetched} pages={result.pages_fetched}"
    )

    db = Database(settings.db_path)
    async with db.session() as session:
        known = await illusts.get_known_pids(session)
        ranks = await bookmarks.get_rank_map(session)
    await db.dispose()

    assert len(known) == 60
    ordered = sorted(ranks, key=lambda pid: ranks[pid])
    assert len(set(ranks.values())) == 60  # ranks are unique
    assert all(ranks[a] < ranks[b] for a, b in zip(ordered, ordered[1:], strict=False))

    storage = WorksStorage(settings.works_dir)
    assert storage.preview_path(ordered[0]).exists()
    assert storage.meta_path(ordered[0]).exists()


async def test_live_second_incremental_stops_at_first_page(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings(_env_file=None)
    settings.ensure_dirs()

    async with open_sync_service(settings) as service:
        first = await service.run_incremental(max_pages=1)
        assert first.new_count == 30
        second = await service.run_incremental()

    assert second.new_count == 0
    # page 1 of public was fully known -> stop; private still queried once
    assert second.pages_fetched == 2
