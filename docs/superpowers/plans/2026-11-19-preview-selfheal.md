# 封面/动图元数据自愈实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让增量同步每轮自动补拉未就绪的封面与动图元数据，失败可重试、可观测、可手动修复，升级后无需重跑全量同步。

**Architecture:** 在 `illust` / `ugoira_meta` 上加显式状态列；同步的收尾阶段改为一个统一的「资产补拉队列」（查 DB → stat/下载 → 校验 → 写状态），新作品插入时默认 `pending` 因而同一轮即被覆盖。维护入口重置失败计数后立即跑一轮补拉，统计与任务详情暴露失败/待补数量。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 async / SQLite + Alembic / Pillow / React 19 + Vite + TanStack Query。

**Spec:** `docs/superpowers/specs/2026-11-19-preview-selfheal-design.md`

## Global Constraints

- Shell 为 PowerShell 7（`pwsh`），不是 Bash。
- 后端命令在仓库根目录执行：`uv run pytest -q`、`uv run ruff check src tests && uv run ruff format --check src tests`、`uv run mypy`。
- `ruff format` 是格式权威；mypy strict 只检查 `src/`。
- 前端在 `frontend/` 下执行：`npm test -- <file>`、`npm run typecheck`、`npm run build`；前端改动后必须重新构建并把 `src/pixiv_archive/web/static/` 的产物一起提交。
- UI 文案使用中文；重试上限固定为 5 次（`PREVIEW_ATTEMPTS_LIMIT = 5`、`UGOIRA_META_ATTEMPTS_LIMIT = 5`）。
- 迁移只加列、不回填；历史缺失封面由升级后的第一次增量同步自愈。
- 每个任务结束提交一次；提交信息使用 `feat:` / `test:` 前缀。

## Review Focus

1. 升级后第一次增量同步：已有 `preview.jpg` 的作品只做存在性检查，绝不重新下载（防止一次全库图片请求风暴）。
2. 永久 404 或元数据里没有预览 URL 的作品：最多重试 5 次后停在 `failed`，不得每 6 小时无限请求。
3. 单个目标抛异常或写盘失败：只影响该目标，不能中断整轮同步，也不能丢弃同批其他目标的成功。
4. `download_previews=False`（CLI `--no-previews` / `DOWNLOAD_PREVIEWS=false`）：跳过补拉，但 `previews_pending` 统计仍要正确。
5. 动图失败占位行（`zip_url` 为空）：不得被阶段 B 生成 zip/mp4 任务；重试成功后 `meta_attempts` 必须归零。

---

### Task 1: 迁移 0005 与模型状态列

**Files:**
- Create: `src/pixiv_archive/db/migrations/versions/0005_preview_state.py`
- Modify: `src/pixiv_archive/db/models.py:39-46`（`Illust`）、`:103-109`（`UgoiraMeta`）
- Modify: `tests/test_migrations.py`
- Modify: `AGENTS.md`（Gotchas：迁移 0005 与自愈行为）

**Interfaces:**
- Produces: `Illust.preview_state: str`（默认 `"pending"`）、`Illust.preview_attempts: int`（默认 `0`）、`Illust.preview_error: str | None`；`UgoiraMeta.meta_attempts: int`（默认 `0`）、`UgoiraMeta.meta_error: str | None`。

- [ ] **Step 1: 写失败的迁移测试**

在 `tests/test_migrations.py` 末尾追加（复用现有 subprocess 写法）：

```python
def test_migration_adds_preview_state_columns(tmp_path):
    db_file = tmp_path / "archive.db"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "DATA_DIR": str(tmp_path),
            "PIXIV_REFRESH_TOKEN": "tok",
            "PIXIV_USER_ID": "1",
        },
    )
    assert result.returncode == 0, result.stderr

    import sqlite3

    conn = sqlite3.connect(db_file)
    try:
        illust = {row[1] for row in conn.execute("PRAGMA table_info(illust)")}
        ugoira = {row[1] for row in conn.execute("PRAGMA table_info(ugoira_meta)")}
        default = conn.execute(
            "SELECT dflt_value FROM pragma_table_info('illust') WHERE name='preview_state'"
        ).fetchone()
    finally:
        conn.close()
    assert {"preview_state", "preview_attempts", "preview_error"} <= illust
    assert {"meta_attempts", "meta_error"} <= ugoira
    assert default is not None and "pending" in default[0]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_migrations.py::test_migration_adds_preview_state_columns -q`
Expected: FAIL（no such column / 集合断言失败）

- [ ] **Step 3: 实现模型列与迁移**

`models.py` 的 `Illust` 在 `thumb_ready` 后追加三列；`UgoiraMeta` 在 `frame_count` 后追加两列。`0005_preview_state.py` 的 `upgrade()` 用 `op.add_column` 加同样的列（`preview_state`/`meta_attempts` 等均 `nullable=False, server_default=...`，`preview_error`/`meta_error` 可空），`downgrade()` 反序删除。`revision = "0005"`、`down_revision = "0004"`。

同时更新 `AGENTS.md` 的 Gotchas：迁移 0005 只加列，历史缺失封面由升级后第一次增量同步自动补拉；`preview_state`/`meta_attempts` 是补拉队列的状态来源。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_migrations.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add src/pixiv_archive/db/models.py src/pixiv_archive/db/migrations/versions/0005_preview_state.py tests/test_migrations.py AGENTS.md
git commit -m "feat(db): add preview and ugoira metadata state columns"
```

---

### Task 2: 状态仓库原语

**Files:**
- Modify: `src/pixiv_archive/db/repo/illusts.py`
- Test: `tests/test_repo_preview_state.py`（新建）

**Interfaces:**
- Produces（全部在 `db/repo/illusts.py`）：
  - `async def get_preview_backlog(session, *, max_attempts: int) -> list[int]`
  - `async def get_meta_json_map(session, pids: list[int]) -> dict[int, str | None]`
  - `async def mark_previews_ready(session, pids: list[int]) -> int`
  - `async def mark_previews_pending(session, pids: list[int]) -> int`
  - `async def get_ready_preview_pids(session) -> list[int]`
  - `async def record_preview_failure(session, pid: int, *, error: str, max_attempts: int) -> None`
  - `async def count_previews_missing(session) -> int`
  - `async def reset_failed_previews(session) -> int`
  - `async def get_ugoira_meta_backlog(session, *, max_attempts: int) -> list[int]`
  - `async def count_ugoira_meta_missing(session) -> int`
  - `async def record_ugoira_meta_failure(session, pid: int, *, error: str) -> None`
- 修改 `upsert_illust`：插入值显式加 `"preview_state": "pending"`，冲突更新时排除 `preview_state`。
- 修改 `upsert_ugoira_meta`：插入与冲突更新都把 `meta_attempts=0`、`meta_error=None` 写入。

- [ ] **Step 1: 写失败的仓库测试**

```python
# tests/test_repo_preview_state.py
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


async def _seed(db, pid, *, state="active", type_="illust", preview_state="pending",
                preview_attempts=0, meta_json=None):
    async with db.session() as session:
        if await session.get(Author, 1) is None:
            session.add(Author(id=1, name="a"))
        session.add(Illust(pid=pid, title="t", author_id=1, type=type_, state=state,
                           preview_state=preview_state, preview_attempts=preview_attempts,
                           meta_json=meta_json))
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
        "https://x/1.zip", 3, 0, None,
    )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_repo_preview_state.py -q`
Expected: FAIL（`AttributeError: module ... has no attribute 'get_preview_backlog'`）

- [ ] **Step 3: 实现仓库函数**

`get_preview_backlog`：`select(Illust.pid).where(Illust.state == "active", Illust.preview_state != "ready", Illust.preview_attempts < max_attempts).order_by(Illust.pid)`。
`record_preview_failure`：一条 `update`，`preview_attempts = preview_attempts + 1`，`preview_error = error[:500]`，`preview_state` 用 `case((Illust.preview_attempts + 1 >= max_attempts, "failed"), else_="pending")`。
`mark_previews_ready` / `mark_previews_pending` / `get_meta_json_map`：按 500 个 pid 分块，避免 SQLite 参数上限；`mark_previews_pending` 同时把 `preview_attempts` 归零、`preview_error` 置空。
`get_ready_preview_pids`：`select(Illust.pid).where(Illust.state == "active", Illust.preview_state == "ready").order_by(Illust.pid)`（供手动修复核对文件是否仍存在）。
`reset_failed_previews`：`update(...).where(preview_state == "failed").values(preview_state="pending", preview_attempts=0, preview_error=None)`，返回 `rowcount or 0`。
`count_previews_missing`：`select(func.count()).where(Illust.state == "active", Illust.preview_state != "ready")`。
`get_ugoira_meta_backlog`：对 `UgoiraMeta` 做 outer join，条件为 `Illust.state == "active"`、`Illust.type == "ugoira"`、`(UgoiraMeta.pid.is_(None)) | (UgoiraMeta.zip_url == "") | (UgoiraMeta.frame_count == 0)`、`func.coalesce(UgoiraMeta.meta_attempts, 0) < max_attempts`，按 pid 排序。
`record_ugoira_meta_failure`：`insert(UgoiraMeta)` 的 `on_conflict_do_update` 只递增 `meta_attempts`、写 `meta_error`，不覆盖已存在的 `zip_url`/`frames_json`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_repo_preview_state.py tests/test_repo_illusts.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add src/pixiv_archive/db/repo/illusts.py tests/test_repo_preview_state.py
git commit -m "feat(db): add preview and ugoira retry state helpers"
```

---

### Task 3: 统一资产补拉队列接管同步收尾

**Files:**
- Modify: `src/pixiv_archive/sync/orchestrator.py:29-44`（`SyncResult`）、`:79-309`（两个 run）、`:331-392`（`_finalize`/`_fetch_previews`/ugoira）
- Test: `tests/test_sync_incremental.py`、`tests/test_sync_full.py`
- Test helper: `tests/fakes.py`（仅当需要）

**Interfaces:**
- Consumes: Task 2 的 `illusts.get_preview_backlog` / `get_meta_json_map` / `mark_previews_ready` / `mark_previews_pending` / `get_ready_preview_pids` / `record_preview_failure` / `count_previews_missing`。
- Produces:
  - `PREVIEW_ATTEMPTS_LIMIT = 5`、`UGOIRA_META_ATTEMPTS_LIMIT = 5`（orchestrator 模块级常量）
  - `@dataclass AssetRepairResult`，字段 `reset: int = 0`、`previews_fetched: int = 0`、`previews_failed: int = 0`、`previews_pending: int = 0`、`ugoira_fetched: int = 0`、`ugoira_failed: int = 0`
  - `async def MetadataSyncService.repair_assets(self, *, reset_failed: bool = False) -> AssetRepairResult`
  - `SyncResult.previews_pending: int = 0`
  - 私有 `_repair_previews(out)`、`_repair_ugoira_metadata(out)`、静态 `_preview_url(meta_json: str | None) -> str | None`

- [ ] **Step 1: 写失败的自愈测试**

在 `tests/test_sync_incremental.py` 追加（`PREVIEW_ATTEMPTS_LIMIT` 从 orchestrator 导入）：

```python
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
    payload = '{"image_urls": {"medium": "https://i/medium.jpg", "square_medium": "https://i/sq.jpg"}}'
    assert MetadataSyncService._preview_url(payload) == "https://i/sq.jpg"
    assert MetadataSyncService._preview_url('{"image_urls": {"medium": "https://i/medium.jpg"}}') == (
        "https://i/medium.jpg"
    )
    assert MetadataSyncService._preview_url(None) is None
```

此外修改两处既有测试：

- `test_incremental_skips_previews_when_disabled` 末尾补 `assert result.previews_pending == 1`（跳过下载不影响待补统计）。
- `test_sync_full.py::test_full_sync_backfills_missing_previews`：`storage.preview_path(1).unlink()` 之后补一条 `update(Illust).values(preview_state="pending")`（状态是队列的权威来源；手动修复会用 `repair_assets(reset_failed=True)` 核对磁盘并重新入队）。
- `tests/test_sync_full.py` 顶部相应补 `from sqlalchemy import update` 与 `from pixiv_archive.db.models import Illust`。

`tests/test_sync_incremental.py` 顶部补充 `from sqlalchemy import update` 与
`from pixiv_archive.sync.orchestrator import PREVIEW_ATTEMPTS_LIMIT`。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_sync_incremental.py -k "preview or previews" -q`
Expected: FAIL（第二轮 `d2.urls` 为空 / 无 `previews_pending`）

- [ ] **Step 3: 实现补拉队列**

1. 删除 `run_incremental` / `run_full` 里的 `preview_targets`、`ugoira_targets` 收集与 `_finalize(result, ...)` 调用；两处改为：

```python
repair = await self.repair_assets()
result.previews_fetched += repair.previews_fetched
result.previews_failed += repair.previews_failed
result.previews_pending = repair.previews_pending
result.ugoira_meta_fetched += repair.ugoira_fetched
result.failed_count += repair.ugoira_failed
```

2. `meta.json` 改为在每次 `upsert_illust` 成功后立即写（`self._storage.save_meta_json(illust.pid, illust.model_dump(mode="json", by_alias=True))`），放在现有的 per-work `try/except` 里；`_finalize` 因此删除。
3. `repair_assets`：`reset_failed=True` 时先把 `failed` 重置为 `pending` 并累加 `out.reset`；再用 `get_ready_preview_pids()` + `self._storage.has_preview(pid)` 找出「状态 ready 但文件已丢失」的 pid，`mark_previews_pending` 后同样累加 `out.reset`。随后 `download_previews` 为真时跑 `_repair_previews`，再跑 `_repair_ugoira_metadata`，最后用新 session 计算 `out.previews_pending = await illusts.count_previews_missing(session)`。
4. `_repair_previews`：
   - 一个 session 读 `get_preview_backlog(session, max_attempts=PREVIEW_ATTEMPTS_LIMIT)`；
   - 用 `self._storage.has_preview(pid)` 把存在的 pid 收集起来 → `mark_previews_ready` 并提交（计为修复，不计入 `previews_fetched`）；
   - 其余 pid 用 `get_meta_json_map` 取 `meta_json`，`_preview_url()` 解析 `image_urls.square_medium` → `image_urls.medium`；无 URL 记失败 `"no preview url"`；
   - 有 URL 的目标并发下载（每个目标独立 `try/except`），成功时 `atomic_write_bytes(self._storage.preview_path(pid), data)`，失败返回错误字符串；
   - 一个 session 里 `mark_previews_ready` 成功列表、逐条 `record_preview_failure` 失败列表，提交；`out.previews_fetched`/`out.previews_failed` 计数。
5. `_repair_ugoira_metadata`：读 `get_ugoira_meta_backlog`，逐个 `await self._client.get_ugoira_metadata(pid)`；成功写 `illusts.upsert_ugoira_meta`（现有逻辑），`except PixivError` 时 `record_ugoira_meta_failure(pid, error=str(exc))` 并 `ugoira_failed += 1`。

- [ ] **Step 4: 运行同步与全量测试确认通过**

Run: `uv run pytest tests/test_sync_incremental.py tests/test_sync_full.py -q`
Expected: PASS（含既有的 `test_incremental_counts_preview_failures`、`test_incremental_skips_previews_when_disabled`、`test_full_sync_backfills_missing_previews`）

- [ ] **Step 5: 提交**

```powershell
git add src/pixiv_archive/sync/orchestrator.py tests/test_sync_incremental.py tests/test_sync_full.py
git commit -m "feat(sync): repair missing previews and ugoira metadata every run"
```

---

### Task 4: 预览内容校验、失败隔离与下载器日志

**Files:**
- Modify: `src/pixiv_archive/sync/orchestrator.py`（`_repair_previews` 内部）
- Modify: `src/pixiv_archive/media/downloader.py:65-102`
- Modify: `src/pixiv_archive/sync/factory.py:17-46`
- Modify: `tests/fakes.py`
- Test: `tests/test_sync_incremental.py`、`tests/test_media.py`

**Interfaces:**
- Consumes: `media.thumbnails.is_valid_image(data: bytes) -> bool`。
- Produces: `ImageDownloader.fetch_bytes` 在候选 URL 全部失败后调用一次 `self._on_error(url, reason)`；失败原因文本为 `"http 404"` 形式。
- `FakeDownloader` 新增可选参数 `corrupt_urls: set[str] | None`（`fetch_bytes` 返回 `b"not-an-image"`）与 `error_urls: set[str] | None`（`fetch_bytes` 抛 `RuntimeError`）。

- [ ] **Step 1: 写失败测试**

`tests/test_media.py` 追加：

```python
async def test_downloader_reports_final_failure_once():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    errors: list[tuple[str, str]] = []
    downloader = ImageDownloader(
        _image_client(handler), on_error=lambda url, reason: errors.append((url, reason))
    )
    url = "https://i.pximg.net/missing.jpg"
    assert await downloader.fetch_bytes(url) is None
    assert errors == [(url, "http 404")]
```

`tests/test_sync_incremental.py` 追加：

```python
async def test_invalid_preview_bytes_are_not_marked_ready(db, tmp_path):
    url = "https://i.pximg.net/80_sq.jpg"
    client = FakeClient({"public": [page([make_illust(80)], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, client, FakeDownloader(corrupt_urls={url})).run_incremental()
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_media.py::test_downloader_reports_final_failure_once tests/test_sync_incremental.py -k "invalid or batch" -q`
Expected: FAIL（`on_error` 从未调用；损坏字节被写成文件）

- [ ] **Step 3: 实现**

- `media/downloader.py`：`_fetch_once` 改为返回 `tuple[bytes | None, str]`（成功 `(data, "")`，404 返回 `(None, "http 404")`，网络/5xx 返回 `(None, f"network error: {exc}")` / `(None, f"http {status}")`）；`fetch_bytes` 记录最后一个 reason，全部失败时调用一次 `_on_error`。
- `sync/factory.py`：加 `logger = logging.getLogger(__name__)`，构造 `ImageDownloader` 时传 `on_error=lambda url, reason: logger.warning("image fetch failed: %s (%s)", url, reason)`。
- `orchestrator._repair_previews`：`data = await self._downloader.fetch_bytes(url)`；`data is None` → 失败 `"fetch failed"`；`not is_valid_image(data)` → 失败 `"invalid image data"`；通过后再原子写。整个 per-target 协程用 `try/except Exception` 包裹，把异常文本作为失败原因；`asyncio.gather(..., return_exceptions=True)` 并把异常结果转成失败。
- `tests/fakes.py`：为 `FakeDownloader` 增加 `corrupt_urls` / `error_urls` 两个集合，分别在 `fetch_bytes`/`fetch_to_file` 前置判断。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_media.py tests/test_sync_incremental.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add src/pixiv_archive/media/downloader.py src/pixiv_archive/sync/factory.py src/pixiv_archive/sync/orchestrator.py tests/fakes.py tests/test_media.py tests/test_sync_incremental.py
git commit -m "fix(sync): validate preview bytes and isolate per-target failures"
```

---

### Task 5: 动图元数据重试与下载范围就绪判定

**Files:**
- Modify: `src/pixiv_archive/sync/orchestrator.py`（`_repair_ugoira_metadata`）
- Modify: `src/pixiv_archive/download/scope.py:164-178`
- Test: `tests/test_sync_incremental.py`、`tests/test_download_scope.py`

**Interfaces:**
- Consumes: Task 2 的 `get_ugoira_meta_backlog` / `record_ugoira_meta_failure` / `upsert_ugoira_meta`。
- Produces: `resolve_scope` 只对 `zip_url != "" and frame_count > 0` 的动图生成 `ugoira_zip`/`ugoira_mp4` 任务。

- [ ] **Step 1: 写失败测试**

`tests/test_sync_incremental.py` 追加：

```python
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
```

`tests/test_download_scope.py` 追加（沿用文件里的 `_seed_illust` 与 `DownloadScope(kind="selected", pids=[...])`）：

```python
async def test_ugoira_jobs_require_ready_metadata(db):
    await _seed_illust(db, 7, type_="ugoira")
    async with db.session() as session:
        session.add(UgoiraMeta(pid=7, zip_url="", frames_json="[]", frame_count=0))
        await session.commit()

    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="selected", pids=[7]))
    kinds = [kind for _, kind, _ in plan.jobs]
    assert "ugoira_zip" not in kinds
    assert "ugoira_mp4" not in kinds
    assert kinds == ["thumb"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_sync_incremental.py::test_ugoira_metadata_failure_is_retried_on_next_run tests/test_download_scope.py::test_ugoira_jobs_require_ready_metadata -q`
Expected: FAIL（没有重试、仍生成 ugoira 任务）

- [ ] **Step 3: 实现**

- `scope.py` 的 `ugoira_pids` 查询加 `.where(UgoiraMeta.zip_url != "", UgoiraMeta.frame_count > 0)`。
- `_repair_ugoira_metadata` 按 Task 3 的队列逻辑实现（若尚未实现），`PixivError` 时 `record_ugoira_meta_failure`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_sync_incremental.py tests/test_download_scope.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add src/pixiv_archive/sync/orchestrator.py src/pixiv_archive/download/scope.py tests/test_sync_incremental.py tests/test_download_scope.py
git commit -m "feat(sync): retry ugoira metadata and gate downloads on readiness"
```

---

### Task 6: 待补数量接入任务详情与 CLI

**Files:**
- Modify: `src/pixiv_archive/web/routers/tasks.py:82-92`
- Modify: `src/pixiv_archive/cli.py:156-170`
- Test: `tests/test_web_routers_tasks.py`、`tests/test_cli.py`

**Interfaces:**
- Consumes: `SyncResult.previews_pending`（Task 3）。
- Produces: `/api/sync` 任务 detail 含 `previews_pending`；CLI 汇总输出含「待补」。

- [ ] **Step 1: 写失败测试**

`tests/test_web_routers_tasks.py`：给 `FakeResult` 加 `previews_pending = 4`，在两处断言任务详情的地方补：

```python
assert listing[0]["detail"]["previews_pending"] == 4
```

（`test_sync_endpoint_starts_task` 与 `test_duplicate_sync_rejected` 里的 FakeResult 都要加该属性。）

`tests/test_cli.py` 追加：

```python
def test_report_sync_includes_pending_previews(capsys):
    from pixiv_archive.cli import _report_sync
    from pixiv_archive.sync.orchestrator import SyncResult

    _report_sync(SyncResult(run_id=1, kind="incremental", previews_pending=3))
    assert "待补 3" in capsys.readouterr().out
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_routers_tasks.py tests/test_cli.py -q`
Expected: FAIL（KeyError / 无「待补」）

- [ ] **Step 3: 实现**

- `tasks.py` 的 sync detail 字典加 `"previews_pending": result.previews_pending`。
- `cli._report_sync` 在预览片段后加 `f"待补 {result.previews_pending}，"`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_routers_tasks.py tests/test_cli.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add src/pixiv_archive/web/routers/tasks.py src/pixiv_archive/cli.py tests/test_web_routers_tasks.py tests/test_cli.py
git commit -m "feat(web): surface pending preview count in sync task detail"
```

---

### Task 7: 统计接口新增封面/动图就绪指标

**Files:**
- Modify: `src/pixiv_archive/web/schemas.py:136-152`
- Modify: `src/pixiv_archive/web/routers/stats.py:49-129`
- Test: `tests/test_web_routers_stats_export.py`

**Interfaces:**
- Consumes: Task 2 的 `illusts.count_previews_missing` / `count_ugoira_meta_missing`。
- Produces: `StatsOut.previews_ready: int`、`StatsOut.previews_missing: int`、`StatsOut.ugoira_meta_missing: int`。

- [ ] **Step 1: 写失败测试**

`tests/test_web_routers_stats_export.py::test_stats_endpoint` 追加：

```python
assert payload["previews_ready"] == 0
assert payload["previews_missing"] == 2
assert payload["ugoira_meta_missing"] == 0
```

并追加一个新测试：

```python
async def test_stats_counts_preview_and_ugoira_gaps(client):
    from pixiv_archive.db.models import Illust

    database = client._transport.app.state.db  # type: ignore[union-attr]
    async with database.session() as session:
        await session.execute(
            Illust.__table__.update().where(Illust.pid == 10).values(preview_state="ready")
        )
        await session.commit()
    payload = (await client.get("/api/stats")).json()
    assert payload["previews_ready"] == 1
    assert payload["previews_missing"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_routers_stats_export.py -q`
Expected: FAIL（KeyError: previews_ready）

- [ ] **Step 3: 实现**

`stats.py` 用三条聚合查询计算：
`previews_ready = count(Illust where state='active' and preview_state='ready')`、
`previews_missing = count(Illust where state='active' and preview_state!='ready')`、
`ugoira_meta_missing` 调用 `illusts.count_ugoira_meta_missing(session)`。
在 `StatsOut` 里加三个 `int` 字段并在返回处赋值。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_routers_stats_export.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add src/pixiv_archive/web/schemas.py src/pixiv_archive/web/routers/stats.py tests/test_web_routers_stats_export.py
git commit -m "feat(web): expose preview and ugoira metadata readiness in stats"
```

---

### Task 8: 维护入口与 CLI 补拉命令

**Files:**
- Modify: `src/pixiv_archive/web/routers/maintenance.py`
- Modify: `src/pixiv_archive/cli.py:13-63`、`115-153`
- Test: `tests/test_web_maintenance.py`、`tests/test_cli.py`

**Interfaces:**
- Consumes: `MetadataSyncService.repair_assets(reset_failed: bool) -> AssetRepairResult`；`sync.factory.open_sync_service(settings)`。
- Produces: `POST /api/maintenance/repair-previews` → `TaskOut`；CLI `maintain repair-previews`；任务 detail 键与 `AssetRepairResult` 字段一一对应（`reset`、`previews_fetched`、`previews_failed`、`previews_pending`、`ugoira_fetched`、`ugoira_failed`）。

- [ ] **Step 1: 写失败测试**

`tests/test_web_maintenance.py` 追加（用 monkeypatch 替换 maintenance 模块里的 `open_sync_service`）：

```python
async def test_repair_previews_task(client, monkeypatch):
    from contextlib import asynccontextmanager
    from dataclasses import asdict

    import pixiv_archive.web.routers.maintenance as maintenance_module
    from pixiv_archive.sync.orchestrator import AssetRepairResult

    class FakeService:
        async def repair_assets(self, *, reset_failed=False):
            assert reset_failed is True
            return AssetRepairResult(reset=2, previews_fetched=3, previews_failed=1,
                                     previews_pending=1, ugoira_fetched=0, ugoira_failed=0)

    @asynccontextmanager
    async def fake_open(settings):
        yield FakeService()

    monkeypatch.setattr(maintenance_module, "open_sync_service", fake_open)
    response = await client.post("/api/maintenance/repair-previews")
    assert response.status_code == 202
    record = await _wait(client)
    assert record["status"] == "completed"
    assert record["detail"]["previews_fetched"] == 3
    assert record["detail"]["reset"] == 2
```

`tests/test_cli.py` 追加：

```python
def test_build_parser_maintain_repair_previews():
    args = build_parser().parse_args(["maintain", "repair-previews"])
    assert args.action == "repair-previews"


async def test_run_maintain_repair_previews(monkeypatch, tmp_path, capsys):
    from contextlib import asynccontextmanager

    import pixiv_archive.cli as cli
    from pixiv_archive.sync.orchestrator import AssetRepairResult

    class FakeService:
        async def repair_assets(self, *, reset_failed=False):
            return AssetRepairResult(reset=1, previews_fetched=2, previews_pending=0)

    @asynccontextmanager
    async def fake_open(settings):
        yield FakeService()

    monkeypatch.setattr(cli, "open_sync_service", fake_open)
    settings = _settings(monkeypatch, tmp_path)
    exit_code = await cli.run_maintain(["maintain", "repair-previews"], settings=settings)
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "预览补拉" in captured.out
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_maintenance.py tests/test_cli.py -k "previews" -q`
Expected: FAIL（404 / 参数 choices 拒绝）

- [ ] **Step 3: 实现**

- `web/routers/maintenance.py`：模块顶部 `from pixiv_archive.sync.factory import open_sync_service`，新增：

```python
@router.post("/repair-previews", status_code=status.HTTP_202_ACCEPTED, response_model=TaskOut)
async def start_repair_previews(
    request: Request,
    tasks: Annotated[TaskManager, Depends(get_tasks)],  # noqa: B008
) -> TaskOut:
    settings = request.app.state.settings

    async def run(context: TaskContext) -> dict[str, Any]:
        context.progress("previews", 0, 1, "补拉缺失封面")
        async with open_sync_service(settings) as service:
            result = await service.repair_assets(reset_failed=True)
        context.progress("previews", 1, 1, "完成")
        return asdict(result)

    ...
```

（`asdict` 从 `dataclasses` 导入；409 处理与现有任务一致。）
- `cli.py`：`maintain` 的 `choices` 加 `"repair-previews"`。`run_maintain` 在 `await _ensure_schema(settings)` 之后、`db = Database(...)` 之前插入该分支（随后立即 `return 0`，不进入原有 `try/finally`）：
  `async with open_sync_service(settings) as service: result = await service.repair_assets(reset_failed=True)`，打印
  `f"预览补拉：重置 {result.reset}，成功 {result.previews_fetched}，失败 {result.previews_failed}，待补 {result.previews_pending}，动图 {result.ugoira_fetched}（失败 {result.ugoira_failed}）"`。
  注意 `run_maintain` 顶部已 `from pixiv_archive.sync.factory import ...`（模块级），测试会 monkeypatch 该名字。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_maintenance.py tests/test_cli.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add src/pixiv_archive/web/routers/maintenance.py src/pixiv_archive/cli.py tests/test_web_maintenance.py tests/test_cli.py
git commit -m "feat: add manual preview repair task and CLI command"
```

---

### Task 9: 前端统计、任务文案与维护按钮

**Files:**
- Modify: `frontend/src/api/types.ts:91-108`
- Modify: `frontend/src/api/mutations.ts`
- Modify: `frontend/src/pages/Stats.tsx:72-94`
- Modify: `frontend/src/components/MaintenanceCard.tsx`
- Modify: `frontend/src/components/TaskPanel.tsx:30-36`
- Modify: `frontend/src/pages/Stats.test.tsx`

**Interfaces:**
- Consumes: Task 7 的 stats 字段；Task 8 的 `POST /api/maintenance/repair-previews`。
- Produces: `useRepairPreviews()`（返回 `TaskOut`，成功时 invalidate `tasks` 与 `stats`）。

- [ ] **Step 1: 写失败的前端测试**

`frontend/src/pages/Stats.test.tsx` 的 `STATS` 常量加 `previews_ready: 2050, previews_missing: 0, ugoira_meta_missing: 0`，并追加：

```tsx
it("shows preview readiness", async () => {
  mockStats({ previews_ready: 2048, previews_missing: 2 });
  renderStats();
  await waitFor(() => expect(screen.getByText("待补 2")).toBeInTheDocument());
});
```

- [ ] **Step 2: 运行测试确认失败**

Run（在 `frontend/` 下）: `npm test -- src/pages/Stats.test.tsx`
Expected: FAIL（找不到「待补 2」）

- [ ] **Step 3: 实现**

- `types.ts`：`StatsOut` 加三个 `number` 字段。
- `Stats.tsx`：网格里加
  `<Card label="封面就绪" value={data.previews_ready.toLocaleString()} hint={data.previews_missing > 0 ? \`待补 ${data.previews_missing.toLocaleString()}\` : "全部就绪"} />`
  和
  `<Card label="动图元数据" value={(data.ugoira_count - data.ugoira_meta_missing).toLocaleString()} hint={data.ugoira_meta_missing > 0 ? \`缺失 ${data.ugoira_meta_missing.toLocaleString()}\` : "全部就绪"} />`。
- `mutations.ts`：新增 `useRepairPreviews`，`POST /api/maintenance/repair-previews`，`onSuccess` invalidate `tasks` 与 `stats`。
- `MaintenanceCard.tsx`：新增按钮「补拉缺失封面」，接 `useRepairPreviews`；错误提示分支加上 `previews.isError`。
- `TaskPanel.tsx` 的 sync 文案改为：
  `` `新增 ${...} · 页 ${...} · 预览 ${detail.previews_fetched ?? 0}` `` +
  `` (detail.previews_failed ? `（失败 ${detail.previews_failed}）` : "") `` +
  `` (detail.previews_pending ? ` · 待补 ${detail.previews_pending}` : "") ``。

- [ ] **Step 4: 运行前端验证并重建产物**

Run（在 `frontend/` 下）:
`npm test -- src/pages/Stats.test.tsx`
`npm run lint`
`npm run typecheck`
`npm run build`
Expected: 全部通过；`src/pixiv_archive/web/static/assets/` 出现新的带 hash 产物且旧产物被替换。

- [ ] **Step 5: 提交**

```powershell
git add frontend/src src/pixiv_archive/web/static
git commit -m "feat(web): show preview readiness and add manual repair button"
```

---

### Task 10: 全量验证与回归

**Files:**
- Test: 全仓库（无新增源码）

**Interfaces:**
- Consumes: Tasks 1-9 的全部产出。

- [ ] **Step 1: 运行后端门禁**

Run:
`uv run ruff check src tests`
`uv run ruff format --check src tests`
`uv run mypy`
`uv run pytest -q`
Expected: 全部退出码 0（ruff 若报格式，先 `uv run ruff format src tests` 再重跑）。

- [ ] **Step 2: 运行前端门禁**

Run（在 `frontend/` 下）: `npm run lint`、`npm run typecheck`、`npm test`、`npm run build`
Expected: 全部通过，`git status` 中 `web/static` 无未提交变更。

- [ ] **Step 3: 复跑原始复现脚本**

Run:
`uv run python "C:\Users\Administrator\AppData\Local\Temp\opencode\preview-repro\repro_preview.py"`
Expected: `run2` 行不再是 `preview attempts []`，而是包含 `https://i.pximg.net/70_sq.jpg`，且 `file True`（第二轮增量即自愈）。

- [ ] **Step 4: 提交（如有格式修正）**

```powershell
git add -A
git commit -m "chore: apply formatter and final verification fixes"
```

（若 Step 1-3 无需改动则跳过本步。）
