# 计划 ②：导出与统计 + 维护面板实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 导出支持"按选中 / 按当前筛选"；统计改为 SQL 聚合并新增体积分布与可点击跳转；WebUI 维护面板（重建存储统计 / 修复下载状态 / 数据库体检）。

**Architecture:** 迁移 `0004` 为 `illust` 加 `byte_size` / `thumb_ready` / `animation_ready` 三列（不扫描）；下载 worker 写文件后维护三列；`/api/stats` 改纯 SQL 聚合并暴露 `stats_stale`；新增 `web/routers/maintenance.py`（复用 `TaskManager` + SSE）与 `maintenance/` 服务模块；前端新增 `MaintenanceCard`、改造 `Export.tsx` 与 `Stats.tsx`。

**Tech Stack:** 同计划 ①（Python 3.12 / SQLAlchemy async / FastAPI / Alembic / pytest-asyncio；React 19 + TS + Vitest）。

**前置依赖：** 计划 ①（`db/query.py` 的 `IllustFilters`、`SelectionContext`、`GalleryFiltersContext`、`useGalleryQueryState`）。开始前确认 `src/pixiv_archive/db/query.py` 存在。

**约定：** 每个 Task 末尾提交。迁移文件手写（仓库现有迁移均为手写，无 autogenerate）。

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `src/pixiv_archive/db/migrations/versions/0004_storage_stats.py` | **新建**：加三列 |
| `src/pixiv_archive/db/models.py` | 改造：`Illust` 加 `byte_size` / `thumb_ready` / `animation_ready` |
| `src/pixiv_archive/media/storage.py` | 改造：`file_size` 辅助 |
| `src/pixiv_archive/download/worker.py` | 改造：写文件后累加字节与布尔列 |
| `src/pixiv_archive/web/routers/stats.py` | 改造：SQL 聚合 + 新字段 |
| `src/pixiv_archive/web/schemas.py` | 改造：`StatsOut` 新字段；`ExportRequest` 筛选字段 |
| `src/pixiv_archive/web/routers/export.py` | 改造：`use_filter` + 共享筛选 + 按作者分组 |
| `src/pixiv_archive/maintenance/__init__.py` | **新建**：维护服务（rebuild / repair / db-check） |
| `src/pixiv_archive/maintenance/service.py` | **新建**：三个操作的实现 |
| `src/pixiv_archive/web/routers/maintenance.py` | **新建**：三个 API |
| `src/pixiv_archive/web/app.py` | 改造：注册 maintenance 路由 |
| `src/pixiv_archive/cli.py` | 改造：`maintain` 子命令 |
| `frontend/src/api/types.ts` | 改造：`StatsOut` / `ExportRequest` / 维护响应类型 |
| `frontend/src/api/mutations.ts` | 改造：导出请求类型；维护 mutations |
| `frontend/src/pages/Export.tsx` | 改造：范围选择 + 分组选项 |
| `frontend/src/pages/Stats.tsx` | 改造：体积分布 + 可点击指标 + stale 提示 |
| `frontend/src/pages/Settings.tsx` | 改造：维护卡片 |
| `frontend/src/components/MaintenanceCard.tsx` | **新建** |
| `tests/test_web_routers_stats_export.py` | 改造：新统计字段、导出筛选用例 |
| `tests/test_web_maintenance.py` | **新建** |
| `tests/test_maintenance_service.py` | **新建** |
| `tests/test_download_worker.py` | 改造：新增体积列用例 |
| `tests/test_migrations.py` | 改造：断言新列存在 |

---

### Task 1: 迁移 0004 与模型字段

**Files:**
- Create: `src/pixiv_archive/db/migrations/versions/0004_storage_stats.py`
- Modify: `src/pixiv_archive/db/models.py:22-49`
- Test: `tests/test_migrations.py`（追加断言）

- [ ] **Step 1: 写失败的测试**

在 `tests/test_migrations.py` 末尾追加：

```python
def test_migration_adds_storage_stats_columns(tmp_path):
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
        columns = {row[1] for row in conn.execute("PRAGMA table_info(illust)")}
    finally:
        conn.close()
    assert {"byte_size", "thumb_ready", "animation_ready"} <= columns
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_migrations.py -q`
Expected: FAIL（缺少新列）

- [ ] **Step 3: 写迁移与模型**

`src/pixiv_archive/db/migrations/versions/0004_storage_stats.py`：

```python
"""storage stats columns

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("illust", sa.Column("byte_size", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("illust", sa.Column("thumb_ready", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column(
        "illust", sa.Column("animation_ready", sa.Boolean(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("illust", "animation_ready")
    op.drop_column("illust", "thumb_ready")
    op.drop_column("illust", "byte_size")
```

`src/pixiv_archive/db/models.py` 的 `Illust` 中，在 `page_downloaded_count` 之后插入：

```python
    byte_size: Mapped[int] = mapped_column(BigInteger, default=0)
    thumb_ready: Mapped[bool] = mapped_column(default=False)
    animation_ready: Mapped[bool] = mapped_column(default=False)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_migrations.py tests/test_db.py tests/test_models.py -q`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/db/migrations/versions/0004_storage_stats.py src/pixiv_archive/db/models.py tests/test_migrations.py
git commit -m "feat(db): add per-illust storage stats columns"
```

---

### Task 2: worker 维护体积与就绪布尔列

**Files:**
- Modify: `src/pixiv_archive/media/storage.py`（追加辅助函数）
- Modify: `src/pixiv_archive/download/worker.py:319-373`
- Test: `tests/test_download_worker.py`（追加用例）

- [ ] **Step 1: 追加失败测试**

在 `tests/test_download_worker.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_download_worker.py -q`
Expected: 新用例 FAIL（`byte_size` 恒为 0 或 `AttributeError`）

- [ ] **Step 3: 实现**

`src/pixiv_archive/media/storage.py` 末尾追加：

```python
def file_size(path: Path) -> int:
    """Size in bytes, or 0 when the path does not exist."""
    try:
        return path.stat().st_size
    except OSError:
        return 0
```

`src/pixiv_archive/download/worker.py` 改造点（保持其他逻辑不变）：

1. import 增加：

```python
from pixiv_archive.media.storage import WorksStorage, atomic_write_bytes, file_size
```

2. 新增私有方法（放在 `_mark_page_done` 之前）：

```python
    async def _recompute_storage_stats(self, pid: int) -> None:
        """Recompute byte size and ready flags from the on-disk layout.

        Performed after every successful write; the per-work directory is
        small, so a targeted rescan is cheaper and more robust than delta
        bookkeeping across retries.
        """
        work = self._storage.work_dir(pid)
        total = 0
        original_dir = work / "original"
        if original_dir.is_dir():
            total += sum(file_size(path) for path in original_dir.iterdir() if path.is_file())
        thumb = work / "thumb.webp"
        animation = work / "animation.mp4"
        zip_path = work / "source.zip"
        total += file_size(thumb) + file_size(animation) + file_size(zip_path)
        async with self._db.session() as session:
            await session.execute(
                update(Illust)
                .where(Illust.pid == pid)
                .values(
                    byte_size=total,
                    thumb_ready=thumb.is_file(),
                    animation_ready=animation.is_file(),
                )
            )
            await session.commit()
```

3. 在 `_handle_image` 成功写入后（`atomic_write_bytes(dest, data)` 之后的锁内）调用：把

```python
            atomic_write_bytes(dest, data)
        await self._mark_page_done(pid, target)
```

改为

```python
            atomic_write_bytes(dest, data)
            await self._recompute_storage_stats(pid)
        await self._mark_page_done(pid, target)
```

4. `_ensure_first_original` 中 `atomic_write_bytes(destination, data)` 之后加：

```python
            await self._recompute_storage_stats(pid)
```

5. `_handle_thumb` 中生成成功后加：

```python
        generated = await asyncio.to_thread(generate_thumb, source, dest)
        if generated:
            await self._recompute_storage_stats(pid)
            report.thumbs_done += 1
        return generated, False
```

6. `_handle_ugoira_zip` 中成功返回前加：

```python
        ok = await self._ensure_ugoira_zip(pid)
        if ok:
            await self._recompute_storage_stats(pid)
            report.ugoira_done += 1
        return ok, False
```

7. `_handle_ugoira_mp4` 中 `if ok:` 分支加：

```python
        if ok:
            await self._recompute_storage_stats(pid)
            report.ugoira_done += 1
            return True, False
```

**注意：** `_recompute_storage_stats` 使用独立 session，而 `_handle_image` 在其后调用 `_mark_page_done`（也开 own session）。两者不会同时持有写锁（顺序调用），无死锁风险。SQLite WAL 模式下并发安全。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_download_worker.py tests/test_media.py -q`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/media/storage.py src/pixiv_archive/download/worker.py tests/test_download_worker.py
git commit -m "feat(download): track per-work byte size and ready flags"
```

---

### Task 3: 统计服务（rebuild / repair / db-check）

**Files:**
- Create: `src/pixiv_archive/maintenance/__init__.py`
- Create: `src/pixiv_archive/maintenance/service.py`
- Test: `tests/test_maintenance_service.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_maintenance_service.py
from pathlib import Path

import pytest
from sqlalchemy import select

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust, IllustPage
from pixiv_archive.maintenance.service import (
    db_check,
    preview_repair_download_state,
    rebuild_storage_stats,
    repair_download_state,
)


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "m.db")
    await database.create_all()
    yield database
    await database.dispose()


def _write_work(works: Path, pid: int, *, pages: int = 1, thumb: bool = True) -> int:
    original = works / str(pid) / "original"
    original.mkdir(parents=True)
    total = 0
    for index in range(pages):
        payload = b"x" * (100 + index)
        (original / f"{index:03d}_p{index}.jpg").write_bytes(payload)
        total += len(payload)
    if thumb:
        payload = b"t" * 50
        (works / str(pid) / "thumb.webp").write_bytes(payload)
        total += len(payload)
    return total


async def _seed(db, pid: int, *, pages: int = 1) -> None:
    async with db.session() as session:
        if await session.get(Author, 1) is None:
            session.add(Author(id=1, name="a"))
        session.add(Illust(pid=pid, title=f"t{pid}", author_id=1, page_count=pages))
        for index in range(pages):
            session.add(
                IllustPage(
                    pid=pid,
                    page_index=index,
                    original_url=f"https://i.pximg.net/{pid}_p{index}.jpg",
                    ext=".jpg",
                )
            )
        await session.commit()
    async with db.session() as session:
        session.add(Bookmark(pid=pid, restrict="public", rank=pid, state="active"))
        await session.commit()


async def test_rebuild_storage_stats_sets_size_and_flags(db, tmp_path):
    await _seed(db, 1, pages=2)
    await _seed(db, 2, pages=1)
    works = tmp_path / "works"
    expected1 = _write_work(works, 1, pages=2, thumb=True)
    expected2 = _write_work(works, 2, pages=1, thumb=False)

    async with db.session() as session:
        result = await rebuild_storage_stats(session, works)
    assert result["works"] == 2

    async with db.session() as session:
        rows = {
            illust.pid: illust
            for illust in (await session.execute(select(Illust))).scalars()
        }
    assert rows[1].byte_size == expected1
    assert rows[1].thumb_ready is True
    assert rows[2].byte_size == expected2
    assert rows[2].thumb_ready is False


async def test_repair_preview_and_apply(db, tmp_path):
    await _seed(db, 5, pages=2)
    works = tmp_path / "works"
    _write_work(works, 5, pages=1, thumb=False)
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update()
            .where(Illust.pid == 5)
            .values(has_original=True, page_downloaded_count=2)
        )
        await session.execute(
            IllustPage.__table__.update()
            .where(IllustPage.pid == 5)
            .values(download_state="done")
        )
        await session.commit()

    async with db.session() as session:
        preview = await preview_repair_download_state(session, works)
    assert preview == {"pages_to_reset": 1, "works_to_fix": 1}

    async with db.session() as session:
        await repair_download_state(session, works)

    async with db.session() as session:
        pages = (
            (await session.execute(select(IllustPage).order_by(IllustPage.page_index)))
            .scalars()
            .all()
        )
        illust = (await session.execute(select(Illust))).scalar_one()
    assert [page.download_state for page in pages] == ["done", "pending"]
    assert illust.has_original is False
    assert illust.page_downloaded_count == 1


async def test_db_check_reports_orphans_and_mismatch(db, tmp_path):
    await _seed(db, 6, pages=1)
    works = tmp_path / "works"
    # DB says downloaded, but no files exist on disk
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update().where(Illust.pid == 6).values(has_original=True)
        )
        await session.commit()

    async with db.session() as session:
        report = await db_check(session, works)
    assert report["ok"] is False
    kinds = {issue["kind"] for issue in report["issues"]}
    assert "missing_files" in kinds
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_maintenance_service.py -q`
Expected: FAIL（`ModuleNotFoundError: pixiv_archive.maintenance`）

- [ ] **Step 3: 实现**

`src/pixiv_archive/maintenance/__init__.py`：

```python
from pixiv_archive.maintenance.service import (
    db_check,
    preview_repair_download_state,
    rebuild_storage_stats,
    repair_download_state,
)

__all__ = [
    "db_check",
    "preview_repair_download_state",
    "rebuild_storage_stats",
    "repair_download_state",
]
```

`src/pixiv_archive/maintenance/service.py`：

```python
"""Maintenance operations that reconcile the DB with the works directory."""

from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Bookmark, Illust, IllustPage, IllustTag
from pixiv_archive.media.storage import file_size

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def _work_files(works: Path, pid: int) -> tuple[list[Path], Path, Path, Path]:
    work = works / str(pid)
    original = work / "original"
    originals = (
        sorted(path for path in original.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
        if original.is_dir()
        else []
    )
    return originals, work / "thumb.webp", work / "animation.mp4", work / "source.zip"


async def rebuild_storage_stats(session: AsyncSession, works: Path) -> dict[str, int]:
    """Recompute byte_size / thumb_ready / animation_ready for every illust."""
    pids = list((await session.execute(select(Illust.pid))).scalars().all())
    total_bytes = 0
    for pid in pids:
        originals, thumb, animation, zip_path = _work_files(works, pid)
        size = sum(file_size(path) for path in (*originals, thumb, animation, zip_path))
        total_bytes += size
        await session.execute(
            update(Illust)
            .where(Illust.pid == pid)
            .values(
                byte_size=size,
                thumb_ready=thumb.is_file(),
                animation_ready=animation.is_file(),
            )
        )
    await session.commit()
    return {"works": len(pids), "total_bytes": total_bytes}


async def preview_repair_download_state(session: AsyncSession, works: Path) -> dict[str, int]:
    """Count what :func:`repair_download_state` would change (no writes)."""
    pages_to_reset = 0
    works_to_fix = 0
    rows = (
        await session.execute(
            select(IllustPage.pid, IllustPage.page_index, IllustPage.download_state)
        )
    ).all()
    by_pid: dict[int, list[tuple[int, str]]] = {}
    for pid, page_index, state in rows:
        by_pid.setdefault(pid, []).append((page_index, state))
    for pid, pages in by_pid.items():
        originals, *_ = _work_files(works, pid)
        present = {path.name.split("_", 1)[0] for path in originals}
        changed = 0
        for page_index, state in pages:
            exists = f"{page_index:03d}" in present
            if state == "done" and not exists:
                changed += 1
            elif state != "done" and exists:
                changed += 1
        if changed:
            pages_to_reset += changed
            works_to_fix += 1
    return {"pages_to_reset": pages_to_reset, "works_to_fix": works_to_fix}


async def repair_download_state(session: AsyncSession, works: Path) -> dict[str, int]:
    """Reconcile page download_state / counts / has_original with the disk."""
    fixed_pages = 0
    touched_works = 0
    rows = (
        await session.execute(
            select(IllustPage.pid, IllustPage.page_index, IllustPage.download_state)
        )
    ).all()
    by_pid: dict[int, list[tuple[int, str]]] = {}
    for pid, page_index, state in rows:
        by_pid.setdefault(pid, []).append((page_index, state))
    for pid, pages in by_pid.items():
        originals, *_ = _work_files(works, pid)
        present = {path.name.split("_", 1)[0] for path in originals}
        for page_index, state in pages:
            exists = f"{page_index:03d}" in present
            if state == "done" and not exists:
                await session.execute(
                    update(IllustPage)
                    .where(IllustPage.pid == pid, IllustPage.page_index == page_index)
                    .values(download_state="pending", last_error="file missing on disk")
                )
                fixed_pages += 1
            elif state != "done" and exists:
                await session.execute(
                    update(IllustPage)
                    .where(IllustPage.pid == pid, IllustPage.page_index == page_index)
                    .values(download_state="done", last_error=None)
                )
                fixed_pages += 1
        total = len(pages)
        done = len(present)
        await session.execute(
            update(Illust)
            .where(Illust.pid == pid)
            .values(page_downloaded_count=done, has_original=(done == total and total > 0))
        )
        touched_works += 1
    await session.commit()
    return {"pages_fixed": fixed_pages, "works_fixed": touched_works}


async def db_check(session: AsyncSession, works: Path) -> dict[str, Any]:
    """Read-only integrity report: DB internals plus DB/disk mismatches."""
    issues: list[dict[str, Any]] = []

    integrity = (await session.execute(text("PRAGMA integrity_check"))).scalar_one()
    if integrity != "ok":
        issues.append({"kind": "integrity", "count": 1, "samples": [str(integrity)]})

    for name, stmt, sample in (
        (
            "orphan_bookmark",
            select(Bookmark.pid).where(
                ~Bookmark.pid.in_(select(Illust.pid))
            ),
            Bookmark.pid,
        ),
        (
            "orphan_page",
            select(IllustPage.pid).where(
                ~IllustPage.pid.in_(select(Illust.pid))
            ),
            IllustPage.pid,
        ),
        (
            "orphan_illust_tag",
            select(IllustTag.pid).where(
                ~IllustTag.pid.in_(select(Illust.pid))
            ),
            IllustTag.pid,
        ),
    ):
        rows = (await session.execute(stmt)).all()
        if rows:
            issues.append(
                {"kind": name, "count": len(rows), "samples": [int(row[0]) for row in rows[:5]]}
            )

    duplicate_rank = (
        await session.execute(
            select(Bookmark.rank, func.count())
            .where(Bookmark.state == "active")
            .group_by(Bookmark.rank)
            .having(func.count() > 1)
        )
    ).all()
    if duplicate_rank:
        issues.append(
            {
                "kind": "duplicate_rank",
                "count": len(duplicate_rank),
                "samples": [int(rank) for rank, _ in duplicate_rank[:5]],
            }
        )

    missing_files = 0
    missing_samples: list[int] = []
    mismatch_rows = (
        await session.execute(
            select(Illust.pid).where(Illust.has_original.is_(True))
        )
    ).scalars().all()
    for pid in mismatch_rows:
        originals, *_ = _work_files(works, pid)
        if not originals:
            missing_files += 1
            if len(missing_samples) < 5:
                missing_samples.append(int(pid))
    if missing_files:
        issues.append(
            {"kind": "missing_files", "count": missing_files, "samples": missing_samples}
        )

    return {"ok": not issues, "issues": issues}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_maintenance_service.py -q`
Expected: 全部通过

- [ ] **Step 5: lint / mypy**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy`
Expected: 无错误

- [ ] **Step 6: Commit**

```bash
git add src/pixiv_archive/maintenance tests/test_maintenance_service.py
git commit -m "feat(maintenance): add storage stats, repair and db-check services"
```

---

### Task 4: 维护 API 与 CLI

**Files:**
- Create: `src/pixiv_archive/web/routers/maintenance.py`
- Modify: `src/pixiv_archive/web/app.py:56-62`
- Modify: `src/pixiv_archive/web/schemas.py`（维护响应模型）
- Modify: `src/pixiv_archive/cli.py`
- Test: `tests/test_web_maintenance.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_web_maintenance.py
import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust, IllustPage
from pixiv_archive.web.auth import SessionSigner
from pixiv_archive.web.routers.maintenance import router as maintenance_router
from pixiv_archive.web.routers.tasks import router as tasks_router
from pixiv_archive.web.tasks import TaskManager


@pytest.fixture
async def client(tmp_path):
    database = Database(tmp_path / "mt.db")
    await database.create_all()
    works = tmp_path / "works"
    original = works / "1" / "original"
    original.mkdir(parents=True)
    (original / "000_p0.jpg").write_bytes(b"a" * 10)
    (works / "1" / "thumb.webp").write_bytes(b"t" * 5)

    async with database.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=1, title="t", author_id=1, page_count=1))
        await session.commit()
    async with database.session() as session:
        session.add(
            IllustPage(pid=1, page_index=0, original_url="x", ext=".jpg", download_state="done")
        )
        session.add(Bookmark(pid=1, restrict="public", rank=0, state="active"))
        await session.commit()

    app = FastAPI()
    app.state.db = database
    app.state.session_signer = SessionSigner("secret")
    app.state.tasks = TaskManager()
    app.state.events = app.state.tasks.events
    app.state.settings = type("S", (), {"works_dir": works, "data_dir": tmp_path})()
    app.include_router(maintenance_router)
    app.include_router(tasks_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as http:
        http.cookies.set("session", app.state.session_signer.sign("ok"))
        yield http
    await database.dispose()


async def _wait(client) -> dict:
    tasks = client._transport.app.state.tasks  # type: ignore[union-attr]
    for _ in range(100):
        await asyncio.sleep(0.02)
        listing = (await client.get("/api/tasks")).json()
        if listing and listing[0]["status"] != "running":
            return listing[0]
    raise AssertionError("task did not finish")


async def test_rebuild_stats_task_updates_columns(client):
    response = await client.post("/api/maintenance/rebuild-stats")
    assert response.status_code == 202
    record = await _wait(client)
    assert record["kind"] == "maintenance"
    assert record["status"] == "completed"
    assert record["detail"]["works"] == 1

    from sqlalchemy import select

    database = client._transport.app.state.db  # type: ignore[union-attr]
    async with database.session() as session:
        illust = (await session.execute(select(Illust))).scalar_one()
    assert illust.byte_size == 15
    assert illust.thumb_ready is True


async def test_repair_preview_and_run(client):
    preview = await client.get("/api/maintenance/repair-download-state/preview")
    assert preview.status_code == 200
    assert preview.json()["works_to_fix"] == 0

    response = await client.post("/api/maintenance/repair-download-state")
    assert response.status_code == 202
    record = await _wait(client)
    assert record["status"] == "completed"


async def test_db_check_returns_report(client):
    response = await client.post("/api/maintenance/db-check")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["issues"] == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_maintenance.py -q`
Expected: FAIL（`ModuleNotFoundError: pixiv_archive.web.routers.maintenance`）

- [ ] **Step 3: 实现 API**

`src/pixiv_archive/web/schemas.py` 追加：

```python
class MaintenanceResultOut(BaseModel):
    ok: bool
    issues: list[dict[str, Any]] = Field(default_factory=list)
```

`src/pixiv_archive/web/routers/maintenance.py`：

```python
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.maintenance.service import (
    db_check,
    preview_repair_download_state,
    rebuild_storage_stats,
    repair_download_state,
)
from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_session, get_settings, get_tasks
from pixiv_archive.web.schemas import MaintenanceResultOut, TaskOut
from pixiv_archive.web.tasks import TaskContext, TaskManager

router = APIRouter(
    prefix="/api/maintenance",
    tags=["maintenance"],
    dependencies=[Depends(require_auth)],  # noqa: B008
)


def _works_dir(request: Request) -> Path:
    return get_settings(request).works_dir


@router.post("/rebuild-stats", status_code=status.HTTP_202_ACCEPTED, response_model=TaskOut)
async def start_rebuild_stats(
    request: Request,
    tasks: Annotated[TaskManager, Depends(get_tasks)],  # noqa: B008
) -> TaskOut:
    works = _works_dir(request)
    database = request.app.state.db

    async def run(context: TaskContext) -> dict[str, Any]:
        async with database.session() as session:
            context.progress("rebuild", 0, 1, "重建存储统计")
            result = await rebuild_storage_stats(session, works)
            context.progress("rebuild", 1, 1, "完成")
            return dict(result)

    try:
        task_id = tasks.start("maintenance", run)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record = tasks.get(task_id)
    assert record is not None
    return TaskOut(**record.to_dict())


@router.get("/repair-download-state/preview")
async def repair_preview(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],  # noqa: B008
) -> dict[str, int]:
    return await preview_repair_download_state(session, _works_dir(request))


@router.post(
    "/repair-download-state", status_code=status.HTTP_202_ACCEPTED, response_model=TaskOut
)
async def start_repair(
    request: Request,
    tasks: Annotated[TaskManager, Depends(get_tasks)],  # noqa: B008
) -> TaskOut:
    works = _works_dir(request)
    database = request.app.state.db

    async def run(context: TaskContext) -> dict[str, Any]:
        async with database.session() as session:
            context.progress("repair", 0, 1, "修复下载状态")
            result = await repair_download_state(session, works)
            context.progress("repair", 1, 1, "完成")
            return dict(result)

    try:
        task_id = tasks.start("maintenance", run)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record = tasks.get(task_id)
    assert record is not None
    return TaskOut(**record.to_dict())


@router.post("/db-check", response_model=MaintenanceResultOut)
async def run_db_check(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],  # noqa: B008
) -> MaintenanceResultOut:
    report = await db_check(session, _works_dir(request))
    return MaintenanceResultOut(**report)
```

`src/pixiv_archive/web/app.py`：在 import 行加入 `maintenance`，并在 `app.include_router(export.router)` 之后加：

```python
    app.include_router(maintenance.router)
```

import 行改为：

```python
from pixiv_archive.web.routers import auth, export, gallery, illust, maintenance, stats, tasks
```

- [ ] **Step 4: 加 CLI `maintain` 子命令**

`src/pixiv_archive/cli.py` 改造：

1. `build_parser()` 中在 `download` parser 之后增加：

```python
    maintain = subparsers.add_parser("maintain", help="reconcile DB with the works directory")
    maintain.add_argument(
        "action",
        choices=("rebuild-stats", "repair-download-state", "db-check"),
        help="maintenance operation",
    )
    maintain.add_argument(
        "--yes",
        action="store_true",
        help="apply repair-download-state without prompting",
    )
```

2. 新增 `run_maintain`：

```python
async def run_maintain(argv: list[str], settings: Settings | None = None) -> int:
    from pixiv_archive.db.engine import Database
    from pixiv_archive.maintenance.service import (
        db_check,
        preview_repair_download_state,
        rebuild_storage_stats,
        repair_download_state,
    )
    from pixiv_archive.sync.factory import _ensure_schema

    parser = build_parser()
    args = parser.parse_args(argv)
    settings = settings or Settings()
    settings.ensure_dirs()

    await _ensure_schema(settings)
    db = Database(settings.db_path)
    try:
        async with db.session() as session:
            if args.action == "rebuild-stats":
                result = await rebuild_storage_stats(session, settings.works_dir)
                print(f"重建完成：{result}")
                return 0
            if args.action == "db-check":
                report = await db_check(session, settings.works_dir)
                print("体检通过" if report["ok"] else f"发现 {len(report['issues'])} 类问题：")
                for issue in report["issues"]:
                    print(f"  - {issue['kind']}: {issue['count']} 例，样本 {issue['samples']}")
                return 0
            preview = await preview_repair_download_state(session, settings.works_dir)
            print(f"预览：{preview}")
            if not args.yes:
                print("如需执行请加 --yes")
                return 0
            result = await repair_download_state(session, settings.works_dir)
            print(f"修复完成：{result}")
            return 0
    finally:
        await db.dispose()
```

3. `main()` 中的命令分派改为：

```python
    if argv[0] not in ("sync", "download", "maintain"):
        build_parser().error(f"unknown command: {argv[0]}")
    if argv[0] == "download":
        return asyncio.run(run_download(argv))
    if argv[0] == "maintain":
        return asyncio.run(run_maintain(argv))
    return asyncio.run(run_sync(argv))
```

- [ ] **Step 4b: 补 CLI 测试**

在 `tests/test_cli.py` 末尾追加：

```python
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
    db = Database(settings.db_path)
    await db.create_all()
    await db.dispose()

    exit_code = await run_maintain(["maintain", "rebuild-stats"], settings=settings)
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "重建完成" in captured.out


async def test_run_maintain_repair_requires_yes(monkeypatch, tmp_path, capsys):
    from pixiv_archive.cli import run_maintain

    settings = _settings(monkeypatch, tmp_path)
    db = Database(settings.db_path)
    await db.create_all()
    await db.dispose()

    exit_code = await run_maintain(["maintain", "repair-download-state"], settings=settings)
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "预览" in captured.out
    assert "--yes" in captured.out
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_web_maintenance.py tests/test_cli.py -q`
Expected: 全部通过

- [ ] **Step 6: 全量后端校验**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy && uv run pytest -q`
Expected: 全部通过

- [ ] **Step 7: Commit**

```bash
git add src/pixiv_archive/web/routers/maintenance.py src/pixiv_archive/web/app.py src/pixiv_archive/web/schemas.py src/pixiv_archive/cli.py tests/test_web_maintenance.py tests/test_cli.py
git commit -m "feat(web): expose maintenance rebuild, repair and db-check"
```

---

### Task 5: `/api/stats` 改为 SQL 聚合

**Files:**
- Modify: `src/pixiv_archive/web/schemas.py`（`StatsOut`）
- Modify: `src/pixiv_archive/web/routers/stats.py`
- Test: `tests/test_web_routers_stats_export.py`（改造 + 追加）

- [ ] **Step 1: 改造测试**

`tests/test_web_routers_stats_export.py` 的 `test_stats_endpoint` 替换为：

```python
async def test_stats_endpoint(client):
    response = await client.get("/api/stats")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_illusts"] == 2
    assert payload["total_pages"] == 2
    assert payload["downloaded_pages"] == 1
    assert payload["pending_pages"] == 1
    assert payload["by_type"] == {"ugoira": 1, "illust": 1}
    assert payload["by_restrict"] == {"public": 1, "private": 1}
    assert payload["ugoira_count"] == 1
    assert payload["animation_ready"] == 0
    assert payload["total_bytes"] == 0
    assert payload["stats_stale"] is True
    assert payload["by_type_bytes"] == {"ugoira": 0, "illust": 0}


async def test_stats_reflects_rebuilt_columns(client):
    from sqlalchemy import select

    from pixiv_archive.db.models import Illust

    database = client._transport.app.state.db  # type: ignore[union-attr]
    async with database.session() as session:
        await session.execute(
            Illust.__table__.update()
            .where(Illust.pid == 10)
            .values(byte_size=1234, thumb_ready=True, animation_ready=True)
        )
        await session.commit()

    response = await client.get("/api/stats")
    payload = response.json()
    assert payload["total_bytes"] == 1234
    assert payload["thumbs_ready"] == 1
    assert payload["animation_ready"] == 1
    assert payload["stats_stale"] is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_routers_stats_export.py -q`
Expected: FAIL（`animation_ready` 仍为 1、缺 `stats_stale`）

- [ ] **Step 3: 实现**

`src/pixiv_archive/web/schemas.py` 的 `StatsOut` 替换为：

```python
class StatsOut(BaseModel):
    total_illusts: int
    unbookmarked: int
    total_pages: int
    downloaded_pages: int
    failed_pages: int
    pending_pages: int
    total_bytes: int
    thumbs_ready: int
    ugoira_count: int
    animation_ready: int
    by_type: dict[str, int]
    by_restrict: dict[str, int]
    by_type_bytes: dict[str, int]
    by_restrict_bytes: dict[str, int]
    top_authors_bytes: list[dict[str, Any]]
    stats_stale: bool
```

`src/pixiv_archive/web/routers/stats.py` 替换为（删除 `_sum_sizes` 与文件系统扫描）：

```python
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Author, Bookmark, Illust, IllustPage, UgoiraMeta
from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_session
from pixiv_archive.web.schemas import StatsOut

router = APIRouter(prefix="/api", tags=["stats"], dependencies=[Depends(require_auth)])  # noqa: B008


@router.get("/stats", response_model=StatsOut)
async def stats(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> StatsOut:
    total_illusts = (
        await session.execute(
            select(func.count()).select_from(Illust).where(Illust.state == "active")
        )
    ).scalar_one()
    unbookmarked = (
        await session.execute(
            select(func.count()).select_from(Bookmark).where(Bookmark.state == "unbookmarked")
        )
    ).scalar_one()
    page_counts: dict[str, int] = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(
                select(IllustPage.download_state, func.count()).group_by(IllustPage.download_state)
            )
        ).all()
    }
    by_type: dict[str, int] = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(select(Illust.type, func.count()).group_by(Illust.type))
        ).all()
    }
    by_restrict: dict[str, int] = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(
                select(Bookmark.restrict, func.count()).group_by(Bookmark.restrict)
            )
        ).all()
    }
    ugoira_count = (
        await session.execute(select(func.count()).select_from(UgoiraMeta))
    ).scalar_one()
    total_bytes = (
        await session.execute(select(func.coalesce(func.sum(Illust.byte_size), 0)))
    ).scalar_one()
    thumbs_ready = (
        await session.execute(select(func.count()).where(Illust.thumb_ready.is_(True)))
    ).scalar_one()
    animation_ready = (
        await session.execute(select(func.count()).where(Illust.animation_ready.is_(True)))
    ).scalar_one()

    by_type_bytes = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(
                select(Illust.type, func.coalesce(func.sum(Illust.byte_size), 0)).group_by(
                    Illust.type
                )
            )
        ).all()
    }
    by_restrict_bytes = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(
                select(Bookmark.restrict, func.coalesce(func.sum(Illust.byte_size), 0))
                .join(Illust, Illust.pid == Bookmark.pid)
                .group_by(Bookmark.restrict)
            )
        ).all()
    }
    top_authors_bytes = [
        {
            "id": int(row[0]),
            "name": str(row[1]),
            "bytes": int(row[2]),
            "illust_count": int(row[3]),
        }
        for row in (
            await session.execute(
                select(
                    Author.id,
                    Author.name,
                    func.coalesce(func.sum(Illust.byte_size), 0).label("bytes"),
                    func.count(Illust.pid),
                )
                .join(Illust, Illust.author_id == Author.id)
                .group_by(Author.id)
                .order_by(func.coalesce(func.sum(Illust.byte_size), 0).desc())
                .limit(10)
            )
        ).all()
    ]
    stale = (
        await session.execute(
            select(func.count())
            .select_from(Illust)
            .where(Illust.has_original.is_(True), Illust.byte_size == 0)
        )
    ).scalar_one()

    return StatsOut(
        total_illusts=total_illusts,
        unbookmarked=unbookmarked,
        total_pages=sum(page_counts.values()),
        downloaded_pages=page_counts.get("done", 0),
        failed_pages=page_counts.get("failed", 0),
        pending_pages=page_counts.get("pending", 0),
        total_bytes=int(total_bytes),
        thumbs_ready=int(thumbs_ready),
        ugoira_count=ugoira_count,
        animation_ready=int(animation_ready),
        by_type=by_type,
        by_restrict=by_restrict,
        by_type_bytes=by_type_bytes,
        by_restrict_bytes=by_restrict_bytes,
        top_authors_bytes=top_authors_bytes,
        stats_stale=bool(stale),
    )
```

**注意：** 移除了 `case` 导入（上面代码块中未使用；若实现时保留 `case` 请一并删除，避免 ruff F401）。同时 `stats.py` 不再需要 `Path` 与 `get_settings`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_routers_stats_export.py -q`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/web/schemas.py src/pixiv_archive/web/routers/stats.py tests/test_web_routers_stats_export.py
git commit -m "feat(web): compute stats with SQL aggregates and storage columns"
```

---

### Task 6: 导出支持按筛选与按作者分组

**Files:**
- Modify: `src/pixiv_archive/web/schemas.py`（`ExportRequest`）
- Modify: `src/pixiv_archive/web/routers/export.py`
- Test: `tests/test_web_routers_stats_export.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `tests/test_web_routers_stats_export.py` 末尾追加：

```python
async def test_export_by_filter_excludes_deleted(client):
    import io
    import zipfile

    from pixiv_archive.db.models import Illust

    database = client._transport.app.state.db  # type: ignore[union-attr]
    async with database.session() as session:
        session.add(Illust(pid=40, title="gone", author_id=1, state="deleted"))
        await session.commit()
    async with database.session() as session:
        session.add(Bookmark(pid=40, restrict="public", rank=4096, state="active"))
        await session.commit()

    response = await client.post(
        "/api/export",
        json={"include_metadata": True, "include_originals": False, "use_filter": True},
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    await client._transport.app.state.tasks.wait(task_id)  # type: ignore[union-attr]
    download = await client.get(f"/api/export/{task_id}/download")
    archive = zipfile.ZipFile(io.BytesIO(download.content))
    names = archive.namelist()
    assert "metadata/10.json" in names
    assert "metadata/20.json" in names
    assert "metadata/40.json" not in names


async def test_export_by_filter_applies_downloaded_flag(client):
    import io
    import zipfile

    response = await client.post(
        "/api/export",
        json={
            "include_metadata": True,
            "include_originals": False,
            "use_filter": True,
            "downloaded": True,
        },
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    await client._transport.app.state.tasks.wait(task_id)  # type: ignore[union-attr]
    download = await client.get(f"/api/export/{task_id}/download")
    archive = zipfile.ZipFile(io.BytesIO(download.content))
    names = archive.namelist()
    assert "metadata/10.json" in names
    assert "metadata/20.json" not in names


async def test_export_by_filter_with_no_matches_is_422(client):
    response = await client.post(
        "/api/export",
        json={"include_metadata": True, "use_filter": True, "q": "no-such-title"},
    )
    assert response.status_code == 422


async def test_export_groups_by_author_when_requested(client):
    import io
    import zipfile

    response = await client.post(
        "/api/export",
        json={
            "include_metadata": True,
            "include_originals": False,
            "pids": [10, 20],
            "group_by_author": True,
        },
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    await client._transport.app.state.tasks.wait(task_id)  # type: ignore[union-attr]
    download = await client.get(f"/api/export/{task_id}/download")
    archive = zipfile.ZipFile(io.BytesIO(download.content))
    names = archive.namelist()
    assert "1/10.json" in names
    assert "1/20.json" in names
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_routers_stats_export.py -q`
Expected: 新用例 FAIL（`use_filter` / `group_by_author` 未定义）

- [ ] **Step 3: 实现**

`src/pixiv_archive/web/schemas.py` 的 `ExportRequest` 替换为：

```python
class ExportRequest(BaseModel):
    include_metadata: bool = True
    include_originals: bool = False
    pids: list[int] = Field(default_factory=list)
    x_restrict: int | None = None
    only_downloaded: bool = False
    group_by_author: bool = False
    # filter-mode export (same fields as the gallery filters)
    use_filter: bool = False
    tags: list[str] = Field(default_factory=list)
    author_ids: list[int] = Field(default_factory=list)
    q: str | None = None
    type: str | None = None
    downloaded: bool | None = None
    restrict: str | None = None
    only_unbookmarked: bool = False
    include_unbookmarked: bool = False
    page_min: int | None = None
    page_max: int | None = None
    bookmarks_min: int | None = None
    bookmarks_max: int | None = None
    views_min: int | None = None
    views_max: int | None = None
```

`src/pixiv_archive/web/routers/export.py` 的 `_selected_pids` 替换为：

```python
async def _selected_pids(session: AsyncSession, payload: ExportRequest) -> list[int]:
    if payload.pids:
        stmt = (
            select(Illust.pid).join(Bookmark, Bookmark.pid == Illust.pid).order_by(Bookmark.rank)
        )
        stmt = stmt.where(Illust.pid.in_(payload.pids))
        if payload.x_restrict is not None:
            stmt = stmt.where(Illust.x_restrict == payload.x_restrict)
        if payload.only_downloaded:
            stmt = stmt.where(Illust.has_original.is_(True))
        return list((await session.execute(stmt)).scalars().all())

    if payload.use_filter:
        from pixiv_archive.db.query import IllustFilters, build_filtered_pids

        filters = IllustFilters(
            tags=payload.tags,
            author_ids=payload.author_ids,
            q=payload.q,
            type=payload.type,
            x_restrict=payload.x_restrict,
            downloaded=payload.downloaded,
            restrict=payload.restrict,
            only_unbookmarked=payload.only_unbookmarked,
            include_unbookmarked=payload.include_unbookmarked,
            page_min=payload.page_min,
            page_max=payload.page_max,
            bookmarks_min=payload.bookmarks_min,
            bookmarks_max=payload.bookmarks_max,
            views_min=payload.views_min,
            views_max=payload.views_max,
        )
        if payload.only_downloaded and filters.downloaded is None:
            filters.downloaded = True
        return list((await session.execute(build_filtered_pids(filters))).scalars().all())

    stmt = select(Illust.pid).join(Bookmark, Bookmark.pid == Illust.pid).order_by(Bookmark.rank)
    if payload.x_restrict is not None:
        stmt = stmt.where(Illust.x_restrict == payload.x_restrict)
    if payload.only_downloaded:
        stmt = stmt.where(Illust.has_original.is_(True))
    return list((await session.execute(stmt)).scalars().all())
```

在 `run` 闭包中，metadata 写入路径支持按作者分组：

```python
                    if payload.include_metadata:
                        prefix = f"{illust.author_id}/" if payload.group_by_author else "metadata/"
                        suffix = f"{pid}.json" if payload.group_by_author else f"{pid}.json"
                        archive.writestr(
                            f"{prefix}{suffix}",
                            json.dumps(
                                _metadata_payload(illust, author, []),
                                ensure_ascii=False,
                                indent=2,
                            ),
                        )
```

原 originals 路径 `f"{pid:012d}/original/{relative}"` 在 `group_by_author` 时改为 `f"{illust.author_id}/{pid:012d}/original/{relative}"`（用条件表达式）。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_routers_stats_export.py -q`
Expected: 全部通过（含既有 `test_export_includes_deleted_works` 仍通过：pids 路径不受影响）

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/web/schemas.py src/pixiv_archive/web/routers/export.py tests/test_web_routers_stats_export.py
git commit -m "feat(web): export by selection, filter or author grouping"
```

---

### Task 7: 前端统计页与维护卡片

**Files:**
- Modify: `frontend/src/api/types.ts`（`StatsOut`、`ExportRequest`、维护类型）
- Modify: `frontend/src/api/queries.ts`（`useStats` 不变）
- Modify: `frontend/src/api/mutations.ts`（导出 payload、维护 mutations）
- Modify: `frontend/src/pages/Stats.tsx`
- Modify: `frontend/src/pages/Settings.tsx`
- Create: `frontend/src/components/MaintenanceCard.tsx`
- Test: `frontend/src/pages/Stats.test.tsx`（改造）

- [ ] **Step 1: 改造前端类型与测试**

`frontend/src/api/types.ts` 的 `StatsOut` 替换为：

```ts
export interface StatsOut {
  total_illusts: number;
  unbookmarked: number;
  total_pages: number;
  downloaded_pages: number;
  failed_pages: number;
  pending_pages: number;
  total_bytes: number;
  thumbs_ready: number;
  ugoira_count: number;
  animation_ready: number;
  by_type: Record<string, number>;
  by_restrict: Record<string, number>;
  by_type_bytes: Record<string, number>;
  by_restrict_bytes: Record<string, number>;
  top_authors_bytes: { id: number; name: string; bytes: number; illust_count: number }[];
  stats_stale: boolean;
}
```

`ExportRequest` 追加：

```ts
export interface ExportRequest {
  include_metadata: boolean;
  include_originals: boolean;
  pids?: number[];
  x_restrict?: number;
  only_downloaded?: boolean;
  group_by_author?: boolean;
  use_filter?: boolean;
  tags?: string[];
  author_ids?: number[];
  q?: string;
  type?: "illust" | "ugoira";
  downloaded?: boolean;
  restrict?: "public" | "private";
  only_unbookmarked?: boolean;
  include_unbookmarked?: boolean;
  page_min?: number;
  page_max?: number;
  bookmarks_min?: number;
  bookmarks_max?: number;
  views_min?: number;
  views_max?: number;
}
```

新增维护类型：

```ts
export interface MaintenancePreview {
  pages_to_reset: number;
  works_to_fix: number;
}

export interface DbCheckIssue {
  kind: string;
  count: number;
  samples: (number | string)[];
}

export interface DbCheckReport {
  ok: boolean;
  issues: DbCheckIssue[];
}
```

`frontend/src/pages/Stats.test.tsx` 替换为（完整文件；Stats 现在渲染 `Link`，测试需要 Router）：

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import Stats from "./Stats";

const STATS = {
  total_illusts: 2050,
  unbookmarked: 3,
  total_pages: 21832,
  downloaded_pages: 192,
  failed_pages: 1,
  pending_pages: 21639,
  total_bytes: 501_234_567,
  thumbs_ready: 24,
  ugoira_count: 43,
  animation_ready: 2,
  by_type: { illust: 2007, ugoira: 43 },
  by_restrict: { public: 2047, private: 3 },
  by_type_bytes: { illust: 401_234_567, ugoira: 100_000_000 },
  by_restrict_bytes: { public: 500_000_000, private: 1_234_567 },
  top_authors_bytes: [{ id: 1, name: "画师甲", bytes: 200_000_000, illust_count: 10 }],
  stats_stale: false,
};

afterEach(() => vi.restoreAllMocks());

function mockStats(overrides: Partial<typeof STATS> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.includes("/api/stats") ? { ...STATS, ...overrides } : [];
      return Promise.resolve(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    }),
  );
}

function renderStats() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Stats />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Stats", () => {
  it("renders totals from the api", async () => {
    mockStats();
    renderStats();
    await waitFor(() => expect(screen.getByText("2,050")).toBeInTheDocument());
    expect(screen.getByText("21,832")).toBeInTheDocument();
    expect(screen.getByText(/192/)).toBeInTheDocument();
  });

  it("shows a download progress percentage", async () => {
    mockStats();
    renderStats();
    await waitFor(() => expect(screen.getByText(/0\.9%/)).toBeInTheDocument());
  });

  it("renders the storage distribution", async () => {
    mockStats();
    renderStats();
    await waitFor(() => expect(screen.getByText("体积与页数分布")).toBeInTheDocument());
    expect(screen.getByText("画师甲")).toBeInTheDocument();
  });

  it("links download metrics to gallery filters", async () => {
    mockStats();
    renderStats();
    await waitFor(() => expect(screen.getByText(/192/)).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /已下载页/ })).toHaveAttribute(
      "href",
      "/?downloaded=true",
    );
  });

  it("prompts to rebuild stats when stale", async () => {
    mockStats({ stats_stale: true });
    renderStats();
    await waitFor(() => expect(screen.getByText(/体积未知/)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run（在 `frontend/`）: `npm test -- src/pages/Stats.test.tsx`
Expected: FAIL（缺"体积与页数分布"）

- [ ] **Step 3: 实现 Stats 页**

`frontend/src/pages/Stats.tsx` 替换为：

```tsx
import { Link } from "react-router-dom";

import { useAuthors, useStats, useTags } from "../api/queries";
import { formatBytes } from "../lib/format";

const TYPE_LABELS: Record<string, string> = {
  illust: "插画",
  manga: "漫画",
  ugoira: "动图",
};

const RESTRICT_LABELS: Record<string, string> = {
  public: "公开收藏",
  private: "私密收藏",
};

function Card({
  label,
  value,
  hint,
  to,
}: {
  label: string;
  value: string;
  hint?: string;
  to?: string;
}) {
  const body = (
    <>
      <div className="text-xs text-text-muted">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
      {hint ? <div className="mt-1 text-xs text-text-muted">{hint}</div> : null}
    </>
  );
  if (to) {
    return (
      <Link
        to={to}
        className="block rounded-lg border border-border-subtle bg-surface-raised p-4 transition-colors hover:border-accent"
      >
        {body}
      </Link>
    );
  }
  return <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">{body}</div>;
}

export default function Stats() {
  const { data, isLoading, isError } = useStats();
  const authors = useAuthors(10);
  const tags = useTags(20);

  if (isLoading) {
    return <div className="p-6 text-sm text-text-muted">加载中…</div>;
  }
  if (isError || !data) {
    return <div className="p-6 text-sm text-red-400">统计数据加载失败</div>;
  }

  const percent = data.total_pages > 0 ? (data.downloaded_pages / data.total_pages) * 100 : 0;

  return (
    <div className="space-y-6 p-6">
      <h1 className="text-base font-semibold">统计</h1>

      {data.stats_stale ? (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
          部分作品体积未知，请在「设置 → 维护」中运行「重建存储统计」。
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card label="作品总数" value={data.total_illusts.toLocaleString()} />
        <Card label="总页数" value={data.total_pages.toLocaleString()} />
        <Card
          label="已下载页"
          value={data.downloaded_pages.toLocaleString()}
          hint={`${percent.toFixed(1)}% · 待下载 ${data.pending_pages.toLocaleString()}`}
          to="/?downloaded=true"
        />
        <Card label="占用空间" value={formatBytes(data.total_bytes)} />
        <Card label="缩略图" value={data.thumbs_ready.toLocaleString()} />
        <Card
          label="动图"
          value={data.ugoira_count.toLocaleString()}
          hint={`已转码 ${data.animation_ready}`}
        />
        <Card label="已取消收藏" value={data.unbookmarked.toLocaleString()} to="/unbookmarked" />
        <Card
          label="失败页"
          value={data.failed_pages.toLocaleString()}
          hint={data.failed_pages > 0 ? "可在任务页重试失败项" : undefined}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
          <div className="mb-3 text-sm font-medium">体积与页数分布</div>
          <div className="space-y-2 text-sm">
            {Object.entries(data.by_type).map(([type, count]) => (
              <div key={type} className="flex items-center justify-between">
                <span className="text-text-muted">{TYPE_LABELS[type] ?? type}</span>
                <span>
                  {count.toLocaleString()} · {formatBytes(data.by_type_bytes[type] ?? 0)}
                </span>
              </div>
            ))}
            {Object.entries(data.by_restrict).map(([restrict, count]) => (
              <div key={restrict} className="flex items-center justify-between">
                <span className="text-text-muted">{RESTRICT_LABELS[restrict] ?? restrict}</span>
                <span>
                  {count.toLocaleString()} · {formatBytes(data.by_restrict_bytes[restrict] ?? 0)}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
          <div className="mb-3 text-sm font-medium">体积 TOP 作者</div>
          <div className="space-y-2 text-sm">
            {data.top_authors_bytes.length === 0 ? (
              <span className="text-text-muted">暂无数据</span>
            ) : (
              data.top_authors_bytes.map((author) => (
                <div key={author.id} className="flex items-center justify-between gap-3">
                  <Link to={`/?author_id=${author.id}`} className="truncate hover:text-accent">
                    {author.name}
                  </Link>
                  <span>
                    {formatBytes(author.bytes)} · {author.illust_count}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
          <div className="mb-3 text-sm font-medium">作者 TOP 10</div>
          <div className="space-y-2 text-sm">
            {(authors.data ?? []).map((author) => (
              <div key={author.id} className="flex items-center justify-between gap-3">
                <Link to={`/?author_id=${author.id}`} className="truncate hover:text-accent">
                  {author.name}
                </Link>
                <span>{author.illust_count}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
          <div className="mb-3 text-sm font-medium">常见标签</div>
          <div className="flex flex-wrap gap-2">
            {(tags.data ?? []).map((tag) => (
              <Link
                key={tag.name}
                to={`/?tag=${encodeURIComponent(tag.name)}`}
                className="rounded bg-surface-hover px-2 py-1 text-xs hover:text-accent"
              >
                {tag.name} · {tag.illust_count}
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 实现维护卡片与服务端 mutations**

`frontend/src/api/mutations.ts` 追加：

```ts
import type { DbCheckReport, MaintenancePreview, TaskOut } from "./types";

export function useRebuildStats() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<TaskOut>("/api/maintenance/rebuild-stats", { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tasks"] });
      void client.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function usePreviewRepair() {
  return useMutation({
    mutationFn: () =>
      apiFetch<MaintenancePreview>("/api/maintenance/repair-download-state/preview"),
  });
}

export function useRepairDownloadState() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<TaskOut>("/api/maintenance/repair-download-state", { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tasks"] });
      void client.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useDbCheck() {
  return useMutation({
    mutationFn: () => apiFetch<DbCheckReport>("/api/maintenance/db-check", { method: "POST" }),
  });
}
```

`frontend/src/components/MaintenanceCard.tsx`：

```tsx
import { useDbCheck, usePreviewRepair, useRebuildStats, useRepairDownloadState } from "../api/mutations";

export default function MaintenanceCard() {
  const rebuild = useRebuildStats();
  const preview = usePreviewRepair();
  const repair = useRepairDownloadState();
  const check = useDbCheck();

  return (
    <div className="rounded-lg border border-border-subtle bg-surface-raised p-4 text-sm">
      <div className="mb-2 font-medium">维护</div>
      <p className="mb-3 text-text-muted">
        对数据库与本地文件做一致性检查与修复。重建统计会扫描 works 目录，数据量大时较慢。
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => rebuild.mutate()}
          disabled={rebuild.isPending}
          className="rounded-md bg-accent px-3 py-1.5 text-white disabled:opacity-50"
        >
          {rebuild.isPending ? "已提交…" : "重建存储统计"}
        </button>
        <button
          type="button"
          onClick={() => preview.mutate()}
          disabled={preview.isPending}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-50"
        >
          预览修复下载状态
        </button>
        <button
          type="button"
          onClick={() => repair.mutate()}
          disabled={repair.isPending}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-50"
        >
          执行修复
        </button>
        <button
          type="button"
          onClick={() => check.mutate()}
          disabled={check.isPending}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-50"
        >
          数据库体检
        </button>
      </div>

      {preview.data ? (
        <div className="mt-3 text-xs text-text-muted">
          预览：{preview.data.works_to_fix} 个作品、{preview.data.pages_to_reset} 页需要修正。
        </div>
      ) : null}

      {check.data ? (
        <div className="mt-3 text-xs">
          {check.data.ok ? (
            <span className="text-emerald-300">体检通过，无异常。</span>
          ) : (
            <ul className="space-y-1 text-amber-300">
              {check.data.issues.map((issue) => (
                <li key={issue.kind}>
                  {issue.kind}：{issue.count} 例（样本 {issue.samples.join(", ")}）
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}

      {rebuild.isError || repair.isError || check.isError ? (
        <div className="mt-3 text-xs text-red-400">操作失败，请查看任务页或服务日志。</div>
      ) : null}
    </div>
  );
}
```

`frontend/src/pages/Settings.tsx` 中，在"服务配置"卡片之后插入：

```tsx
      <MaintenanceCard />
```

并 import：

```tsx
import MaintenanceCard from "../components/MaintenanceCard";
```

- [ ] **Step 5: 运行测试确认通过**

Run（在 `frontend/`）: `npm test -- src/pages/Stats.test.tsx` 然后 `npm run lint; npm run typecheck; npm test`
Expected: 全部通过

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat(web): storage distribution stats and maintenance panel"
```

---

### Task 8: 导出页范围选择

**Files:**
- Modify: `frontend/src/pages/Export.tsx`
- Test: `frontend/src/pages/Export.test.tsx`（新建）

- [ ] **Step 1: 写失败的测试**

```tsx
// frontend/src/pages/Export.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GalleryFiltersProvider } from "../contexts/GalleryFiltersContext";
import { SelectionProvider } from "../contexts/SelectionContext";
import Export from "./Export";

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <SelectionProvider>
            <GalleryFiltersProvider>{children}</GalleryFiltersProvider>
          </SelectionProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
  };
}

afterEach(() => vi.restoreAllMocks());

function mockApi() {
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/stats")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            total_illusts: 1,
            unbookmarked: 0,
            total_pages: 1,
            downloaded_pages: 1,
            failed_pages: 0,
            pending_pages: 0,
            total_bytes: 1,
            thumbs_ready: 1,
            ugoira_count: 0,
            animation_ready: 0,
            by_type: {},
            by_restrict: {},
            by_type_bytes: {},
            by_restrict_bytes: {},
            top_authors_bytes: [],
            stats_stale: false,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      );
    }
    return Promise.resolve(
      new Response(JSON.stringify({ task_id: "t1", filename: "f.zip" }), {
        status: 202,
        headers: { "content-type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("Export", () => {
  it("submits the current gallery filter when selecting filter scope", async () => {
    const fetchMock = mockApi();
    render(<Export />, { wrapper: wrapper() });

    await userEvent.click(screen.getByLabelText("按当前筛选"));
    await userEvent.click(screen.getByRole("button", { name: "开始导出" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url]) => String(url) === "/api/export",
      );
      expect(call).toBeTruthy();
    });
    const body = JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body));
    expect(body.use_filter).toBe(true);
  });

  it("disables selection scope when nothing is selected", async () => {
    mockApi();
    render(<Export />, { wrapper: wrapper() });
    expect(screen.getByLabelText("按选中 (0)")).toBeDisabled();
  });

  it("does not set use_filter in the default all scope", async () => {
    const fetchMock = mockApi();
    render(<Export />, { wrapper: wrapper() });
    await userEvent.click(screen.getByRole("button", { name: "开始导出" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/export")).toBe(true),
    );
    const call = fetchMock.mock.calls.find(([url]) => String(url) === "/api/export");
    const body = JSON.parse(String(call?.[1]?.body));
    expect(body.use_filter).toBeFalsy();
    expect(body.pids).toBeUndefined();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run（在 `frontend/`）: `npm test -- src/pages/Export.test.tsx`
Expected: FAIL（找不到"按当前筛选"）

- [ ] **Step 3: 实现**

`frontend/src/pages/Export.tsx` 替换为：

```tsx
import { useState } from "react";

import { useStartExport } from "../api/mutations";
import { useStats } from "../api/queries";
import type { ExportRequest, GalleryQuery } from "../api/types";
import { useGalleryFilters } from "../contexts/GalleryFiltersContext";
import { useSelection } from "../contexts/SelectionContext";

type Scope = "all" | "filter" | "selected";

export default function Export() {
  const stats = useStats();
  const start = useStartExport();
  const { filters } = useGalleryFilters();
  const selection = useSelection();
  const [scope, setScope] = useState<Scope>("all");
  const [includeOriginals, setIncludeOriginals] = useState(false);
  const [includeMetadata, setIncludeMetadata] = useState(true);
  const [onlyDownloaded, setOnlyDownloaded] = useState(true);
  const [r18, setR18] = useState<"" | "0" | "1">("");
  const [groupByAuthor, setGroupByAuthor] = useState(false);
  const [filename, setFilename] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const payload: ExportRequest = {
      include_metadata: includeMetadata,
      include_originals: includeOriginals,
      only_downloaded: onlyDownloaded,
      x_restrict: r18 === "" ? undefined : Number(r18),
      group_by_author: groupByAuthor,
    };
    if (scope === "selected") {
      payload.pids = Array.from(selection.selected);
    } else if (scope === "filter") {
      payload.use_filter = true;
      const fromFilter: (keyof GalleryQuery)[] = [
        "tags",
        "author_ids",
        "q",
        "type",
        "downloaded",
        "restrict",
        "only_unbookmarked",
        "include_unbookmarked",
        "page_min",
        "page_max",
        "bookmarks_min",
        "bookmarks_max",
        "views_min",
        "views_max",
      ];
      fromFilter.forEach((key) => {
        const value = filters[key];
        if (value === undefined) return;
        (payload as Record<string, unknown>)[key] = value;
      });
      if (payload.x_restrict === undefined && filters.x_restrict !== undefined) {
        payload.x_restrict = filters.x_restrict;
      }
    }
    start.mutate(payload, {
      onSuccess: (response) => {
        setFilename(response.filename);
        setTaskId(response.task_id);
      },
    });
  };

  return (
    <div className="max-w-xl space-y-5 p-6">
      <h1 className="text-base font-semibold">导出</h1>
      <p className="text-sm text-text-muted">
        按条件打包下载。当前已下载{" "}
        {stats.data?.downloaded_pages.toLocaleString() ?? "…"} 页。
      </p>

      <form
        onSubmit={submit}
        className="space-y-3 rounded-lg border border-border-subtle bg-surface-raised p-4"
      >
        <fieldset className="space-y-2">
          <legend className="text-sm text-text-muted">范围</legend>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="scope"
              checked={scope === "all"}
              onChange={() => setScope("all")}
              className="accent-accent"
            />
            全部 / 条件
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="scope"
              checked={scope === "filter"}
              onChange={() => setScope("filter")}
              className="accent-accent"
            />
            按当前筛选
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="scope"
              checked={scope === "selected"}
              disabled={selection.count === 0}
              onChange={() => setScope("selected")}
              className="accent-accent"
            />
            按选中 ({selection.count})
          </label>
        </fieldset>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={includeMetadata}
            onChange={(event) => setIncludeMetadata(event.target.checked)}
            className="accent-accent"
          />
          包含元数据 JSON
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={includeOriginals}
            onChange={(event) => setIncludeOriginals(event.target.checked)}
            className="accent-accent"
          />
          包含原图文件（体积可能很大）
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={onlyDownloaded}
            onChange={(event) => setOnlyDownloaded(event.target.checked)}
            className="accent-accent"
          />
          仅包含已下载的作品
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={groupByAuthor}
            onChange={(event) => setGroupByAuthor(event.target.checked)}
            className="accent-accent"
          />
          按作者分组目录
        </label>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-text-muted">分级</span>
          <select
            value={r18}
            onChange={(event) => setR18(event.target.value as typeof r18)}
            className="rounded-md border border-border-subtle bg-surface px-2 py-1.5"
          >
            <option value="">不限</option>
            <option value="0">仅全年龄</option>
            <option value="1">仅 R-18</option>
          </select>
        </label>

        <button
          type="submit"
          disabled={start.isPending || (!includeMetadata && !includeOriginals)}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {start.isPending ? "创建导出任务…" : "开始导出"}
        </button>
      </form>

      {start.isError ? (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {start.error instanceof Error ? start.error.message : "导出失败"}
        </div>
      ) : null}

      {filename && taskId ? (
        <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-3 text-sm">
          <div className="text-emerald-300">导出任务已创建：{filename}</div>
          <div className="mt-2 flex gap-3">
            <a className="underline" href={`/api/export/${taskId}/download`}>
              下载压缩包
            </a>
            <a className="underline" href="/tasks">
              查看进度
            </a>
          </div>
        </div>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run（在 `frontend/`）: `npm test -- src/pages/Export.test.tsx`
Expected: 全部通过

- [ ] **Step 5: 全量前端验证与构建**

Run（在 `frontend/`）: `npm run lint; npm run typecheck; npm test; npm run build`
Expected: 全部通过；构建产物更新 `src/pixiv_archive/web/static/`

- [ ] **Step 6: Commit**

```bash
git add -A frontend/src src/pixiv_archive/web/static
git commit -m "feat(web): export by selection, filter or author grouping"
```

---

### Task 9: 文档与最终验证

**Files:**
- Modify: `README.md`（接口表、维护命令）
- Modify: `AGENTS.md`（架构说明）

- [ ] **Step 1: 全量验证**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy && uv run pytest -q`
Run（在 `frontend/`）: `npm run lint; npm run typecheck; npm test; npm run build`
Expected: 全部通过

- [ ] **Step 2: 更新 README**

"主要接口"表中 `POST /api/export` 行替换为：

```markdown
| POST | `/api/export` | 导出 zip（JSON 元数据 / 原图；可按 pids、按筛选或按作者分组） |
```

在该表之后追加：

```markdown
| GET | `/api/stats` | 统计（数量 / 页状态 / 体积分布，体积来自本地统计列） |
| POST | `/api/maintenance/rebuild-stats` | 重建存储统计（后台任务） |
| GET | `/api/maintenance/repair-download-state/preview` | 预览下载状态修复 |
| POST | `/api/maintenance/repair-download-state` | 执行下载状态修复（后台任务） |
| POST | `/api/maintenance/db-check` | 数据库体检（只读报告） |
```

在"阶段 B"代码块之后新增：

```bash
# 维护：重建体积统计 / 体检 / 修复下载状态（CLI）
uv run python -m pixiv_archive maintain rebuild-stats
uv run python -m pixiv_archive maintain db-check
uv run python -m pixiv_archive maintain repair-download-state --yes
```

并补充一句：

```markdown
升级到带 `byte_size` 统计列的新版本后，体积显示为 0 属正常：在 WebUI「设置 → 维护」运行一次「重建存储统计」，或在容器内执行上面的 CLI。
```

- [ ] **Step 3: 更新 AGENTS.md**

Architecture 列表追加：

```markdown
- `maintenance/` = DB 与 `works/` 目录的对账（重建体积统计、修复下载状态、体检）；Web 端通过 `/api/maintenance/*` 以任务形式调用，CLI 为 `maintain` 子命令。
```

Gotchas 追加：

```markdown
- 迁移 `0004` 只加体积统计列（默认 0），历史数据需通过「维护 → 重建存储统计」回填；`/api/stats` 的 `stats_stale` 指示是否尚未回填。
```

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: document export scopes, stats columns and maintenance"
```
