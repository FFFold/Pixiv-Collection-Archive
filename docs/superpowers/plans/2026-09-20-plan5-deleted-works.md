# 已失效作品（被画师删除 / 非公开）处理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 同步阶段识别 pixiv 返回的“空壳”作品（被删除/非公开），把它们标记为 `illust.state="deleted"` 而不是当作正常作品入库；保留既有元数据与已下载文件；界面可筛选查看；导出包含全部行。

**Architecture:** 检测发生在 stage A（`MetadataSyncService`）：全量同步检查读到的每一条，增量同步只检查本次实际翻到的页；不再对空壳抓预览图、写 `meta.json`、建下载相关数据。下载侧不做任何失效判定（404 仍记失败）。Web 层新增 `状态` 筛选参数，导出去掉 `active` 硬过滤。

**Tech Stack:** Python 3.12 / SQLAlchemy async / pytest (`asyncio_mode=auto`) / React 19 + TypeScript / Vitest。

---

## 背景与已确认的决策

- **判定条件（满足其一）：** 图片地址命中 `s.pximg.net/common/images/limit_*`，或作者 id 为 0。`create_date` 是请求时刻的伪造值，不能用；`sanity_level`/计数不参与判定。
- **场景 1（首次同步即空壳）：** 只建最简记录（pid + 收藏位置 + `state="deleted"`），不存空标题、不建 `illust_page`、不抓预览、不写 `meta.json`、不建下载任务。
- **场景 2（已同步过后失效）：** 只改状态；标题/标签/原图地址/已下载文件/预览图全部保留。
- **场景 3（同步时还活着、没下载、之后被删）：** 等下一次全量同步检测；下载 404 只记失败，不做失效判定。
- **恢复：** 同步读到真实数据时自动恢复 `state="active"` 并正常覆盖。
- **队列：** 标失效时把该 pid 的 `pending`/`failed` 下载任务改为 `skipped`。
- **界面：** 工具栏新增第 6 个下拉「状态：全部状态 / 仅正常 / 已失效」，默认「仅正常」；不加徽标、不加路由、详情页与统计页不改。
- **导出：** 包含数据库全部行（不再只看 `active`）。
- **不写迁移、不修存量数据**（现有 61 条空壳等下次全量同步时被标出）。

**为什么没有迁移：** `illust.state` 列已存在（`String(16)`），只是新增一个取值。

---

## 文件结构

**后端**
- Create: `src/pixiv_archive/sync/unavailable.py` — 纯函数判定“空壳”，无 I/O。
- Modify: `src/pixiv_archive/db/repo/illusts.py` — 新增“仅标记失效/恢复”的仓库函数。
- Modify: `src/pixiv_archive/db/repo/downloads.py` — 新增按 pid 跳过队列任务的函数。
- Modify: `src/pixiv_archive/sync/orchestrator.py` — 全量/增量接入检测与统计。
- Modify: `src/pixiv_archive/db/models.py` — `Illust` 增加 `is_unavailable` 属性。
- Modify: `src/pixiv_archive/web/gallery_query.py`、`web/routers/gallery.py` — 状态筛选。
- Modify: `src/pixiv_archive/web/schemas.py` — `GalleryItem.state`。
- Modify: `src/pixiv_archive/web/routers/export.py` — 导出全部行。
- Modify: `src/pixiv_archive/cli.py`、`web/routers/tasks.py` — 汇报/任务详情增加 `deleted_count`。

**测试**
- Create: `tests/test_sync_unavailable.py` — 同步检测（场景 1/2/3 与恢复）。
- Modify: `tests/fakes.py` — 新增 `make_stub_illust`。
- Modify: `tests/test_web_gallery_query.py`、`tests/test_web_routers_gallery.py`（若不存在则并入前者）— 状态筛选。
- Modify: `tests/test_export.py`（若存在，见 Task 8 说明）— 导出范围。
- Frontend: `frontend/src/api/types.ts`、`frontend/src/lib/constants.ts`、`frontend/src/components/Toolbar.tsx`、`frontend/src/components/Toolbar.test.tsx`（若不存在则按 Task 11 创建）。

---

### Task 1: 空壳判定函数

**Files:**
- Create: `src/pixiv_archive/sync/unavailable.py`
- Test: `tests/test_sync_unavailable.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sync_unavailable.py
from fakes import make_illust, make_stub_illust
from pixiv_archive.sync.unavailable import is_unavailable


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
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_sync_unavailable.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.sync.unavailable'`（以及 `make_stub_illust` 未定义）

- [ ] **Step 3: 在 `tests/fakes.py` 增加 stub 工厂**

在 `make_illust` 之后追加：

```python
_STUB_URL = "https://s.pximg.net/common/images/limit_unknown_360.png"


def make_stub_illust(pid: int, **overrides) -> PixivIllust:
    """A bookmark entry for a deleted/private work, as pixiv returns it."""
    payload = {
        "id": pid,
        "title": "",
        "type": "illust",
        "page_count": 1,
        "user": {"id": 0, "name": "", "account": ""},
        "tags": [],
        "width": 100,
        "height": 100,
        "total_view": 0,
        "total_bookmarks": 0,
        "meta_single_page": {"original_image_url": _STUB_URL},
        "image_urls": {
            "square_medium": _STUB_URL,
            "medium": _STUB_URL,
            "large": _STUB_URL,
        },
    }
    payload.update(overrides)
    return PixivIllust.model_validate(payload)
```

- [ ] **Step 4: 实现判定函数**

```python
# src/pixiv_archive/sync/unavailable.py
from pixiv_archive.pixiv.models import Illust as PixivIllust

_PLACEHOLDER_MARKER = "s.pximg.net/common/images/limit_"


def is_unavailable(illust: PixivIllust) -> bool:
    """True when pixiv returns a placeholder stub for a deleted/private work.

    pixiv keeps the bookmark entry but blanks everything out: user id 0 and
    every image URL points at s.pximg.net/common/images/limit_*.
    """
    if illust.user.id == 0:
        return True
    return any(_PLACEHOLDER_MARKER in url for url in _all_urls(illust))


def _all_urls(illust: PixivIllust) -> list[str]:
    urls = list(illust.original_urls)
    urls.extend(str(value) for value in illust.image_urls.values())
    for page in illust.meta_pages:
        urls.extend(str(value) for value in (page.get("image_urls") or {}).values())
    return urls
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_sync_unavailable.py -q`
Expected: PASS（4 passed）

- [ ] **Step 6: 提交**

```powershell
git add src/pixiv_archive/sync/unavailable.py tests/test_sync_unavailable.py tests/fakes.py
git commit -m "feat(sync): detect pixiv placeholder stubs for deleted works"
```

---

### Task 2: 仓库函数（标记失效 / 恢复 / 跳过队列）

**Files:**
- Modify: `src/pixiv_archive/db/repo/illusts.py`
- Modify: `src/pixiv_archive/db/repo/downloads.py`
- Modify: `src/pixiv_archive/db/models.py`
- Test: `tests/test_sync_unavailable.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_sync_unavailable.py`：

```python
import pytest
from sqlalchemy import select

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import DownloadJob, Illust
from pixiv_archive.db.repo import downloads, illusts


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "unavail.db")
    await database.create_all()
    yield database
    await database.dispose()


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


async def test_reactivate_illust_sets_active(db):
    async with db.session() as session:
        await illusts.upsert_illust(session, make_illust(1), meta_json="{}")
        await illusts.mark_illust_deleted(session, 1)
        await session.commit()
    async with db.session() as session:
        changed = await illusts.reactivate_illust(session, 1)
        await session.commit()
    assert changed is True
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert row.state == "active"


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
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_sync_unavailable.py -q`
Expected: FAIL — `AttributeError: module 'pixiv_archive.db.repo.illusts' has no attribute 'mark_illust_deleted'`

- [ ] **Step 3: 在 `db/models.py` 给 `Illust` 加只读属性**

在 `Illust` 类 `updated_at` 之后追加：

```python
    @property
    def is_unavailable(self) -> bool:
        """True when pixiv no longer serves this work (deleted or private)."""
        return self.state == "deleted"
```

- [ ] **Step 4: 实现 `mark_illust_deleted` / `reactivate_illust`**

追加到 `src/pixiv_archive/db/repo/illusts.py` 末尾：

```python
async def mark_illust_deleted(session: AsyncSession, pid: int) -> bool:
    """Flag a work as deleted without touching any of its other columns.

    Returns True when a row was updated. A work that never existed is ignored;
    its bookmark row is still written by the caller.
    """
    result = await session.execute(
        update(Illust)
        .where(Illust.pid == pid, Illust.state != "deleted")
        .values(state="deleted", updated_at=utcnow())
    )
    assert isinstance(result, CursorResult)
    return (result.rowcount or 0) > 0


async def reactivate_illust(session: AsyncSession, pid: int) -> bool:
    result = await session.execute(
        update(Illust)
        .where(Illust.pid == pid, Illust.state == "deleted")
        .values(state="active", updated_at=utcnow())
    )
    assert isinstance(result, CursorResult)
    return (result.rowcount or 0) > 0
```

同时把文件顶部 SQLAlchemy 导入改为：

```python
from sqlalchemy import CursorResult, delete, select, update
```

- [ ] **Step 5: 实现 `skip_jobs_for_pid`**

追加到 `src/pixiv_archive/db/repo/downloads.py` 末尾：

```python
async def skip_jobs_for_pid(session: AsyncSession, pid: int) -> int:
    """Skip queued/failed jobs for a work that no longer exists on pixiv."""
    result = await session.execute(
        update(DownloadJob)
        .where(DownloadJob.pid == pid, DownloadJob.status.in_(("pending", "failed")))
        .values(status="skipped", last_error="illust deleted", updated_at=utcnow())
    )
    assert isinstance(result, CursorResult)
    return result.rowcount or 0
```

并把该文件首行导入改为：

```python
from pixiv_archive.db.models import DownloadBatch, DownloadJob, utcnow
```

- [ ] **Step 6: 运行确认通过**

Run: `uv run pytest tests/test_sync_unavailable.py -q`
Expected: PASS（7 passed）

- [ ] **Step 7: 提交**

```powershell
git add src/pixiv_archive/db/repo/illusts.py src/pixiv_archive/db/repo/downloads.py src/pixiv_archive/db/models.py tests/test_sync_unavailable.py
git commit -m "feat(db): add deleted-state repo helpers and job skipping"
```

---

### Task 3: 全量同步检测（场景 1 / 2 与恢复）

**Files:**
- Modify: `src/pixiv_archive/sync/orchestrator.py:163-254`
- Test: `tests/test_sync_unavailable.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_sync_unavailable.py`：

```python
from pathlib import Path

from fakes import FakeClient, FakeDownloader, page
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.sync.orchestrator import MetadataSyncService


def build_service(db, tmp_path, client, downloader) -> MetadataSyncService:
    return MetadataSyncService(
        db=db,
        client=client,
        storage=WorksStorage(tmp_path / "works"),
        downloader=downloader,
        download_previews=True,
    )


async def test_full_sync_marks_stub_deleted_and_skips_side_effects(db, tmp_path):
    client = FakeClient({"public": [page([make_stub_illust(1)], cursor=None)], "private": []})
    downloader = FakeDownloader()
    result = await build_service(db, tmp_path, client, downloader).run_full()

    assert result.deleted_count == 1
    assert result.new_count == 0
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert row.state == "deleted"
    assert row.title == ""
    assert row.page_count == 0
    assert downloader.urls == []
    assert not (tmp_path / "works" / "1" / "meta.json").exists()
    async with db.session() as session:
        pages = (await session.execute(select(IllustPage))).scalars().all()
    assert pages == []


async def test_full_sync_deleting_keeps_existing_metadata_and_files(db, tmp_path):
    setup = FakeClient({"public": [page([make_illust(1, title="original")], cursor=None)], "private": []})
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()
    storage = WorksStorage(tmp_path / "works")
    assert storage.preview_path(1).exists()

    stub = FakeClient({"public": [page([make_stub_illust(1)], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, stub, FakeDownloader()).run_full()

    assert result.deleted_count == 1
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert row.state == "deleted"
    assert row.title == "original"
    assert storage.preview_path(1).exists()
    await assert_original_url_unchanged(db, 1, "https://i.pximg.net/1.jpg")


async def test_full_sync_restores_work_that_came_back(db, tmp_path):
    stub = FakeClient({"public": [page([make_stub_illust(1)], cursor=None)], "private": []})
    await build_service(db, tmp_path, stub, FakeDownloader()).run_full()

    alive = FakeClient({"public": [page([make_illust(1, title="back")], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, alive, FakeDownloader()).run_full()

    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert row.state == "active"
    assert row.title == "back"
    assert result.deleted_count == 1


async def assert_original_url_unchanged(db, pid: int, expected: str) -> None:
    async with db.session() as session:
        row = (await session.execute(select(IllustPage).where(IllustPage.pid == pid))).scalar_one()
    assert row.original_url == expected
```

补充所需导入：在文件顶部加上 `from pixiv_archive.db.models import IllustPage`。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_sync_unavailable.py -q`
Expected: FAIL — `TypeError: SyncResult.__init__() got an unexpected keyword argument 'deleted_count'`（或断言 `result.deleted_count` 不存在）

- [ ] **Step 3: 给 `SyncResult` 加字段**

`orchestrator.py` 的 `SyncResult` 数据类中，在 `unbookmarked_count` 之后加：

```python
    deleted_count: int = 0
```

- [ ] **Step 4: 改 `run_full` 的写入循环**

替换 `run_full` 中 `async with self._db.session() as session:` 写入块（从 `for illust, restrict, pos in listed:` 到 `await session.commit()`）为：

```python
            async with self._db.session() as session:
                for illust, restrict, pos in listed:
                    try:
                        if is_unavailable(illust):
                            deleted = await self._handle_unavailable(
                                session, illust, restrict=restrict
                            )
                            if deleted:
                                result.deleted_count += 1
                            continue
                        await illusts.upsert_illust(
                            session, illust, meta_json=self._meta_json(illust)
                        )
                        new_rank = rank_mod.full_rank(pos)
                        was_known = illust.pid in known_pids
                        await bookmarks.set_active_rank(
                            session,
                            pid=illust.pid,
                            restrict=restrict,
                            rank=new_rank,
                            now=now,
                        )
                        if was_known:
                            if old_ranks.get(illust.pid) != new_rank:
                                result.rank_rebuilt_count += 1
                        else:
                            result.new_count += 1
                        preview_targets.append(illust)
                        if illust.type == "ugoira":
                            ugoira_targets.append(illust)
                    except Exception as exc:  # noqa: BLE001 - keep the batch going
                        result.failed_count += 1
                        result.warnings.append(f"作品 {illust.pid} 元数据写入失败: {exc}")
                if truncated:
                    result.warnings.append("达到 max_pages 限制，未完成全量遍历，未标记取消收藏")
                else:
                    result.unbookmarked_count = await bookmarks.mark_unbookmarked(
                        session, missing, now=now
                    )
                await session.commit()
```

- [ ] **Step 5: 新增 `_handle_unavailable` 辅助方法**

加在 `_finalize` 之前：

```python
    async def _handle_unavailable(
        self, session: Any, illust: PixivIllust, *, restrict: str
    ) -> bool:
        """Mark a pixiv stub as deleted, creating a bookmark-only row if new.

        Existing metadata, original URLs and downloaded files are left alone;
        only the state flag and bookmark position are written.
        """
        known = await illusts.get_illust_state(session, illust.pid) is not None
        if known:
            changed = await illusts.mark_illust_deleted(session, illust.pid)
        else:
            await illusts.create_placeholder_illust(session, pid=illust.pid)
            changed = True
        await bookmarks.set_active_rank(
            session,
            pid=illust.pid,
            restrict=restrict,
            rank=rank_mod.full_rank(illust.position) if False else 0,
            now=utcnow(),
        )
        await downloads.skip_jobs_for_pid(session, illust.pid)
        return changed
```

**注意：** 上面的 `rank` 行是占位写法，必须替换成调用方传入的真实 rank。把签名改为 `_handle_unavailable(self, session, illust, *, restrict: str, rank: int) -> bool`，调用处传 `rank=rank_mod.full_rank(pos)`，方法体内直接 `rank=rank`，并删除 `illust.position`。最终实现：

```python
    async def _handle_unavailable(
        self, session: AsyncSession, illust: PixivIllust, *, restrict: str, rank: int
    ) -> bool:
        known = await illusts.get_illust_state(session, illust.pid) is not None
        if known:
            changed = await illusts.mark_illust_deleted(session, illust.pid)
        else:
            await illusts.create_placeholder_illust(session, pid=illust.pid)
            changed = True
        await bookmarks.set_active_rank(
            session, pid=illust.pid, restrict=restrict, rank=rank, now=utcnow()
        )
        await downloads.skip_jobs_for_pid(session, illust.pid)
        return changed
```

调用处相应改为：

```python
                        if is_unavailable(illust):
                            deleted = await self._handle_unavailable(
                                session,
                                illust,
                                restrict=restrict,
                                rank=rank_mod.full_rank(pos),
                            )
                            if deleted:
                                result.deleted_count += 1
                            continue
```

补充导入到 `orchestrator.py`：

```python
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.repo import bookmarks, downloads, illusts, sync_runs
from pixiv_archive.sync.unavailable import is_unavailable
```

- [ ] **Step 6: 实现 `get_illust_state` / `create_placeholder_illust`**

追加到 `src/pixiv_archive/db/repo/illusts.py`：

```python
async def get_illust_state(session: AsyncSession, pid: int) -> str | None:
    return (
        await session.execute(select(Illust.state).where(Illust.pid == pid))
    ).scalar_one_or_none()


async def create_placeholder_illust(session: AsyncSession, *, pid: int) -> None:
    """Insert a bare illust row for a work that is already deleted on pixiv.

    No title, tags, pages or meta_json: there is nothing real to store, and
    a later sync can still restore it once the work is visible again.
    """
    stmt = insert(Illust).values(pid=pid, author_id=0, state="deleted")
    stmt = stmt.on_conflict_do_nothing(index_elements=[Illust.pid])
    await session.execute(stmt)
```

- [ ] **Step 7: 运行确认通过**

Run: `uv run pytest tests/test_sync_unavailable.py -q`
Expected: PASS（10 passed）。若 `test_full_sync_deleting_keeps_existing_metadata_and_files` 失败于 `assert_original_url_unchanged`，检查 `_handle_unavailable` 是否误调用了 `upsert_illust`。

- [ ] **Step 8: 跑全量同步现有测试，确认无回归**

Run: `uv run pytest tests/test_sync_full.py tests/test_sync_incremental.py -q`
Expected: PASS（全部）

- [ ] **Step 9: 提交**

```powershell
git add src/pixiv_archive/sync/orchestrator.py src/pixiv_archive/db/repo/illusts.py tests/test_sync_unavailable.py
git commit -m "feat(sync): flag deleted works during full sync"
```

---

### Task 4: 增量同步检测（只负责本次翻到的页）

**Files:**
- Modify: `src/pixiv_archive/sync/orchestrator.py:75-161`
- Test: `tests/test_sync_unavailable.py`

- [ ] **Step 1: 写失败测试**

追加：

```python
async def test_incremental_marks_known_work_deleted_when_first_page_shows_stub(db, tmp_path):
    setup = FakeClient({"public": [page([make_illust(1, title="original")], cursor=None)], "private": []})
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()

    shrunk = FakeClient({"public": [page([make_stub_illust(1)], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, shrunk, FakeDownloader()).run_incremental()

    assert result.deleted_count == 1
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert row.state == "deleted"
    assert row.title == "original"


async def test_incremental_restores_stub_that_came_back(db, tmp_path):
    stub = FakeClient({"public": [page([make_stub_illust(1)], cursor=None)], "private": []})
    await build_service(db, tmp_path, stub, FakeDownloader()).run_full()
    async with db.session() as session:
        assert (await session.get(Illust, 1)).state == "deleted"

    alive = FakeClient({"public": [page([make_illust(1, title="back")], cursor=None)], "private": []})
    await build_service(db, tmp_path, alive, FakeDownloader()).run_incremental()
    async with db.session() as session:
        row = await session.get(Illust, 1)
    assert row.state == "active"
    assert row.title == "back"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_sync_unavailable.py -q -k incremental`
Expected: FAIL — 增量同步对已 known 且非 unbookmarked 的 pid 直接 `continue`（`orchestrator.py:107`），不会标记 deleted。

- [ ] **Step 3: 改增量抓取循环，收集“本轮见到的”**

把 `orchestrator.py` 的 `run_incremental` 抓取循环（`for restrict in RESTRICTS:` 到 `max_pages` 判断）替换为：

```python
            discovered: list[tuple[PixivIllust, str]] = []
            seen: set[int] = set()
            observed: list[PixivIllust] = []
            for restrict in RESTRICTS:
                cursor: int | None = None
                while not self._cancel.is_set():
                    page = await self._client.list_bookmarks(restrict, max_bookmark_id=cursor)
                    result.pages_fetched += 1
                    self._progress(
                        "fetch",
                        result.pages_fetched,
                        0,
                        f"读取{restrict}收藏第 {result.pages_fetched} 页",
                    )
                    if not page.illusts:
                        break
                    observed.extend(page.illusts)
                    page_all_known = True
                    for illust in page.illusts:
                        if illust.pid in known_pids and states.get(illust.pid) != "unbookmarked":
                            continue
                        page_all_known = False
                        if illust.pid not in seen:
                            seen.add(illust.pid)
                            discovered.append((illust, restrict))
                    if page_all_known:
                        break
                    if page.next_bookmark_id is None:
                        break
                    cursor = page.next_bookmark_id
                    if max_pages is not None and result.pages_fetched >= max_pages:
                        break
```

- [ ] **Step 4: 在写入前处理本轮看到的 stub**

在 `ranks = rank_mod.incremental_ranks(...)` 之前插入：

```python
            live_discovered: list[tuple[PixivIllust, str]] = []
            async with self._db.session() as session:
                for illust, restrict in discovered:
                    if is_unavailable(illust):
                        deleted = await self._handle_unavailable(
                            session,
                            illust,
                            restrict=restrict,
                            rank=await bookmarks.next_rank(session, pid=illust.pid),
                        )
                        if deleted:
                            result.deleted_count += 1
                    else:
                        live_discovered.append((illust, restrict))
                await session.commit()
```

**注意：** 这里不能给 stub 分配“最前”的新 rank（它会破坏已有收藏顺序）。`next_rank` 的约定见 Step 5：已有 bookmark 时保留原 rank，新 bookmark 用当前最小 rank 之前的位置。

同时把后续写入循环改为遍历 `live_discovered`：

```python
                for (illust, restrict), rank_value in zip(discovered, ranks, strict=True):
```

改成：

```python
                for (illust, restrict), rank_value in zip(live_discovered, ranks, strict=True):
```

并把 `ranks = rank_mod.incremental_ranks(min_rank, len(discovered))` 改为 `len(live_discovered)`。

- [ ] **Step 5: 实现 `bookmarks.next_rank`**

追加到 `src/pixiv_archive/db/repo/bookmarks.py`：

```python
async def next_rank(session: AsyncSession, *, pid: int) -> int:
    """Rank to use when touching an existing bookmark without moving it.

    Known pids keep their current rank; brand-new pids are placed in front of
    every existing rank (same convention as incremental sync).
    """
    existing = (
        await session.execute(select(Bookmark.rank).where(Bookmark.pid == pid))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    from pixiv_archive.sync import rank as rank_mod

    minimum = await get_min_rank(session)
    return rank_mod.incremental_ranks(minimum, 1)[0]
```

- [ ] **Step 6: 运行确认通过**

Run: `uv run pytest tests/test_sync_unavailable.py -q`
Expected: PASS（12 passed）

- [ ] **Step 7: 回归整套同步测试**

Run: `uv run pytest tests/test_sync_full.py tests/test_sync_incremental.py tests/test_rank.py -q`
Expected: PASS（全部）

- [ ] **Step 8: 提交**

```powershell
git add src/pixiv_archive/sync/orchestrator.py src/pixiv_archive/db/repo/bookmarks.py tests/test_sync_unavailable.py
git commit -m "feat(sync): detect deleted works in the pages incremental sync reads"
```

---

### Task 5: 同步结果汇报与任务详情

**Files:**
- Modify: `src/pixiv_archive/cli.py:103-116`
- Modify: `src/pixiv_archive/web/routers/tasks.py:69-78`
- Test: `tests/test_sync_unavailable.py`（无新增断言）、`tests/test_cli.py`（改动现有断言）

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_sync_unavailable.py`：

```python
async def test_sync_result_reports_deleted_count(db, tmp_path):
    client = FakeClient({"public": [page([make_stub_illust(5)], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, client, FakeDownloader()).run_incremental()
    assert result.deleted_count == 1
    assert result.new_count == 0
```

- [ ] **Step 2: 运行确认通过（此时已实现）**

Run: `uv run pytest tests/test_sync_unavailable.py::test_sync_result_reports_deleted_count -q`
Expected: PASS

- [ ] **Step 3: CLI 汇报里加“失效”**

`cli.py` 的 `_report_sync` 改为：

```python
def _report_sync(result: SyncResult) -> None:
    print(
        f"[{result.kind}] {result.status}: "
        f"新增 {result.new_count}，取消 {result.unbookmarked_count}，"
        f"失效 {result.deleted_count}，"
        f"rank 修正 {result.rank_rebuilt_count}，"
        f"页数 {result.pages_fetched}，"
        f"预览图 {result.previews_fetched}（失败 {result.previews_failed}），"
        f"ugoira {result.ugoira_meta_fetched}，"
        f"其它失败 {result.failed_count}"
    )
```

- [ ] **Step 4: Web 任务详情里加 `deleted_count`**

`web/routers/tasks.py` 的返回字典中，在 `"unbookmarked_count"` 之后加：

```python
                "deleted_count": result.deleted_count,
```

- [ ] **Step 5: 更新受影响的现有测试**

`tests/test_cli.py` 与其他断言同步汇报字符串的测试若失败，按新输出更新期望值。先运行找出失败点：

Run: `uv run pytest tests/test_cli.py tests/test_cli_download.py tests/test_web_routers_tasks.py -q`
Expected: 若有 FAIL，按实际新字符串更新断言后重跑至 PASS。

- [ ] **Step 6: 全量后端测试**

Run: `uv run pytest -q`
Expected: PASS（全部）

- [ ] **Step 7: 提交**

```powershell
git add src/pixiv_archive/cli.py src/pixiv_archive/web/routers/tasks.py tests
git commit -m "feat(sync): report deleted_count in CLI and task detail"
```

---

### Task 6: Web API 状态筛选与导出范围

**Files:**
- Modify: `src/pixiv_archive/web/gallery_query.py:18-55`
- Modify: `src/pixiv_archive/web/routers/gallery.py:29-47`
- Modify: `src/pixiv_archive/web/schemas.py:15-33`
- Modify: `src/pixiv_archive/web/routers/export.py:33-46`
- Test: `tests/test_web_gallery_query.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_web_gallery_query.py`：

```python
async def test_query_default_excludes_deleted(db):
    await _seed(db, 1, rank=0)
    await _seed(db, 2, rank=10, state="deleted")
    async with db.session() as session:
        result = await query_gallery(session, GalleryFilters(), offset=0, limit=10)
    assert [item.pid for item in result.items] == [1]


async def test_query_only_deleted_returns_stubs(db):
    await _seed(db, 1, rank=0)
    await _seed(db, 2, rank=10, state="deleted")
    async with db.session() as session:
        result = await query_gallery(
            session, GalleryFilters(only_deleted=True), offset=0, limit=10
        )
    assert [item.pid for item in result.items] == [2]
    assert result.items[0].state == "deleted"


async def test_query_all_statuses_includes_deleted(db):
    await _seed(db, 1, rank=0)
    await _seed(db, 2, rank=10, state="deleted")
    async with db.session() as session:
        result = await query_gallery(
            session, GalleryFilters(include_deleted=True), offset=0, limit=10
        )
    assert [item.pid for item in result.items] == [1, 2]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_web_gallery_query.py -q`
Expected: FAIL — `TypeError: GalleryFilters.__init__() got an unexpected keyword argument 'only_deleted'`

- [ ] **Step 3: `GalleryFilters` 与条件构造**

`gallery_query.py` 的 `GalleryFilters` 增加两个字段：

```python
    only_deleted: bool = False
    include_deleted: bool = False
```

`_base_conditions` 开头（`conditions = [Illust.state == "active"]` 处）替换为：

```python
    if filters.only_deleted:
        conditions = [Illust.state == "deleted"]
    elif filters.include_deleted:
        conditions = []
    else:
        conditions = [Illust.state == "active"]
```

`query_gallery` 的 `GalleryItem(...)` 构造里，在 `unbookmarked=...` 之后加：

```python
            state=illust.state,
```

- [ ] **Step 4: `GalleryItem` 暴露 state**

`web/schemas.py` 的 `GalleryItem` 在 `unbookmarked: bool` 之后加：

```python
    state: str
```

- [ ] **Step 5: 路由参数**

`web/routers/gallery.py` 在 `include_unbookmarked: bool = False` 之后加：

```python
    only_deleted: bool = False,
    include_deleted: bool = False,
```

并在 `GalleryFilters(...)` 构造里传入这两个参数。

- [ ] **Step 6: 导出包含全部行**

`web/routers/export.py` 的 `_selected_pids` 里把 `.where(Illust.state == "active")` 删除，并在 `if payload.only_downloaded:` 保持原样。改后：

```python
async def _selected_pids(session: AsyncSession, payload: ExportRequest) -> list[int]:
    stmt = (
        select(Illust.pid)
        .join(Bookmark, Bookmark.pid == Illust.pid)
        .order_by(Bookmark.rank)
    )
    if payload.pids:
        stmt = stmt.where(Illust.pid.in_(payload.pids))
    if payload.x_restrict is not None:
        stmt = stmt.where(Illust.x_restrict == payload.x_restrict)
    if payload.only_downloaded:
        stmt = stmt.where(Illust.has_original.is_(True))
    return list((await session.execute(stmt)).scalars().all())
```

- [ ] **Step 7: 运行确认通过**

Run: `uv run pytest tests/test_web_gallery_query.py tests/test_export.py -q`
Expected: PASS。若 `tests/test_export.py` 不存在，运行 `uv run pytest tests/test_web_routers_stats_export.py -q`，并按新语义更新“导出只含 active”的断言（改为包含已删除行）。

- [ ] **Step 8: 提交**

```powershell
git add src/pixiv_archive/web tests
git commit -m "feat(web): add deleted-state gallery filter and include all rows in export"
```

---

### Task 7: 前端状态筛选

**Files:**
- Modify: `frontend/src/api/types.ts:19,114-129`
- Modify: `frontend/src/lib/constants.ts`
- Modify: `frontend/src/components/Toolbar.tsx`
- Test: `frontend/src/components/Toolbar.test.tsx`（若不存在则创建）

- [ ] **Step 1: 写失败测试**

先看是否存在 `frontend/src/components/Toolbar.test.tsx`：

Run: `Get-ChildItem frontend/src/components -Filter Toolbar.test.tsx`

若不存在，创建：

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Toolbar from "./Toolbar";

describe("Toolbar 状态筛选", () => {
  it("选择已失效时回传 only_deleted", async () => {
    const onChange = vi.fn();
    render(
      <Toolbar
        query={{ offset: 0, limit: 60, sort: "rank" }}
        onChange={onChange}
        selectedCount={0}
        onDownloadSelected={vi.fn()}
        onDownloadAllMissing={vi.fn()}
        downloadPending={false}
      />,
    );
    await userEvent.selectOptions(screen.getByLabelText("状态"), "deleted");
    expect(onChange).toHaveBeenCalledWith({ only_deleted: true, offset: 0 });
  });

  it("选择全部状态时回传 include_deleted", async () => {
    const onChange = vi.fn();
    render(
      <Toolbar
        query={{ offset: 0, limit: 60, sort: "rank" }}
        onChange={onChange}
        selectedCount={0}
        onDownloadSelected={vi.fn()}
        onDownloadAllMissing={vi.fn()}
        downloadPending={false}
      />,
    );
    await userEvent.selectOptions(screen.getByLabelText("状态"), "all");
    expect(onChange).toHaveBeenCalledWith({ include_deleted: true, offset: 0 });
  });
});
```

若测试文件已存在，把上述两个用例追加进去，并沿用文件里已有的导入与渲染辅助函数。

- [ ] **Step 2: 运行确认失败**

Run: `npm test -- src/components/Toolbar.test.tsx`（在 `frontend/` 目录）
Expected: FAIL — `Unable to find a label with the text of: 状态`

- [ ] **Step 3: 增加类型与常量**

`frontend/src/api/types.ts`：
- `GalleryItem` 增加 `state: string;`
- `GalleryQuery` 增加 `only_deleted?: boolean;` 和 `include_deleted?: boolean;`

`frontend/src/lib/constants.ts` 追加：

```ts
export const STATUS_OPTIONS = [
  { value: "active", label: "仅正常" },
  { value: "all", label: "全部状态" },
  { value: "deleted", label: "已失效" },
] as const;
```

- [ ] **Step 4: 工具栏加第 6 个下拉**

`frontend/src/components/Toolbar.tsx`：
- 导入 `STATUS_OPTIONS`
- 在「分级」`Select` 之后插入：

```tsx
      <Select
        ariaLabel="状态"
        value={
          query.only_deleted ? "deleted" : query.include_deleted ? "all" : "active"
        }
        options={STATUS_OPTIONS}
        onChange={(value) =>
          onChange({
            only_deleted: value === "deleted" ? true : undefined,
            include_deleted: value === "all" ? true : undefined,
            offset: 0,
          })
        }
      />
```

- [ ] **Step 5: 运行确认通过**

Run: `npm test -- src/components/Toolbar.test.tsx`
Expected: PASS（2 passed）

- [ ] **Step 6: 前端全量检查**

Run: `npm run lint; npm run typecheck; npm test`
Expected: 全部通过

- [ ] **Step 7: 重新构建并提交**

Run: `npm run build`（在 `frontend/` 目录；产物写入 `src/pixiv_archive/web/static/`）

```powershell
cd frontend; npm run build; cd ..
git add frontend/src frontend/src/components/Toolbar.test.tsx src/pixiv_archive/web/static
git commit -m "feat(web): add status filter to gallery toolbar"
```

- [ ] **Step 8: 提交构建产物（若与上一步分开）**

Run: `git status --porcelain src/pixiv_archive/web/static`
若仍有未提交的旧 hash 资源文件被删除，执行：

```powershell
git add -A src/pixiv_archive/web/static
git commit -m "chore: rebuild frontend static assets"
```

---

### Task 8: 后端整体验证（lint / 格式 / 类型 / 测试）

**Files:** 无改动

- [ ] **Step 1: 运行 CI 全序列**

Run:
```powershell
uv run ruff check src tests; uv run ruff format --check src tests; uv run mypy; uv run pytest -q
```
Expected: 全部通过。若 `ruff format --check` 失败，运行 `uv run ruff format src tests` 后重跑并单独提交 `chore: apply ruff format`。

- [ ] **Step 2: 前端 CI 序列**

Run（在 `frontend/`）: `npm run lint; npm run typecheck; npm test; npm run build`
Expected: 全部通过，`src/pixiv_archive/web/static/` 无明显意外变化。

- [ ] **Step 3: 提交任何格式修正**

```powershell
git add -A
git commit -m "chore: satisfy lint and format checks"
```

（仅当 Step 1/2 产生了未提交改动时才执行）

---

## 自查记录

- **场景覆盖：** 场景 1 → Task 3/4 的 `create_placeholder_illust` 分支；场景 2 → Task 3 的 `test_full_sync_deleting_keeps_existing_metadata_and_files`；场景 3 → 明确不做（下载 404 只记失败，等全量/增量检测），无对应任务，符合最终决策。
- **恢复：** Task 3/4 各有一条恢复测试。
- **筛选：** 后端 Task 6、前端 Task 7。
- **导出：** Task 6 Step 6。
- **队列跳过：** Task 2 `skip_jobs_for_pid` + Task 3/4 的 `_handle_unavailable` 调用。
- **不写迁移：** 已确认 `illust.state` 列存在。
- 已知风险：增量恢复 stub 时需要真实数据通过 `upsert_illust` 写入，Task 4 的 `live_discovered` 路径已覆盖；`next_rank` 保留原 rank 不变，避免失效/恢复扰动收藏顺序。
