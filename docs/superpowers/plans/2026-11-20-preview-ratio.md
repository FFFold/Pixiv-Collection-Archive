# 封面按原图比例（medium 预览 + 一次性重抓）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让默认首页封面使用 pixiv `medium`（保留原图比例）而不是 `square_medium`（1:1 裁剪），并提供可中断、可续跑的一次性存量重抓。

**Architecture:** 新增 `media/preview.py` 统一 URL 选择与占位符判定；`preview_state` 增加取值 `stale` 表示「有封面但待按新比例重抓」，作为 DB 内的队列，同步补拉不碰它；`maintenance/preview_refresh.py` 批量覆盖下载（原子写、失败保留旧图）；CLI/Web/前端各接一个入口。

**Tech Stack:** Python 3.12（uv、FastAPI、SQLAlchemy async、Pillow）、React 19 + Vite + Tailwind 4。

**Spec:** `docs/superpowers/specs/2026-11-20-preview-ratio-design.md`

## Global Constraints

- 不新增数据库列、不新增 Alembic 迁移；`stale` 只是 `preview_state`（`String(16)`）的新取值。
- 所有写入必须走 `atomic_write_bytes`；失败路径绝不删除或截断已有 `preview.jpg`。
- 同步补拉队列（`get_preview_backlog`）不得包含 `stale`；`count_previews_missing` 只统计 `pending`/`failed`。
- `resolve_thumb` 优先级不变（`thumb.webp` → `preview.jpg`）；`thumb_ready=1` 的作品不参与重抓。
- 前端 UI 文案保持中文；任何前端改动后执行 `npm run build` 并提交 `src/pixiv_archive/web/static/`。
- CI 顺序：`uv run ruff check src tests` → `uv run ruff format --check src tests` → `uv run mypy` → `uv run pytest -q`。
- 单次重抓的图片请求并发由 `ImageDownloader` 的 `IMAGE_CONCURRENCY` 信号量控制，不额外加并发。

## Review Focus

- 远程封面 404 / 返回 HTML / 返回 `limit_*` 占位图时，旧 `preview.jpg` 必须原样保留（Task 3）。
- 重抓中断后剩余的 `stale` 行不得被下一轮增量同步标成 `ready`（Task 2、Task 3）。
- `thumb_ready=1` 的作品不得进入重抓队列（Task 2、Task 3）。
- 同一作品连续失败 5 次后停止请求、计入 `skipped`，`--restart` 才能重来（Task 3、Task 4）。
- 统计口径：`previews_ready + previews_missing + previews_stale == total_illusts`（Task 5）。

---

### Task 1: 预览 URL 优先级与占位符判定

**Files:**
- Create: `src/pixiv_archive/media/preview.py`
- Modify: `src/pixiv_archive/pixiv/models.py:61-63`
- Modify: `src/pixiv_archive/sync/orchestrator.py:460-469`
- Test: `tests/test_media.py`（新增用例；该文件已存在且导入 `media` 包）

**Interfaces:**
- Produces:
  - `PLACEHOLDER_MARKER: str = "s.pximg.net/common/images/limit_"`
  - `is_placeholder_url(url: str) -> bool`
  - `preview_url_from_meta(meta_json: str | None) -> str | None` —— 解析 `{"image_urls": {...}}`，优先 `medium`，退化 `square_medium`；`meta_json` 为空/非法/无 URL 时返回 `None`
  - `Illust.preview_url` → 同样优先 `medium`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_media.py 末尾追加
import json as _json

from pixiv_archive.media.preview import is_placeholder_url, preview_url_from_meta
from pixiv_archive.pixiv.models import Illust as PixivIllust


def test_preview_url_prefers_medium_over_square():
    meta = _json.dumps(
        {"image_urls": {"medium": "https://i.pximg.net/m.jpg", "square_medium": "https://i.pximg.net/s.jpg"}}
    )
    assert preview_url_from_meta(meta) == "https://i.pximg.net/m.jpg"
    illust = PixivIllust.model_validate(
        {
            "id": 1,
            "title": "t",
            "user": {"id": 1, "name": "a"},
            "image_urls": {"medium": "https://i.pximg.net/m.jpg", "square_medium": "https://i.pximg.net/s.jpg"},
        }
    )
    assert illust.preview_url == "https://i.pximg.net/m.jpg"


def test_preview_url_falls_back_and_handles_bad_meta():
    assert preview_url_from_meta(_json.dumps({"image_urls": {"square_medium": "s"}})) == "s"
    assert preview_url_from_meta(None) is None
    assert preview_url_from_meta("not-json") is None
    assert preview_url_from_meta(_json.dumps({"image_urls": {}})) is None


def test_placeholder_url_detection():
    assert is_placeholder_url("https://s.pximg.net/common/images/limit_unknown_360.png")
    assert not is_placeholder_url("https://i.pximg.net/c/540x540_70/x_master1200.jpg")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_media.py -q -k preview_url`
Expected: FAIL with `ModuleNotFoundError: pixiv_archive.media.preview`

- [ ] **Step 3: 实现 `media/preview.py` 并改两处优先级**

```python
# src/pixiv_archive/media/preview.py
import json

PLACEHOLDER_MARKER = "s.pximg.net/common/images/limit_"


def is_placeholder_url(url: str) -> bool:
    return PLACEHOLDER_MARKER in url


def preview_url_from_meta(meta_json: str | None) -> str | None:
    if not meta_json:
        return None
    try:
        payload = json.loads(meta_json)
    except ValueError:
        return None
    urls = payload.get("image_urls") or {}
    return urls.get("medium") or urls.get("square_medium")
```

- `pixiv/models.py` 的 `Illust.preview_url` 改成 `medium` → `square_medium`。
- `sync/orchestrator.py` 的 `_preview_url` 改为 `return preview_url_from_meta(meta_json)`（保留静态方法名以免改动调用点），从 `media/preview.py` 导入；删除现已无用的 `json`? **不要删**：`orchestrator.py` 仍用 `json.dumps`。

- [ ] **Step 4: 运行相关测试**

Run: `uv run pytest tests/test_media.py tests/test_sync_incremental.py tests/test_sync_full.py -q`
Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add src/pixiv_archive/media/preview.py src/pixiv_archive/pixiv/models.py src/pixiv_archive/sync/orchestrator.py tests/test_media.py
git commit -m "feat: prefer medium preview url and add placeholder guard"
```

---

### Task 2: `stale` 状态与仓库层队列

**Files:**
- Modify: `src/pixiv_archive/db/repo/illusts.py:152-236`
- Test: `tests/test_repo_preview_state.py`

**Interfaces:**
- Consumes: Task 1 无依赖。
- Produces:
  - `mark_previews_stale(session, *, all_active: bool) -> int`
  - `get_stale_preview_pids(session, *, max_attempts: int) -> list[int]`
  - `count_previews_stale(session) -> int`
  - `count_previews_stale_exhausted(session, *, max_attempts: int) -> int`
  - `record_refresh_failure(session, pid: int, *, error: str) -> None`
  - `get_preview_backlog` 语义改为 `preview_state IN ('pending', 'failed')`
  - `count_previews_missing` 语义改为 `preview_state IN ('pending', 'failed')`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_repo_preview_state.py 追加（_seed 增加 thumb_ready 参数）
async def test_preview_backlog_ignores_stale_rows(db):
    await _seed(db, 1, preview_state="stale")
    await _seed(db, 2, preview_state="pending")
    async with db.session() as session:
        assert await illusts.get_preview_backlog(session, max_attempts=5) == [2]
        assert await illusts.count_previews_missing(session) == 1
        assert await illusts.count_previews_stale(session) == 1


async def test_mark_previews_stale_marks_only_undownloaded_active(db):
    await _seed(db, 1, preview_state="ready", thumb_ready=False)
    await _seed(db, 2, preview_state="ready", thumb_ready=True)
    await _seed(db, 3, state="deleted", thumb_ready=False)
    async with db.session() as session:
        assert await illusts.mark_previews_stale(session, all_active=True) == 1
        await session.commit()
        row = await session.get(Illust, 1)
    assert (row.preview_state, row.preview_attempts, row.preview_error) == ("stale", 0, None)


async def test_stale_rows_with_thumb_become_ready_again(db):
    await _seed(db, 1, preview_state="stale", thumb_ready=True)
    await _seed(db, 2, preview_state="stale", thumb_ready=False)
    async with db.session() as session:
        assert await illusts.mark_previews_stale(session, all_active=False) == 1
        await session.commit()
        fixed = await session.get(Illust, 1)
        kept = await session.get(Illust, 2)
    assert fixed.preview_state == "ready"
    assert kept.preview_state == "stale"


async def test_refresh_failure_keeps_stale_and_counts_exhausted(db):
    await _seed(db, 1, preview_state="stale", preview_attempts=4)
    async with db.session() as session:
        await illusts.record_refresh_failure(session, 1, error="http 404")
        await session.commit()
        row = await session.get(Illust, 1)
    assert (row.preview_state, row.preview_attempts, row.preview_error) == ("stale", 5, "http 404")
    async with db.session() as session:
        assert await illusts.get_stale_preview_pids(session, max_attempts=5) == []
        assert await illusts.count_previews_stale_exhausted(session, max_attempts=5) == 1
```

同时给 `_seed` 增加 `thumb_ready=False` 关键字参数并传给 `Illust(...)`；既有用例不受影响。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_repo_preview_state.py -q`
Expected: FAIL with `AttributeError: module ... has no attribute 'mark_previews_stale'`

- [ ] **Step 3: 实现仓库函数**

- `get_preview_backlog`：`where(...Illust.preview_state.in_(("pending", "failed")), Illust.preview_attempts < max_attempts)`。
- `count_previews_missing`：`where(Illust.state == "active", Illust.preview_state.in_(("pending", "failed")))`。
- `mark_previews_stale`：
  - `all_active=True`：`update(Illust).where(Illust.state == "active", Illust.thumb_ready.is_(False)).values(preview_state="stale", preview_attempts=0, preview_error=None)`
  - `all_active=False`：`update(Illust).where(Illust.preview_state == "stale", or_(Illust.state != "active", Illust.thumb_ready.is_(True))).values(preview_state="ready", preview_error=None)`
  - 两者都用 `CursorResult.rowcount` 返回受影响行数。
- `get_stale_preview_pids`：`state='active' AND preview_state='stale' AND preview_attempts < max_attempts ORDER BY pid`。
- `count_previews_stale`：`state='active' AND preview_state='stale'`。
- `count_previews_stale_exhausted`：`state='active' AND preview_state='stale' AND preview_attempts >= max_attempts`。
- `record_refresh_failure`：`update(Illust).where(pid == pid).values(preview_attempts=Illust.preview_attempts + 1, preview_error=error[:500])`（不改 `preview_state`）。

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/test_repo_preview_state.py tests/test_sync_incremental.py tests/test_sync_full.py -q`
Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add src/pixiv_archive/db/repo/illusts.py tests/test_repo_preview_state.py
git commit -m "feat: add stale preview state and queue helpers"
```

---

### Task 3: `PreviewRefresher` 与工厂

**Files:**
- Create: `src/pixiv_archive/maintenance/preview_refresh.py`
- Modify: `src/pixiv_archive/sync/factory.py:99-122`（在 `open_download_worker` 前插入新工厂）
- Test: `tests/test_preview_refresh.py`（新建）

**Interfaces:**
- Consumes: `illusts.mark_previews_stale` / `get_stale_preview_pids` / `count_previews_stale` / `count_previews_stale_exhausted` / `record_refresh_failure` / `mark_previews_ready`；`preview_url_from_meta` / `is_placeholder_url`；`WorksStorage.preview_path`；`atomic_write_bytes`；`is_valid_image`。
- Produces:
  - `REFRESH_BATCH: int = 50`
  - `@dataclass RefreshReport: total: int; fetched: int; failed: int; remaining: int; skipped: int; resumed: bool`
  - `class PreviewRefresher: __init__(self, *, db: Database, storage: WorksStorage, downloader: ImageDownloader) -> None`；`async def run(self, *, restart: bool = False, on_progress: ProgressCallback | None = None) -> RefreshReport`（`ProgressCallback` 为 `Callable[[str, int, int, str], None]`，签名与 `sync/orchestrator.py` 一致）
  - `@asynccontextmanager open_preview_refresher(settings: Settings) -> AsyncIterator[PreviewRefresher]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_preview_refresh.py
import json

import pytest

from fakes import FakeDownloader
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Illust
from pixiv_archive.maintenance.preview_refresh import PreviewRefresher
from pixiv_archive.media.storage import WorksStorage

MEDIUM = "https://i.pximg.net/c/540x540_70/1_p0_master1200.jpg"
SQUARE = "https://i.pximg.net/c/540x540_10_webp/1_p0_square1200.jpg"


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / "refresh.db")
    await db.create_all()
    storage = WorksStorage(tmp_path / "works")
    yield db, storage
    await db.dispose()


async def _seed(db, storage, pid, *, thumb_ready=False, meta_urls=None, preview=b"old-square"):
    storage.work_dir(pid).mkdir(parents=True, exist_ok=True)
    if preview is not None:
        storage.preview_path(pid).write_bytes(preview)
    meta = json.dumps({"image_urls": meta_urls or {"medium": MEDIUM, "square_medium": SQUARE}})
    async with db.session() as session:
        if await session.get(Author, 1) is None:
            session.add(Author(id=1, name="a"))
        session.add(
            Illust(pid=pid, title="t", author_id=1, state="active",
                   thumb_ready=thumb_ready, meta_json=meta)
        )
        await session.commit()


async def test_refresh_overwrites_and_marks_ready(env):
    db, storage = env
    await _seed(db, storage, 1)
    downloader = FakeDownloader()
    report = await PreviewRefresher(db=db, storage=storage, downloader=downloader).run()
    assert (report.total, report.fetched, report.failed, report.remaining) == (1, 1, 0, 0)
    assert downloader.urls == [MEDIUM]
    assert storage.preview_path(1).read_bytes() != b"old-square"


async def test_failed_fetch_keeps_old_preview_and_records_error(env):
    db, storage = env
    await _seed(db, storage, 1)
    downloader = FakeDownloader(fail_urls={MEDIUM})
    report = await PreviewRefresher(db=db, storage=storage, downloader=downloader).run()
    assert (report.fetched, report.failed, report.remaining) == (0, 1, 1)
    assert storage.preview_path(1).read_bytes() == b"old-square"
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert (row.preview_state, row.preview_attempts, row.preview_error) == ("stale", 1, "fetch failed")


async def test_placeholder_and_corrupt_payloads_never_overwrite(env):
    db, storage = env
    await _seed(db, storage, 1, meta_urls={"medium": "https://s.pximg.net/common/images/limit_unknown_360.png"})
    downloader = FakeDownloader()
    report = await PreviewRefresher(db=db, storage=storage, downloader=downloader).run()
    assert downloader.urls == []
    assert report.failed == 1
    assert storage.preview_path(1).read_bytes() == b"old-square"


async def test_thumb_ready_works_are_not_refreshed(env):
    db, storage = env
    await _seed(db, storage, 1, thumb_ready=True)
    downloader = FakeDownloader()
    report = await PreviewRefresher(db=db, storage=storage, downloader=downloader).run()
    assert report.total == 0 and downloader.urls == []
    assert storage.preview_path(1).read_bytes() == b"old-square"


async def test_resume_only_fetches_remaining_stale(env):
    db, storage = env
    await _seed(db, storage, 1, preview=None)
    await _seed(db, storage, 2, preview=None)
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update().where(Illust.pid == 1).values(preview_state="ready")
        )
        await session.execute(
            Illust.__table__.update().where(Illust.pid == 2).values(preview_state="stale")
        )
        await session.commit()
    downloader = FakeDownloader()
    report = await PreviewRefresher(db=db, storage=storage, downloader=downloader).run()
    assert report.resumed is True
    assert downloader.urls == [MEDIUM]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_preview_refresh.py -q`
Expected: FAIL with `ModuleNotFoundError: pixiv_archive.maintenance.preview_refresh`

- [ ] **Step 3: 实现 `maintenance/preview_refresh.py`**

关键点（其余按常规写法）：

- `run()`：`stale_now = count_previews_stale()`；`resumed = stale_now > 0 and not restart`；若 `restart or stale_now == 0` 则 `mark_previews_stale(all_active=True)` 并提交；随后 `mark_previews_stale(all_active=False)` 提交。
- `total = count_previews_stale()`（标记之后）。
- 循环：`pids = await get_stale_preview_pids(max_attempts=5)`；取前 `REFRESH_BATCH`；`asyncio.gather(*(self._refresh_one(pid) ...), return_exceptions=True)`；成功列表 → `mark_previews_ready`，失败列表 → `record_refresh_failure`；`commit`；`on_progress("refresh-previews", done, total, f"重抓封面 {done}/{total}")`；`done += len(batch)`。
- `_refresh_one(pid)`：读 `meta_json`（在循环前用 `get_meta_json_map` 批量取），`preview_url_from_meta` 为 `None` → `"no preview url"`；`is_placeholder_url` → `"placeholder url"`（不请求）；`fetch_bytes` 为 `None` → `"fetch failed"`；`is_valid_image` 失败 → `"invalid image data"`；`atomic_write_bytes(storage.preview_path(pid), data)`；异常返回 `f"{type(exc).__name__}: {exc}"`。
- 退出条件：`get_stale_preview_pids` 返回空（含 attempts 用尽）。
- 报告：`remaining = count_previews_stale()`，`skipped = count_previews_stale_exhausted(max_attempts=5)`。
- 工厂 `open_preview_refresher(settings)`：`_ensure_schema` → `Database(settings.db_path)` → `httpx.AsyncClient(proxy=settings.pixiv_proxy, timeout=60.0)` → `ImageDownloader(client, mirror=settings.pixiv_image_mirror, concurrency=settings.image_concurrency)` → yield `PreviewRefresher(...)`，finally 关闭 client 与 db。

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/test_preview_refresh.py -q`
Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add src/pixiv_archive/maintenance/preview_refresh.py src/pixiv_archive/sync/factory.py tests/test_preview_refresh.py
git commit -m "feat: add preview refresher that overwrites stale covers"
```

---

### Task 4: CLI `maintain refresh-previews`

**Files:**
- Modify: `src/pixiv_archive/cli.py:52-63`（parser choices）、`cli.py:115-163`（`run_maintain`）
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `open_preview_refresher`、`RefreshReport`。
- Produces: `maintain refresh-previews [--restart]`，输出 `封面重抓：总数 N，成功 X，失败 Y，剩余 Z（跳过 S，续跑|新开一轮）`，退出码 0。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cli.py 追加
def test_build_parser_maintain_refresh_previews():
    args = build_parser().parse_args(["maintain", "refresh-previews", "--restart"])
    assert args.action == "refresh-previews"
    assert args.restart is True


async def test_run_maintain_refresh_previews(monkeypatch, tmp_path, capsys):
    from contextlib import asynccontextmanager

    import pixiv_archive.cli as cli_module
    from pixiv_archive.maintenance.preview_refresh import RefreshReport

    @asynccontextmanager
    async def fake_open(settings):
        class Fake:
            async def run(self, *, restart=False, on_progress=None):
                assert restart is True
                return RefreshReport(total=2, fetched=1, failed=1, remaining=1, skipped=0, resumed=False)

        yield Fake()

    monkeypatch.setattr(cli_module, "open_preview_refresher", fake_open)
    monkeypatch.setattr(cli_module, "_ensure_schema", _noop_async)
    exit_code = await cli_module.run_maintain(
        ["maintain", "refresh-previews", "--restart"], _settings(monkeypatch, tmp_path)
    )
    assert exit_code == 0
    assert "总数 2" in capsys.readouterr().out
```

`_noop_async` 与 `open_preview_refresher` 用模块级导入以便 monkeypatch：在 `cli.py` 顶部 `from pixiv_archive.sync.factory import open_download_worker, open_preview_refresher, open_sync_service`（`_ensure_schema` 目前是函数内导入，测试里改为 monkeypatch `pixiv_archive.sync.factory._ensure_schema` 并通过 `cli` 内导入生效——最简单是在 `run_maintain` 内 `from pixiv_archive.sync.factory import _ensure_schema` 保持不变，测试把 `pixiv_archive.sync.factory._ensure_schema` 替换为 async no-op）。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_cli.py -q -k refresh_previews`
Expected: FAIL（argparse 报 `invalid choice: 'refresh-previews'`）

- [ ] **Step 3: 实现**

- `build_parser`：`choices` 增加 `"refresh-previews"`；`maintain.add_argument("--restart", action="store_true", help="...")`。
- `run_maintain`：在 `repair-previews` 分支之后加 `refresh-previews` 分支，使用 `open_preview_refresher(settings)`，打印报告，`return 0`。

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/test_cli.py -q && uv run pytest tests/test_preview_refresh.py -q`
Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add src/pixiv_archive/cli.py tests/test_cli.py
git commit -m "feat: add maintain refresh-previews command"
```

---

### Task 5: Web 端点与统计字段

**Files:**
- Modify: `src/pixiv_archive/web/routers/maintenance.py`（新增端点）
- Modify: `src/pixiv_archive/web/routers/stats.py:59-65,120-140`
- Modify: `src/pixiv_archive/web/schemas.py:136-160`（`StatsOut` 增加 `previews_stale`）
- Modify: `src/pixiv_archive/web/routers/illust.py`? 不需要。
- Test: `tests/test_web_maintenance.py`、`tests/test_web_routers_stats_export.py`

**Interfaces:**
- Consumes: `open_preview_refresher`、`RefreshReport`、`illusts_repo.count_previews_stale`。
- Produces:
  - `POST /api/maintenance/refresh-previews`，请求体 `{"restart": false}`（可选），返回 `202 TaskOut`，任务 detail 为 `{total, fetched, failed, remaining, skipped, resumed}`。
  - `StatsOut.previews_stale: int`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_web_maintenance.py 追加
async def test_refresh_previews_task(client, monkeypatch):
    from contextlib import asynccontextmanager

    import pixiv_archive.web.routers.maintenance as maintenance_module
    from pixiv_archive.maintenance.preview_refresh import RefreshReport

    class FakeRefresher:
        async def run(self, *, restart=False, on_progress=None):
            assert restart is True
            return RefreshReport(total=4, fetched=3, failed=1, remaining=1, skipped=0, resumed=False)

    @asynccontextmanager
    async def fake_open(settings):
        yield FakeRefresher()

    monkeypatch.setattr(maintenance_module, "open_preview_refresher", fake_open)
    response = await client.post("/api/maintenance/refresh-previews", json={"restart": True})
    assert response.status_code == 202
    record = await _wait(client)
    assert record["status"] == "completed"
    assert record["detail"]["remaining"] == 1
    assert record["detail"]["fetched"] == 3


async def test_refresh_previews_rejected_while_sync_runs(client):
    tasks = client._transport.app.state.tasks  # type: ignore[union-attr]

    async def job(context):
        await asyncio.sleep(0.2)
        return {}

    task_id = tasks.start("sync", job)
    response = await client.post("/api/maintenance/refresh-previews")
    assert response.status_code == 409
    await tasks.wait(task_id)
```

统计测试：在 `tests/test_web_routers_stats_export.py` 既有 stats 用例中补断言：插入一条 `preview_state='stale'` 的行后 `previews_stale == 1`，且 `previews_missing` 不变。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_maintenance.py -q -k refresh_previews`
Expected: FAIL 404

- [ ] **Step 3: 实现端点与统计**

- `maintenance.py`：`from pixiv_archive.sync.factory import open_preview_refresher`；新增 `RefreshRequest(BaseModel): restart: bool = False`；`@router.post("/refresh-previews", status_code=202, response_model=TaskOut)`，先检查 `sync` 运行中 → 409（文案复用「同步任务正在运行，请稍后再试」），任务内 `context.progress(...)` 透传、`asdict(report)` 返回。
- `stats.py`：`previews_missing = await illusts_repo.count_previews_missing(session)`（口径已变）、`previews_stale = await illusts_repo.count_previews_stale(session)`。
- `schemas.py` `StatsOut` 增加 `previews_stale: int`。

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/test_web_maintenance.py tests/test_web_routers_stats_export.py -q`
Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add src/pixiv_archive/web/routers/maintenance.py src/pixiv_archive/web/routers/stats.py src/pixiv_archive/web/schemas.py tests/test_web_maintenance.py tests/test_web_routers_stats_export.py
git commit -m "feat: expose refresh-previews endpoint and stale preview stats"
```

---

### Task 6: 前端入口、任务文案与图片尺寸

**Files:**
- Modify: `frontend/src/api/types.ts`、`frontend/src/api/mutations.ts`
- Modify: `frontend/src/components/MaintenanceCard.tsx`、`frontend/src/components/TaskPanel.tsx`
- Modify: `frontend/src/pages/Stats.tsx`、`frontend/src/components/GalleryCard.tsx`
- Test: `frontend/src/components/MaintenanceCard.test.tsx`（新建）、`frontend/src/components/GalleryCard.test.tsx`

**Interfaces:**
- Consumes: `POST /api/maintenance/refresh-previews`、`Stats.previews_stale`、`GalleryItem.width/height`。
- Produces:
  - `useRefreshPreviews()`：`apiFetch<TaskOut>("/api/maintenance/refresh-previews", { method: "POST", body: { restart: false } })`
  - `RefreshPreviewsResult` 类型：`total/fetched/failed/remaining/skipped/resumed`
  - `Stats` 类型新增 `previews_stale: number`

- [ ] **Step 1: 写失败测试**

```tsx
// frontend/src/components/MaintenanceCard.test.tsx（沿用现有测试的 mock 方式）
it("确认后提交重抓封面任务", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  // render + click 「重抓封面（改原图比例）」
  // 断言 fetch 收到 POST /api/maintenance/refresh-previews
});
```

`GalleryCard.test.tsx` 增加：`expect(img).toHaveAttribute("width", "900")`（用 fixture 的 width/height）。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend; npm test -- src/components/MaintenanceCard.test.tsx src/components/GalleryCard.test.tsx`
Expected: FAIL（按钮不存在 / 无 width 属性）

- [ ] **Step 3: 实现**

- `types.ts`：`Stats` 加 `previews_stale`；新增 `RefreshPreviewsResult`（若无用可省略，TaskOut detail 为 `Record<string, number>` 时按现有类型处理）。
- `mutations.ts`：`useRefreshPreviews()`，成功后 invalidate `tasks`、`stats`。
- `MaintenanceCard.tsx`：按钮「重抓封面（改原图比例）」，`onClick` 先 `window.confirm("将重新下载所有未下载作品的封面（约 30–60MB，可中断续跑）。继续？")`；错误提示条件加入 `refresh.isError`。
- `TaskPanel.tsx`：维护分支增加 `"remaining" in u && "resumed" in u` → `重抓封面 ${fetched}/${total} · 失败 ${failed} · 剩余 ${remaining}`。
- `Stats.tsx`：新增「待重抓封面」行，展示 `previews_stale`。
- `GalleryCard.tsx`：`<img>` 加 `width={item.width} height={item.height}`。

- [ ] **Step 4: 运行测试与构建**

Run: `cd frontend; npm run lint; npm run typecheck; npm test; npm run build`
Expected: 全 PASS，`src/pixiv_archive/web/static/` 产物更新

- [ ] **Step 5: 提交**

```bash
git add frontend/src src/pixiv_archive/web/static
git commit -m "feat(ui): add refresh-previews button, stale stats row and img dimensions"
```

---

### Task 7: 文档与整体验证

**Files:**
- Modify: `AGENTS.md`（Gotchas 段落）
- Modify: `docs/superpowers/specs/2026-11-20-preview-ratio-design.md`（状态改为「已实施」）
- Test: 全量 CI 命令

- [ ] **Step 1: 更新文档**

在 `AGENTS.md` 的迁移说明之后追加：`medium` 优先级、`stale` 状态语义、`maintain refresh-previews [--restart]`、`previews_stale` 统计口径、旧版本降级会收敛的说明。

- [ ] **Step 2: 运行后向与前端全量验证**

```powershell
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
uv run pytest -q
cd frontend; npm run lint; npm run typecheck; npm test
```
Expected: 全部通过，无新增告警

- [ ] **Step 3: 提交**

```bash
git add AGENTS.md docs/superpowers/specs/2026-11-20-preview-ratio-design.md
git commit -m "docs: document preview ratio refresh workflow"
```

---

## Self-Review

- 规格覆盖：§3 URL 优先级 → Task 1；§4 覆盖风险 → Task 1（占位符）+ Task 3（原子写/失败保留）；§5 队列与状态 → Task 2/3；§6.1 CLI → Task 4；§6.2 Web → Task 5；§6.3 统计 → Task 5；§6.4 前端 → Task 6；§9 升级说明 → Task 7。
- 类型一致性：`RefreshReport` 字段（`total/fetched/failed/remaining/skipped/resumed`）在 Task 3/4/5/6 一致。
- 未覆盖项：无已知缺口。
