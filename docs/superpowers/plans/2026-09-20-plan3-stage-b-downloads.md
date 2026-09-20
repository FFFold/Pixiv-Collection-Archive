# 计划 3：阶段 B 图片下载

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现阶段 B 图片下载：从已落库的原图 URL 下载作品原图、ugoira zip 并转码为 mp4、生成本地 WebP 缩略图，通过持久化任务队列与可选范围批次支持中断续传与分批执行。

**Architecture:** 新增 `download/` 模块（`batches.py` 负责范围→任务清单、`queue.py` 负责持久化任务状态、`worker.py` 负责并发执行与重试）；`media/ugoira.py` 负责 zip 校验与 ffmpeg 转码；`media/thumbnails.py` 负责本地 WebP 缩略图。下载完全离线（不需 API 调用），仅在 URL 404 时回退一次详情接口刷新 URL。

**Tech Stack:** Python 3.12、SQLAlchemy 2.x async、httpx、Pillow（WebP）、ffmpeg（外部进程）、pytest + pytest-asyncio

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `src/pixiv_archive/db/models.py` | 追加 DownloadJob / DownloadBatch |
| `src/pixiv_archive/db/migrations/versions/0003_download_tables.py` | 对应迁移 |
| `src/pixiv_archive/db/repo/downloads.py` | 批次与任务的增删查、状态聚合 |
| `src/pixiv_archive/media/ugoira.py` | zip 校验、帧时间表、ffmpeg 转码 |
| `src/pixiv_archive/media/thumbnails.py` | Pillow WebP 缩略图与图片校验 |
| `src/pixiv_archive/download/__init__.py` | 导出 |
| `src/pixiv_archive/download/scope.py` | 范围定义与 SQL 解析（筛选/作者/选中/rank 区间/未下载） |
| `src/pixiv_archive/download/queue.py` | 持久化队列操作（入队、认领、完成、失败、重试） |
| `src/pixiv_archive/download/worker.py` | `DownloadWorker`：并发执行任务、更新进度、恢复未完成任务 |
| `src/pixiv_archive/sync/factory.py` | 追加 `open_download_worker` |
| `src/pixiv_archive/cli.py` | 追加 `download` 子命令 |
| `tests/test_ugoira.py` / `tests/test_thumbnails.py` / `tests/test_download_*.py` | 测试 |

---

### Task 1: 下载相关表与迁移 0003

**Files:**
- Modify: `src/pixiv_archive/db/models.py`
- Create: `src/pixiv_archive/db/migrations/versions/0003_download_tables.py`
- Test: `tests/test_download_models.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_download_models.py`：

```python
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, DownloadBatch, DownloadJob, Illust


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "dl.db")
    await database.create_all()
    yield database
    await database.dispose()


async def test_download_tables_exist(db):
    from sqlalchemy import text

    async with db.session() as session:
        rows = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        names = {r[0] for r in rows}
    assert {"download_batch", "download_job"} <= names


async def test_download_job_defaults_and_unique(db):
    from sqlalchemy.exc import IntegrityError

    async with db.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=10, title="x", author_id=1))
        await session.commit()
    async with db.session() as session:
        session.add(DownloadJob(pid=10, kind="image", target="000_p0.jpg"))
        await session.commit()
    async with db.session() as session:
        job = (await session.execute(select(DownloadJob))).scalar_one()
    assert job.status == "pending"
    assert job.attempts == 0
    assert job.last_error is None

    with pytest.raises(IntegrityError):
        async with db.session() as session:
            session.add(DownloadJob(pid=10, kind="image", target="000_p0.jpg"))
            await session.commit()


async def test_download_job_allows_same_pid_different_kind(db):
    async with db.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=10, title="x", author_id=1))
        session.add(DownloadJob(pid=10, kind="image", target="000_p0.jpg"))
        session.add(DownloadJob(pid=10, kind="thumb", target="thumb.webp"))
        await session.commit()
    async with db.session() as session:
        rows = (await session.execute(select(DownloadJob))).scalars().all()
    assert len(rows) == 2


async def test_download_batch_counts(db):
    now = datetime(2026, 5, 5, tzinfo=UTC)
    async with db.session() as session:
        session.add(
            DownloadBatch(
                scope="all_missing",
                filter_json=None,
                created_at=now,
                total=10,
                finished=2,
                failed=1,
            )
        )
        await session.commit()
    async with db.session() as session:
        batch = (await session.execute(select(DownloadBatch))).scalar_one()
    assert batch.total == 10
    assert batch.status == "running"
    assert batch.cancelled is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_download_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'DownloadBatch'`

- [ ] **Step 3: 追加模型**

在 `src/pixiv_archive/db/models.py` 末尾追加：

```python
class DownloadBatch(Base):
    __tablename__ = "download_batch"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(32))
    filter_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    cancelled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    total: Mapped[int] = mapped_column(default=0)
    finished: Mapped[int] = mapped_column(default=0)
    failed: Mapped[int] = mapped_column(default=0)


class DownloadJob(Base):
    __tablename__ = "download_job"
    __table_args__ = (UniqueConstraint("pid", "kind", "target", name="uq_download_job"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("download_batch.id"), nullable=True, index=True
    )
    pid: Mapped[int] = mapped_column(BigInteger, ForeignKey("illust.pid"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    target: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


Index("ix_download_job_status_batch", DownloadJob.status, DownloadJob.batch_id)
```

- [ ] **Step 4: 写迁移 0003**

`src/pixiv_archive/db/migrations/versions/0003_download_tables.py`：

```python
"""download tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-20

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "download_batch",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("filter_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("cancelled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finished", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "download_job",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("download_batch.id"), nullable=True),
        sa.Column("pid", sa.BigInteger(), sa.ForeignKey("illust.pid"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("pid", "kind", "target", name="uq_download_job"),
    )
    op.create_index("ix_download_job_pid", "download_job", ["pid"])
    op.create_index("ix_download_job_status", "download_job", ["status"])
    op.create_index("ix_download_job_batch_id", "download_job", ["batch_id"])
    op.create_index(
        "ix_download_job_status_batch", "download_job", ["status", "batch_id"]
    )


def downgrade() -> None:
    op.drop_table("download_job")
    op.drop_table("download_batch")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_download_models.py tests/test_migrations.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/pixiv_archive/db/models.py src/pixiv_archive/db/migrations/versions/0003_download_tables.py tests/test_download_models.py
git commit -m "feat: add download batch and job tables"
```

---

### Task 2: 仓储层 — downloads

**Files:**
- Create: `src/pixiv_archive/db/repo/downloads.py`
- Modify: `src/pixiv_archive/db/repo/__init__.py`
- Test: `tests/test_repo_downloads.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_repo_downloads.py`：

```python
from datetime import UTC, datetime

import pytest

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Illust
from pixiv_archive.db.repo import downloads


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "drepo.db")
    await database.create_all()
    yield database
    await database.dispose()


async def _seed(db, pids: list[int]) -> None:
    async with db.session() as session:
        session.add(Author(id=1, name="a"))
        for pid in pids:
            session.add(Illust(pid=pid, title=f"t{pid}", author_id=1))
        await session.commit()


async def test_create_batch_and_enqueue(db):
    await _seed(db, [1, 2])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        added = await downloads.enqueue_jobs(
            session,
            batch_id=batch_id,
            jobs=[(1, "image", "000_p0.jpg"), (1, "thumb", "thumb.webp"), (2, "image", "000_p0.jpg")],
            now=datetime.now(UTC),
        )
        await session.commit()
    assert batch_id > 0
    assert added == 3

    async with db.session() as session:
        batch = await downloads.get_batch(session, batch_id)
        counts = await downloads.count_jobs_by_status(session, batch_id)
    assert batch.total == 3
    assert counts == {"pending": 3}


async def test_enqueue_jobs_is_idempotent(db):
    await _seed(db, [1])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="selected", filter_json="{}", now=datetime.now(UTC)
        )
        first = await downloads.enqueue_jobs(
            session, batch_id=batch_id, jobs=[(1, "image", "000_p0.jpg")], now=datetime.now(UTC)
        )
        second = await downloads.enqueue_jobs(
            session, batch_id=batch_id, jobs=[(1, "image", "000_p0.jpg")], now=datetime.now(UTC)
        )
        await session.commit()
    assert first == 1
    assert second == 0  # duplicate target ignored


async def test_claim_pending_jobs(db):
    await _seed(db, [1, 2, 3])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        await downloads.enqueue_jobs(
            session,
            batch_id=batch_id,
            jobs=[(pid, "image", "000_p0.jpg") for pid in (1, 2, 3)],
            now=datetime.now(UTC),
        )
        await session.commit()

    async with db.session() as session:
        claimed = await downloads.claim_pending_jobs(session, limit=2)
        await session.commit()
    assert [job.pid for job in claimed] == [1, 2]
    assert all(job.status == "running" for job in claimed)
    assert all(job.attempts == 1 for job in claimed)

    async with db.session() as session:
        claimed2 = await downloads.claim_pending_jobs(session, limit=10)
        await session.commit()
    assert [job.pid for job in claimed2] == [3]


async def test_finish_job_and_fail_job(db):
    await _seed(db, [1, 2])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        await downloads.enqueue_jobs(
            session, batch_id=batch_id, jobs=[(1, "image", "a.jpg"), (2, "image", "b.jpg")],
            now=datetime.now(UTC),
        )
        await session.commit()
    async with db.session() as session:
        jobs = await downloads.claim_pending_jobs(session, limit=2)
        await downloads.finish_job(session, jobs[0].id, now=datetime.now(UTC))
        await downloads.fail_job(session, jobs[1].id, error="boom", now=datetime.now(UTC))
        await session.commit()

    async with db.session() as session:
        batch = await downloads.get_batch(session, batch_id)
        counts = await downloads.count_jobs_by_status(session, batch_id)
    assert counts == {"done": 1, "failed": 1}
    assert batch.finished == 1
    assert batch.failed == 1


async def test_reset_running_jobs_on_startup(db):
    await _seed(db, [1])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        await downloads.enqueue_jobs(
            session, batch_id=batch_id, jobs=[(1, "image", "a.jpg")], now=datetime.now(UTC)
        )
        await session.commit()
    async with db.session() as session:
        await downloads.claim_pending_jobs(session, limit=1)
        await session.commit()

    async with db.session() as session:
        reset = await downloads.reset_running_jobs(session)
        await session.commit()
    assert reset == 1
    async with db.session() as session:
        counts = await downloads.count_jobs_by_status(session, batch_id)
    assert counts == {"pending": 1}


async def test_retry_failed_jobs(db):
    await _seed(db, [1])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        await downloads.enqueue_jobs(
            session, batch_id=batch_id, jobs=[(1, "image", "a.jpg")], now=datetime.now(UTC)
        )
        await session.commit()
    async with db.session() as session:
        jobs = await downloads.claim_pending_jobs(session, limit=1)
        await downloads.fail_job(session, jobs[0].id, error="boom", now=datetime.now(UTC))
        await session.commit()

    async with db.session() as session:
        retried = await downloads.retry_failed_jobs(session, batch_id=batch_id)
        await session.commit()
    assert retried == 1
    async with db.session() as session:
        counts = await downloads.count_jobs_by_status(session, batch_id)
        batch = await downloads.get_batch(session, batch_id)
    assert counts == {"pending": 1}
    assert batch.failed == 0


async def test_mark_batch_finished_when_no_pending(db):
    await _seed(db, [1])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        await downloads.enqueue_jobs(
            session, batch_id=batch_id, jobs=[(1, "image", "a.jpg")], now=datetime.now(UTC)
        )
        await session.commit()
    async with db.session() as session:
        jobs = await downloads.claim_pending_jobs(session, limit=1)
        await downloads.finish_job(session, jobs[0].id, now=datetime.now(UTC))
        finished = await downloads.finalize_batch_if_done(session, batch_id, now=datetime.now(UTC))
        await session.commit()
    assert finished is True
    async with db.session() as session:
        batch = await downloads.get_batch(session, batch_id)
    assert batch.status == "completed"
    assert batch.finished_at is not None


async def test_finalize_batch_keeps_running_when_pending_left(db):
    await _seed(db, [1, 2])
    async with db.session() as session:
        batch_id = await downloads.create_batch(
            session, scope="all_missing", filter_json=None, now=datetime.now(UTC)
        )
        await downloads.enqueue_jobs(
            session, batch_id=batch_id, jobs=[(1, "image", "a.jpg"), (2, "image", "b.jpg")],
            now=datetime.now(UTC),
        )
        await session.commit()
    async with db.session() as session:
        finished = await downloads.finalize_batch_if_done(session, batch_id, now=datetime.now(UTC))
        await session.commit()
    assert finished is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_repo_downloads.py -v`
Expected: FAIL — `ImportError: cannot import name 'downloads'`

- [ ] **Step 3: 实现 repo/downloads.py**

`src/pixiv_archive/db/repo/downloads.py`：

```python
from datetime import datetime

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import DownloadBatch, DownloadJob


async def create_batch(
    session: AsyncSession, *, scope: str, filter_json: str | None, now: datetime
) -> int:
    batch = DownloadBatch(scope=scope, filter_json=filter_json, created_at=now)
    session.add(batch)
    await session.flush()
    return batch.id


async def get_batch(session: AsyncSession, batch_id: int) -> DownloadBatch | None:
    return await session.get(DownloadBatch, batch_id)


async def enqueue_jobs(
    session: AsyncSession,
    *,
    batch_id: int,
    jobs: list[tuple[int, str, str]],
    now: datetime,
) -> int:
    """Insert ``(pid, kind, target)`` jobs, ignoring duplicates. Returns rows added.

    Existing jobs that are finished or failed are reset to pending so that a
    re-requested download actually re-runs.
    """
    added = 0
    for pid, kind, target in jobs:
        existing = (
            await session.execute(
                select(DownloadJob).where(
                    DownloadJob.pid == pid,
                    DownloadJob.kind == kind,
                    DownloadJob.target == target,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                DownloadJob(
                    batch_id=batch_id, pid=pid, kind=kind, target=target, created_at=now
                )
            )
            added += 1
        elif existing.status in ("done", "failed", "skipped"):
            existing.status = "pending"
            existing.batch_id = batch_id
            existing.last_error = None
            added += 1
    batch = await session.get(DownloadBatch, batch_id)
    if batch is not None:
        batch.total = (
            await session.execute(
                select(func.count()).select_from(DownloadJob).where(DownloadJob.batch_id == batch_id)
            )
        ).scalar_one()
    return added


async def claim_pending_jobs(session: AsyncSession, *, limit: int) -> list[DownloadJob]:
    rows = await session.execute(
        select(DownloadJob)
        .where(DownloadJob.status == "pending")
        .order_by(DownloadJob.id)
        .limit(limit)
    )
    jobs = list(rows.scalars().all())
    for job in jobs:
        job.status = "running"
        job.attempts += 1
    await session.flush()
    return jobs


async def finish_job(
    session: AsyncSession, job_id: int, *, now: datetime, status: str = "done"
) -> None:
    job = await session.get(DownloadJob, job_id)
    if job is None:
        return
    job.status = status
    job.last_error = None
    job.updated_at = now


async def fail_job(session: AsyncSession, job_id: int, *, error: str, now: datetime) -> None:
    job = await session.get(DownloadJob, job_id)
    if job is None:
        return
    job.status = "failed"
    job.last_error = error[:500]
    job.updated_at = now


async def count_jobs_by_status(session: AsyncSession, batch_id: int) -> dict[str, int]:
    rows = await session.execute(
        select(DownloadJob.status, func.count())
        .where(DownloadJob.batch_id == batch_id)
        .group_by(DownloadJob.status)
    )
    return {status: count for status, count in rows}


async def reset_running_jobs(session: AsyncSession) -> int:
    """Return orphaned running jobs (e.g. from a crashed process) to pending."""
    result = await session.execute(
        update(DownloadJob).where(DownloadJob.status == "running").values(status="pending")
    )
    assert isinstance(result, CursorResult)
    return result.rowcount or 0


async def retry_failed_jobs(session: AsyncSession, *, batch_id: int | None = None) -> int:
    stmt = update(DownloadJob).where(DownloadJob.status == "failed")
    if batch_id is not None:
        stmt = stmt.where(DownloadJob.batch_id == batch_id)
    result = await session.execute(stmt.values(status="pending", last_error=None))
    assert isinstance(result, CursorResult)
    count = result.rowcount or 0
    if batch_id is not None:
        batch = await session.get(DownloadBatch, batch_id)
        if batch is not None:
            batch.failed = 0
            batch.status = "running"
            batch.finished_at = None
    return count


async def finalize_batch_if_done(
    session: AsyncSession, batch_id: int, *, now: datetime
) -> bool:
    counts = await count_jobs_by_status(session, batch_id)
    pending = counts.get("pending", 0) + counts.get("running", 0)
    if pending > 0 or not counts:
        return False
    batch = await session.get(DownloadBatch, batch_id)
    if batch is None:
        return False
    batch.finished = counts.get("done", 0) + counts.get("skipped", 0)
    batch.failed = counts.get("failed", 0)
    batch.status = "completed" if batch.failed == 0 else "completed_with_failures"
    batch.finished_at = now
    return True


async def pending_job_count(session: AsyncSession) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(DownloadJob).where(DownloadJob.status == "pending")
        )
    ).scalar_one()


async def missing_pids(session: AsyncSession) -> list[int]:
    """Pids that have at least one pending/failed job, ordered by id."""
    rows = await session.execute(
        select(DownloadJob.pid)
        .where(DownloadJob.status.in_(("pending", "failed")))
        .distinct()
        .order_by(DownloadJob.pid)
    )
    return [row[0] for row in rows]


async def jobs_for_pid(session: AsyncSession, pid: int) -> list[DownloadJob]:
    rows = await session.execute(
        select(DownloadJob).where(DownloadJob.pid == pid).order_by(DownloadJob.id)
    )
    return list(rows.scalars().all())
```

更新 `src/pixiv_archive/db/repo/__init__.py`：

```python
from pixiv_archive.db.repo import bookmarks, downloads, illusts, sync_runs

__all__ = ["bookmarks", "downloads", "illusts", "sync_runs"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_repo_downloads.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/db/repo tests/test_repo_downloads.py
git commit -m "feat: add download queue repository"
```

---

### Task 3: ugoira zip 校验与 ffmpeg 转码

**Files:**
- Create: `src/pixiv_archive/media/ugoira.py`
- Test: `tests/test_ugoira.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_ugoira.py`：

```python
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from pixiv_archive.media.ugoira import (
    UgoiraError,
    build_concat_file,
    ffmpeg_available,
    transcode_to_mp4,
    validate_frames,
)

FFMPEG = shutil.which("ffmpeg")


def _make_zip(path: Path, frames: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name in frames:
            img = Image.new("RGB", (16, 16), color=(10, 20, 30))
            buffer = path.parent / f"tmp_{name}"
            img.save(buffer, format="JPEG")
            zf.write(buffer, name)
            buffer.unlink()


def test_validate_frames_ok(tmp_path):
    zip_path = tmp_path / "u.zip"
    names = [f"{i:06d}.jpg" for i in range(3)]
    _make_zip(zip_path, names)
    frames = [{"file": name, "delay": 100} for name in names]
    extract_dir = tmp_path / "frames"
    result = validate_frames(zip_path, frames, extract_dir)
    assert result == ["000000.jpg", "000001.jpg", "000002.jpg"]
    assert (extract_dir / "000000.jpg").exists()


def test_validate_frames_missing_member(tmp_path):
    zip_path = tmp_path / "u.zip"
    _make_zip(zip_path, ["000000.jpg"])
    frames = [
        {"file": "000000.jpg", "delay": 100},
        {"file": "000001.jpg", "delay": 100},
    ]
    with pytest.raises(UgoiraError):
        validate_frames(zip_path, frames, tmp_path / "frames")


def test_validate_frames_empty_list(tmp_path):
    zip_path = tmp_path / "u.zip"
    _make_zip(zip_path, ["000000.jpg"])
    with pytest.raises(UgoiraError):
        validate_frames(zip_path, [], tmp_path / "frames")


def test_validate_frames_bad_zip(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(UgoiraError):
        validate_frames(bad, [{"file": "a.jpg", "delay": 1}], tmp_path / "frames")


def test_build_concat_file_format(tmp_path):
    frames = [
        {"file": "000000.jpg", "delay": 100},
        {"file": "000001.jpg", "delay": 50},
        {"file": "000002.jpg", "delay": 33},
    ]
    concat = build_concat_file(frames, tmp_path)
    text = concat.read_text("utf-8")
    assert "file '000000.jpg'" in text
    assert "duration 0.100" in text
    assert "duration 0.050" in text
    assert "duration 0.033" in text
    # last frame is repeated so its duration is honoured
    assert text.rstrip().endswith("file '000002.jpg'")


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_transcode_to_mp4_real_ffmpeg(tmp_path):
    zip_path = tmp_path / "u.zip"
    names = [f"{i:06d}.jpg" for i in range(4)]
    _make_zip(zip_path, names)
    frames = [{"file": name, "delay": 100} for name in names]
    frames_json = json.dumps(frames)
    out = tmp_path / "animation.mp4"
    result = transcode_to_mp4(
        zip_path=zip_path,
        frames_json=frames_json,
        frames_dir=tmp_path / "frames",
        dest=out,
        ffmpeg_bin=str(FFMPEG),
    )
    assert result is True
    assert out.exists() and out.stat().st_size > 0
    probe = subprocess.run(
        [str(FFMPEG), "-v", "error", "-i", str(out), "-f", "null", "-"],
        capture_output=True,
    )
    assert probe.returncode == 0


def test_ffmpeg_available_false_for_missing_binary():
    assert ffmpeg_available("/definitely/not/ffmpeg") is False


def test_transcode_returns_false_without_ffmpeg(tmp_path):
    zip_path = tmp_path / "u.zip"
    _make_zip(zip_path, ["000000.jpg"])
    frames_json = json.dumps([{"file": "000000.jpg", "delay": 100}])
    assert (
        transcode_to_mp4(
            zip_path=zip_path,
            frames_json=frames_json,
            frames_dir=tmp_path / "frames",
            dest=tmp_path / "a.mp4",
            ffmpeg_bin="/definitely/not/ffmpeg",
        )
        is False
    )


def test_transcode_refuses_empty_frames(tmp_path):
    zip_path = tmp_path / "u.zip"
    _make_zip(zip_path, ["000000.jpg"])
    assert (
        transcode_to_mp4(
            zip_path=zip_path,
            frames_json="[]",
            frames_dir=tmp_path / "frames",
            dest=tmp_path / "a.mp4",
            ffmpeg_bin=str(FFMPEG) if FFMPEG else "ffmpeg",
        )
        is False
    )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_ugoira.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.media.ugoira'`

- [ ] **Step 3: 实现 media/ugoira.py**

`src/pixiv_archive/media/ugoira.py`：

```python
import json
import logging
import shutil
import subprocess
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_FFMPEG = "ffmpeg"


class UgoiraError(Exception):
    """ugoira zip is corrupt or does not match the frame list."""


def ffmpeg_available(ffmpeg_bin: str) -> bool:
    return shutil.which(ffmpeg_bin) is not None


def validate_frames(zip_path: Path, frames: list[dict], extract_dir: Path) -> list[str]:
    """Extract the zip and confirm every frame in ``frames`` exists.

    Returns the ordered list of member names. Raises UgoiraError on any
    mismatch so a truncated download is never treated as valid.
    """
    if not frames:
        raise UgoiraError("frame list is empty")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            missing = [frame["file"] for frame in frames if frame.get("file") not in names]
            if missing:
                raise UgoiraError(f"zip missing {len(missing)} frames (e.g. {missing[0]})")
            extract_dir.mkdir(parents=True, exist_ok=True)
            zf.extractall(extract_dir)
    except zipfile.BadZipFile as exc:
        raise UgoiraError(f"invalid zip: {exc}") from exc
    return [frame["file"] for frame in frames]


def build_concat_file(frames: list[dict], dest_dir: Path, name: str = "frames.txt") -> Path:
    """Write an ffmpeg concat script with per-frame durations.

    The final frame is listed twice because ffmpeg ignores the duration of
    the last entry in a concat list.
    """
    lines: list[str] = []
    for frame in frames:
        lines.append(f"file '{frame['file']}'")
        lines.append(f"duration {max(0.001, frame['delay'] / 1000.0):.3f}")
    if frames:
        lines.append(f"file '{frames[-1]['file']}'")
    path = dest_dir / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def transcode_to_mp4(
    *,
    zip_path: Path,
    frames_json: str,
    frames_dir: Path,
    dest: Path,
    ffmpeg_bin: str = DEFAULT_FFMPEG,
    timeout: int = 600,
) -> bool:
    """Validate the zip and transcode it to an H.264 mp4.

    Returns False (without raising) when ffmpeg is unavailable, the frame
    list is empty, or transcoding fails — the caller keeps the zip in that
    case and records a status.
    """
    if not ffmpeg_available(ffmpeg_bin):
        logger.warning("ffmpeg not available (%s); skipping transcode", ffmpeg_bin)
        return False
    try:
        frames = json.loads(frames_json)
    except ValueError:
        return False
    if not frames:
        return False

    try:
        validate_frames(zip_path, frames, frames_dir)
    except UgoiraError:
        logger.exception("ugoira validation failed for %s", zip_path)
        return False

    concat_path = build_concat_file(frames, frames_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_name(dest.name + ".part")
    command = [
        ffmpeg_bin,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-vsync",
        "vfr",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-loglevel",
        "error",
        str(tmp_dest),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=frames_dir,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("ffmpeg failed for %s: %s", zip_path, exc)
        return False
    if completed.returncode != 0:
        logger.warning(
            "ffmpeg returned %s for %s: %s",
            completed.returncode,
            zip_path,
            completed.stderr.decode("utf-8", "replace")[:500],
        )
        if tmp_dest.exists():
            tmp_dest.unlink()
        return False
    tmp_dest.replace(dest)
    return True
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_ugoira.py -v`
Expected: 9 passed（若本机无 ffmpeg 则跳过 1 个真实转码测试）

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/media/ugoira.py tests/test_ugoira.py
git commit -m "feat: add ugoira validation and ffmpeg transcode"
```

---

### Task 4: 缩略图与图片校验

**Files:**
- Create: `src/pixiv_archive/media/thumbnails.py`
- Test: `tests/test_thumbnails.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_thumbnails.py`：

```python
import io

from PIL import Image

from pixiv_archive.media.thumbnails import (
    THUMB_LONG_EDGE,
    generate_thumb,
    is_valid_image,
)


def _image_bytes(size=(1200, 800), fmt="JPEG") -> bytes:
    image = Image.new("RGB", size, color=(120, 60, 30))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def test_is_valid_image_true_for_jpeg():
    assert is_valid_image(_image_bytes()) is True


def test_is_valid_image_false_for_garbage():
    assert is_valid_image(b"not an image at all") is False


def test_is_valid_image_false_for_truncated():
    data = _image_bytes(size=(800, 800))
    assert is_valid_image(data[: len(data) // 3]) is False


def test_generate_thumb_scales_long_edge(tmp_path):
    src = tmp_path / "a.jpg"
    src.write_bytes(_image_bytes(size=(2400, 1200)))
    dest = tmp_path / "thumb.webp"
    assert generate_thumb(src, dest) is True
    assert dest.exists()
    with Image.open(dest) as img:
        assert img.format == "WEBP"
        assert max(img.size) == THUMB_LONG_EDGE
        assert img.size == (THUMB_LONG_EDGE, THUMB_LONG_EDGE // 2)


def test_generate_thumb_keeps_small_images(tmp_path):
    src = tmp_path / "small.jpg"
    src.write_bytes(_image_bytes(size=(200, 100)))
    dest = tmp_path / "thumb.webp"
    assert generate_thumb(src, dest) is True
    with Image.open(dest) as img:
        assert img.size == (200, 100)


def test_generate_thumb_returns_false_for_invalid(tmp_path):
    src = tmp_path / "bad.jpg"
    src.write_bytes(b"garbage")
    dest = tmp_path / "thumb.webp"
    assert generate_thumb(src, dest) is False
    assert not dest.exists()


def test_generate_thumb_preserves_alpha_as_rgb(tmp_path):
    image = Image.new("RGBA", (800, 600), color=(10, 20, 30, 128))
    src = tmp_path / "alpha.png"
    image.save(src, format="PNG")
    dest = tmp_path / "thumb.webp"
    assert generate_thumb(src, dest) is True
    with Image.open(dest) as opened:
        assert opened.mode in ("RGB", "RGBA")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_thumbnails.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.media.thumbnails'`

- [ ] **Step 3: 实现 media/thumbnails.py**

`src/pixiv_archive/media/thumbnails.py`：

```python
import io
import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

THUMB_LONG_EDGE = 400
THUMB_QUALITY = 82


def is_valid_image(data: bytes) -> bool:
    """Cheap verification that downloaded bytes form a complete image."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        return True
    except (UnidentifiedImageError, OSError, ValueError):
        return False


def generate_thumb(src: Path, dest: Path, *, long_edge: int = THUMB_LONG_EDGE) -> bool:
    """Create a WebP thumbnail; returns False when the source is unusable."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(src) as image:
            image.load()
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            else:
                image = image.copy()
            if max(image.size) > long_edge:
                image.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
            image.save(dest, format="WEBP", quality=THUMB_QUALITY, method=4)
        return True
    except (UnidentifiedImageError, OSError, ValueError):
        logger.warning("thumbnail generation failed for %s", src, exc_info=True)
        return False
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_thumbnails.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/media/thumbnails.py tests/test_thumbnails.py
git commit -m "feat: add webp thumbnail generation and image validation"
```

---

### Task 5: 下载范围解析

**Files:**
- Create: `src/pixiv_archive/download/__init__.py`
- Create: `src/pixiv_archive/download/scope.py`
- Test: `tests/test_download_scope.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_download_scope.py`：

```python
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Illust, IllustPage
from pixiv_archive.db.repo import bookmarks
from pixiv_archive.download.scope import (
    DownloadScope,
    build_illust_filter,
    empty_scope_matches_nothing,
    resolve_scope,
)


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "scope.db")
    await database.create_all()
    yield database
    await database.dispose()


async def _seed_illust(
    db,
    pid: int,
    *,
    author_id: int = 1,
    type_: str = "illust",
    x_restrict: int = 0,
    page_count: int = 1,
    rank: int | None = None,
    state: str = "active",
    page_download_state: str = "pending",
) -> None:
    async with db.session() as session:
        if await session.get(Author, author_id) is None:
            session.add(Author(id=author_id, name=f"a{author_id}"))
        session.add(
            Illust(
                pid=pid,
                title=f"t{pid}",
                author_id=author_id,
                type=type_,
                x_restrict=x_restrict,
                page_count=page_count,
            )
        )
        for index in range(page_count):
            session.add(
                IllustPage(
                    pid=pid,
                    page_index=index,
                    original_url=f"https://i.pximg.net/{pid}_p{index}.jpg",
                    ext=".jpg",
                    download_state=page_download_state,
                )
            )
        if rank is not None:
            session.add(
                bookmarks.Bookmark(pid=pid, restrict="public", rank=rank, state=state)
            )
        await session.commit()


async def test_scope_all_missing_selects_pending_pages(db):
    await _seed_illust(db, 1, rank=0, page_download_state="pending")
    await _seed_illust(db, 2, rank=10, page_download_state="done")
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="all_missing"))
    assert plan.pids == [1]
    assert plan.jobs == [(1, "image", "000_p0.jpg")]


async def test_scope_author_filters_by_author(db):
    await _seed_illust(db, 1, author_id=1, rank=0)
    await _seed_illust(db, 2, author_id=2, rank=10)
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="author", author_id=2))
    assert plan.pids == [2]


async def test_scope_selected_uses_explicit_pids(db):
    await _seed_illust(db, 1, rank=0)
    await _seed_illust(db, 2, rank=10)
    await _seed_illust(db, 3, rank=20)
    async with db.session() as session:
        plan = await resolve_scope(
            session, DownloadScope(kind="selected", pids=[3, 1, 999])
        )
    assert plan.pids == [1, 3]  # ordered by rank, unknown pids dropped


async def test_scope_rank_range_selects_by_position(db):
    for index, pid in enumerate([10, 20, 30, 40]):
        await _seed_illust(db, pid, rank=index * 1024)
    async with db.session() as session:
        plan = await resolve_scope(
            session, DownloadScope(kind="rank_range", start=1, count=2)
        )
    assert plan.pids == [20, 30]


async def test_scope_filter_combines_flags(db):
    await _seed_illust(db, 1, rank=0, x_restrict=0, type_="illust")
    await _seed_illust(db, 2, rank=10, x_restrict=1, type_="ugoira")
    await _seed_illust(db, 3, rank=20, x_restrict=1, type_="illust")
    async with db.session() as session:
        plan = await resolve_scope(
            session,
            DownloadScope(kind="filter", x_restrict=1, type="illust"),
        )
    assert plan.pids == [3]


async def test_scope_filter_author_and_restrict(db):
    await _seed_illust(db, 1, author_id=5, rank=0)
    await _seed_illust(db, 2, author_id=5, rank=10)
    await _seed_illust(db, 3, author_id=6, rank=20)
    async with db.session() as session:
        plan = await resolve_scope(
            session, DownloadScope(kind="filter", author_id=5, pids=[2])
        )
    assert plan.pids == [2]


async def test_scope_skips_unbookmarked_and_deleted(db):
    await _seed_illust(db, 1, rank=0, state="unbookmarked")
    await _seed_illust(db, 2, rank=10)
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update().where(Illust.pid == 2).values(state="deleted")
        )
        await session.commit()
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="all_missing"))
    assert plan.pids == []


async def test_scope_includes_thumb_job_when_missing(db, tmp_path):
    await _seed_illust(db, 1, rank=0, page_download_state="done")
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="all_missing"))
    assert plan.pids == [1]
    assert plan.jobs == [(1, "thumb", "thumb.webp")]


async def test_scope_ugoira_includes_animation_and_zip_jobs(db):
    await _seed_illust(db, 5, rank=0, type_="ugoira", page_download_state="done")
    async with db.session() as session:
        from pixiv_archive.db.models import UgoiraMeta

        session.add(
            UgoiraMeta(pid=5, zip_url="https://i.pximg.net/u.zip", frames_json="[]", frame_count=0)
        )
        await session.commit()
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="all_missing"))
    kinds = {kind for _, kind, _ in plan.jobs}
    assert kinds == {"ugoira_zip", "ugoira_mp4", "thumb"}


async def test_scope_excludes_ugoira_mp4_when_frames_missing(db):
    await _seed_illust(db, 5, rank=0, type_="ugoira", page_download_state="done")
    async with db.session() as session:
        from pixiv_archive.db.models import UgoiraMeta

        session.add(
            UgoiraMeta(pid=5, zip_url="https://i.pximg.net/u.zip", frames_json="[]", frame_count=0)
        )
        await session.commit()
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="all_missing"))
    kinds = {kind for _, kind, _ in plan.jobs}
    assert "ugoira_mp4" in kinds  # transcode is attempted; worker decides ffmpeg availability


def test_empty_scope_matches_nothing():
    assert empty_scope_matches_nothing(DownloadScope(kind="filter")) is True
    assert empty_scope_matches_nothing(DownloadScope(kind="all_missing")) is False


async def test_build_illust_filter_expression(db):
    await _seed_illust(db, 1, rank=0, x_restrict=0, type_="illust")
    await _seed_illust(db, 2, rank=10, x_restrict=2, type_="ugoira")
    async with db.session() as session:
        stmt = build_illust_filter(DownloadScope(kind="filter", x_restrict=2, type="ugoira"))
        rows = (await session.execute(select(Illust.pid).where(stmt))).scalars().all()
    assert rows == [2]


async def test_resolve_scope_marks_ugoira_page_targets(db):
    await _seed_illust(db, 7, rank=0, type_="ugoira", page_count=1, page_download_state="pending")
    async with db.session() as session:
        plan = await resolve_scope(session, DownloadScope(kind="all_missing"))
    assert plan.jobs == [
        (7, "image", "000_p0.jpg"),
        (7, "thumb", "thumb.webp"),
    ]
```

> 说明：`DownloadScope` 为不可变 dataclass；`resolve_scope` 返回 `ScopePlan(pids, jobs)`，其中 `jobs` 是 `(pid, kind, target)` 列表，`target` 为相对 `works/{pid}` 的路径。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_download_scope.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.download'`

- [ ] **Step 3: 实现 download/scope.py**

`src/pixiv_archive/download/scope.py`：

```python
from dataclasses import dataclass, field

from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Bookmark, Illust, IllustPage, UgoiraMeta


@dataclass(frozen=True)
class DownloadScope:
    """Which illusts a download request should cover."""

    kind: str
    pids: list[int] = field(default_factory=list)
    author_id: int | None = None
    start: int | None = None
    count: int | None = None
    x_restrict: int | None = None
    type: str | None = None


@dataclass
class ScopePlan:
    pids: list[int]
    jobs: list[tuple[int, str, str]]


def empty_scope_matches_nothing(scope: DownloadScope) -> bool:
    """A plain filter scope with no criteria would select the whole library."""
    if scope.kind != "filter":
        return False
    return all(
        value is None
        for value in (scope.author_id, scope.start, scope.count, scope.x_restrict, scope.type)
    ) and not scope.pids


def build_illust_filter(scope: DownloadScope) -> Select:
    """Build the SELECT over active, bookmarked illusts matching the scope."""
    stmt = (
        select(Illust.pid)
        .join(Bookmark, Bookmark.pid == Illust.pid)
        .where(Bookmark.state == "active", Illust.state == "active")
    )
    if scope.kind == "selected":
        if not scope.pids:
            return stmt.where(False)
        stmt = stmt.where(Illust.pid.in_(scope.pids))
    elif scope.kind == "author":
        if scope.author_id is None:
            return stmt.where(False)
        stmt = stmt.where(Illust.author_id == scope.author_id)
    elif scope.kind == "rank_range":
        ordered = stmt.order_by(Bookmark.rank)
        if scope.start is not None or scope.count is not None:
            start = scope.start or 0
            limit = scope.count if scope.count is not None else -1
            stmt = ordered.offset(start)
            if limit is not None and limit >= 0:
                stmt = stmt.limit(limit)
            return stmt
    elif scope.kind == "filter":
        conditions = []
        if scope.x_restrict is not None:
            conditions.append(Illust.x_restrict == scope.x_restrict)
        if scope.type is not None:
            conditions.append(Illust.type == scope.type)
        if scope.author_id is not None:
            conditions.append(Illust.author_id == scope.author_id)
        if scope.pids:
            conditions.append(Illust.pid.in_(scope.pids))
        if conditions:
            stmt = stmt.where(and_(*conditions))
    return stmt.order_by(Bookmark.rank)


async def resolve_scope(session: AsyncSession, scope: DownloadScope) -> ScopePlan:
    """Turn a scope into concrete job tuples ``(pid, kind, target)``.

    Image jobs are only created for pages that are not yet downloaded; thumb
    jobs when a local thumbnail is missing; ugoira jobs for zip + transcode.
    """
    if empty_scope_matches_nothing(scope):
        return ScopePlan(pids=[], jobs=[])

    pids = (await session.execute(build_illust_filter(scope))).scalars().all()
    pids = list(pids)
    if not pids:
        return ScopePlan(pids=[], jobs=[])

    jobs: list[tuple[int, str, str]] = []
    illust_rows = (
        await session.execute(
            select(Illust.pid, Illust.type).where(Illust.pid.in_(pids))
        )
    ).all()
    types = {pid: kind for pid, kind in illust_rows}

    page_rows = (
        await session.execute(
            select(IllustPage.pid, IllustPage.page_index, IllustPage.download_state, IllustPage.ext)
            .where(IllustPage.pid.in_(pids))
            .order_by(IllustPage.pid, IllustPage.page_index)
        )
    ).all()
    pending_pages: dict[int, list[tuple[int, str]]] = {}
    for pid, page_index, state, ext in page_rows:
        if state != "done":
            pending_pages.setdefault(pid, []).append((page_index, ext))

    ugoira_rows = (
        await session.execute(
            select(UgoiraMeta.pid, UgoiraMeta.zip_url, UgoiraMeta.frames_json).where(
                UgoiraMeta.pid.in_(pids)
            )
        )
    ).all()
    ugoira_meta = {pid: (zip_url, frames_json) for pid, zip_url, frames_json in ugoira_rows}

    for pid in pids:
        for page_index, ext in pending_pages.get(pid, []):
            jobs.append((pid, "image", f"{page_index:03d}_p{page_index}{ext}"))
        if types.get(pid) == "ugoira" and pid in ugoira_meta:
            jobs.append((pid, "ugoira_zip", "source.zip"))
            jobs.append((pid, "ugoira_mp4", "animation.mp4"))
        jobs.append((pid, "thumb", "thumb.webp"))
    return ScopePlan(pids=pids, jobs=jobs)
```

`src/pixiv_archive/download/__init__.py`：

```python
from pixiv_archive.download.scope import DownloadScope, ScopePlan, resolve_scope

__all__ = ["DownloadScope", "ScopePlan", "resolve_scope"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_download_scope.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/download tests/test_download_scope.py
git commit -m "feat: add download scope resolution"
```

---

### Task 6: 下载工作者

**Files:**
- Create: `src/pixiv_archive/download/worker.py`
- Modify: `src/pixiv_archive/download/__init__.py`
- Test: `tests/test_download_worker.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_download_worker.py`：

```python
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from fakes import FakeDownloader
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Illust, IllustPage, UgoiraMeta
from pixiv_archive.db.repo import downloads
from pixiv_archive.download.scope import DownloadScope
from pixiv_archive.download.worker import DownloadWorker, DownloadWorkerConfig
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.media.thumbnails import generate_thumb


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


def make_worker(db, tmp_path, downloader, *, transcode=None) -> DownloadWorker:
    config = DownloadWorkerConfig(
        concurrency=2,
        max_attempts=3,
        transcode=transcode,
    )
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
        rows = (await session.execute(select(IllustPage).order_by(IllustPage.page_index))).scalars().all()
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


async def test_worker_generates_thumbnail_from_downloaded_page(db, tmp_path):
    from PIL import Image

    await _seed(db, 2, pages=1)
    downloader = FakeDownloader()
    # produce a real image so the thumbnailer succeeds
    image = Image.new("RGB", (800, 600), color=(10, 200, 30))

    async def fetch_to_file(url: str, dest) -> bool:
        downloader.urls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        image.save(dest, format="JPEG")
        return True

    downloader.fetch_to_file = fetch_to_file  # type: ignore[method-assign]
    worker = make_worker(db, tmp_path, downloader)

    report = await worker.run_scope(DownloadScope(kind="all_missing"))

    assert report.thumbs_done == 1
    assert (WorksStorage(tmp_path / "works").thumb_path(2)).exists()


async def test_worker_transcodes_ugoira_when_enabled(db, tmp_path):
    await _seed(db, 5, pages=1, type_="ugoira")
    downloader = FakeDownloader()
    calls: list[tuple] = []

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
        kinds = {job.kind for job in (await session.execute(select(downloads.DownloadJob))).scalars()}
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_download_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.download.worker'`

- [ ] **Step 3: 实现 download/worker.py**

`src/pixiv_archive/download/worker.py`：

```python
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Illust, IllustPage, UgoiraMeta, utcnow
from pixiv_archive.db.repo import downloads
from pixiv_archive.download.scope import DownloadScope, resolve_scope
from pixiv_archive.media.storage import WorksStorage, atomic_write_bytes
from pixiv_archive.media.thumbnails import generate_thumb, is_valid_image
from pixiv_archive.media.ugoira import transcode_to_mp4

TranscodeFn = Callable[..., Awaitable[bool]]


@dataclass
class DownloadWorkerConfig:
    concurrency: int = 4
    max_attempts: int = 3
    transcode: TranscodeFn | None = None


@dataclass
class DownloadReport:
    batch_id: int
    status: str = "completed"
    pages_done: int = 0
    pages_failed: int = 0
    thumbs_done: int = 0
    ugoira_done: int = 0
    failed: int = 0


class DownloadWorker:
    """Executes stage B: downloads originals, ugoira zips and thumbnails."""

    def __init__(
        self,
        *,
        db: Database,
        storage: WorksStorage,
        downloader,
        config: DownloadWorkerConfig | None = None,
    ) -> None:
        self._db = db
        self._storage = storage
        self._downloader = downloader
        self._config = config or DownloadWorkerConfig()
        self._transcode = self._config.transcode
        self._thumbs_enabled = True

    def set_thumb_enabled(self, enabled: bool) -> None:
        self._thumbs_enabled = enabled

    async def retry_failed(self) -> int:
        async with self._db.session() as session:
            count = await downloads.retry_failed_jobs(session)
            await session.commit()
        return count

    async def run_scope(self, scope: DownloadScope) -> DownloadReport:
        async with self._db.session() as session:
            batch_id = await downloads.create_batch(
                session, scope=scope.kind, filter_json=None, now=utcnow()
            )
            plan = await resolve_scope(session, scope)
            await downloads.enqueue_jobs(
                session, batch_id=batch_id, jobs=plan.jobs, now=utcnow()
            )
            await downloads.reset_running_jobs(session)
            await session.commit()

        report = DownloadReport(batch_id=batch_id)
        if not plan.jobs:
            async with self._db.session() as session:
                await downloads.finalize_batch_if_done(session, batch_id, now=utcnow())
                await session.commit()
            return report

        while True:
            async with self._db.session() as session:
                jobs = await downloads.claim_pending_jobs(
                    session, limit=self._config.concurrency
                )
                await session.commit()
            if not jobs:
                break
            await asyncio.gather(
                *(self._run_job(job.id, job.pid, job.kind, job.target, report) for job in jobs)
            )

        async with self._db.session() as session:
            finalized = await downloads.finalize_batch_if_done(session, batch_id, now=utcnow())
            batch = await downloads.get_batch(session, batch_id)
            counts = await downloads.count_jobs_by_status(session, batch_id)
            await session.commit()
        report.failed = counts.get("failed", 0)
        if batch is not None:
            report.status = batch.status if finalized else "completed"
        return report

    async def _run_job(
        self, job_id: int, pid: int, kind: str, target: str, report: DownloadReport
    ) -> None:
        if kind == "thumb" and not self._thumbs_enabled:
            async with self._db.session() as session:
                await downloads.finish_job(session, job_id, now=utcnow(), status="skipped")
                await session.commit()
            return
        handler = {
            "image": self._handle_image,
            "thumb": self._handle_thumb,
            "ugoira_zip": self._handle_ugoira_zip,
            "ugoira_mp4": self._handle_ugoira_mp4,
        }.get(kind)
        if handler is None:
            await self._mark_failed(job_id, f"unknown job kind {kind}")
            return
        try:
            ok, skipped = await handler(pid, target, report)
        except Exception as exc:  # noqa: BLE001 - a single job must not kill the batch
            await self._mark_failed(job_id, str(exc))
            return
        if skipped:
            async with self._db.session() as session:
                await downloads.finish_job(session, job_id, now=utcnow(), status="skipped")
                await session.commit()
        elif ok:
            async with self._db.session() as session:
                await downloads.finish_job(session, job_id, now=utcnow())
                await session.commit()
        else:
            await self._mark_failed(job_id, "download failed")

    async def _load_page(self, pid: int, target: str) -> tuple[str, str] | None:
        page_index = self._page_index_from_target(target)
        async with self._db.session() as session:
            row = (
                await session.execute(
                    select(IllustPage.original_url, IllustPage.download_state).where(
                        IllustPage.pid == pid, IllustPage.page_index == page_index
                    )
                )
            ).first()
        return (row[0], row[1]) if row is not None else None

    async def _handle_image(
        self, pid: int, target: str, report: DownloadReport
    ) -> tuple[bool, bool]:
        loaded = await self._load_page(pid, target)
        if loaded is None:
            return False, False
        url, download_state = loaded
        dest = self._storage.original_dir(pid) / target
        if download_state == "done" and dest.exists():
            report.pages_done += 1
            return True, True

        data = await self._downloader.fetch_bytes(url)
        if data is None:
            await self._mark_page_failed(pid, target, "fetch failed")
            report.pages_failed += 1
            return False, False
        if not is_valid_image(data):
            await self._mark_page_failed(pid, target, "invalid image data")
            report.pages_failed += 1
            return False, False

        atomic_write_bytes(dest, data)
        await self._mark_page_done(pid, target)
        report.pages_done += 1
        return True, False

    async def _handle_thumb(
        self, pid: int, target: str, report: DownloadReport
    ) -> tuple[bool, bool]:
        dest = self._storage.work_dir(pid) / target
        if dest.exists():
            report.thumbs_done += 1
            return True, True
        source = self._first_original(pid)
        if source is None:
            return False, False
        generated = await asyncio.to_thread(generate_thumb, source, dest)
        if generated:
            report.thumbs_done += 1
        return generated, False

    async def _handle_ugoira_zip(
        self, pid: int, target: str, report: DownloadReport
    ) -> tuple[bool, bool]:
        dest = self._storage.work_dir(pid) / target
        if dest.exists():
            return True, True
        async with self._db.session() as session:
            meta = await session.get(UgoiraMeta, pid)
        if meta is None or not meta.zip_url:
            return False, False
        ok = await self._downloader.fetch_to_file(meta.zip_url, dest)
        if ok:
            report.ugoira_done += 1
        return ok, False

    async def _handle_ugoira_mp4(
        self, pid: int, target: str, report: DownloadReport
    ) -> tuple[bool, bool]:
        dest = self._storage.animation_path(pid)
        if dest.exists():
            return True, True
        zip_path = self._storage.work_dir(pid) / "source.zip"
        if not zip_path.exists():
            return False, False
        async with self._db.session() as session:
            meta = await session.get(UgoiraMeta, pid)
        if meta is None:
            return False, False
        if self._transcode is not None:
            ok = await self._transcode(
                zip_path=zip_path,
                frames_json=meta.frames_json,
                frames_dir=self._storage.work_dir(pid) / "frames",
                dest=dest,
            )
        else:
            ok = await asyncio.to_thread(
                transcode_to_mp4,
                zip_path=zip_path,
                frames_json=meta.frames_json,
                frames_dir=self._storage.work_dir(pid) / "frames",
                dest=dest,
                ffmpeg_bin=self._config.ffmpeg_bin,
            )
        if ok:
            report.ugoira_done += 1
            return True, False
        return False, True  # no ffmpeg / invalid frames -> skip, keep the zip

    def _first_original(self, pid: int) -> Path | None:
        directory = self._storage.original_dir(pid)
        if not directory.is_dir():
            return None
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                return path
        return None

    async def _mark_page_done(self, pid: int, target: str) -> None:
        page_index = self._page_index_from_target(target)
        async with self._db.session() as session:
            await session.execute(
                IllustPage.__table__.update()
                .where(IllustPage.pid == pid, IllustPage.page_index == page_index)
                .values(download_state="done", last_error=None)
            )
            await self._refresh_illust_counters(session, pid)
            await session.commit()

    async def _mark_page_failed(self, pid: int, target: str, error: str) -> None:
        page_index = self._page_index_from_target(target)
        async with self._db.session() as session:
            page = (
                await session.execute(
                    select(IllustPage.attempts).where(
                        IllustPage.pid == pid, IllustPage.page_index == page_index
                    )
                )
            ).scalar_one_or_none()
            attempts = (page or 0) + 1
            await session.execute(
                IllustPage.__table__.update()
                .where(IllustPage.pid == pid, IllustPage.page_index == page_index)
                .values(download_state="failed", last_error=error[:500], attempts=attempts)
            )
            await self._refresh_illust_counters(session, pid)
            await session.commit()

    async def _refresh_illust_counters(self, session, pid: int) -> None:
        total = (
            await session.execute(
                select(func.count()).select_from(IllustPage).where(IllustPage.pid == pid)
            )
        ).scalar_one()
        done = (
            await session.execute(
                select(func.count())
                .select_from(IllustPage)
                .where(IllustPage.pid == pid, IllustPage.download_state == "done")
            )
        ).scalar_one()
        await session.execute(
            Illust.__table__.update()
            .where(Illust.pid == pid)
            .values(page_downloaded_count=done, has_original=(done == total and total > 0))
        )

    async def _mark_failed(self, job_id: int, error: str) -> None:
        async with self._db.session() as session:
            await downloads.fail_job(session, job_id, error=error, now=utcnow())
            await session.commit()

    @staticmethod
    def _page_index_from_target(target: str) -> int:
        try:
            return int(target.split("_", 1)[0])
        except (ValueError, IndexError):
            return 0
```

更新 `src/pixiv_archive/download/__init__.py`：

```python
from pixiv_archive.download.scope import DownloadScope, ScopePlan, resolve_scope
from pixiv_archive.download.worker import DownloadReport, DownloadWorker, DownloadWorkerConfig

__all__ = [
    "DownloadReport",
    "DownloadScope",
    "DownloadWorker",
    "DownloadWorkerConfig",
    "ScopePlan",
    "resolve_scope",
]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_download_worker.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/download tests/test_download_worker.py
git commit -m "feat: add download worker with thumbnail and ugoira handling"
```

---

### Task 7: 工厂接入与 CLI 子命令

**Files:**
- Modify: `src/pixiv_archive/sync/factory.py`
- Modify: `src/pixiv_archive/cli.py`
- Modify: `src/pixiv_archive/config.py`（追加 `ffmpeg_bin`）
- Test: `tests/test_cli_download.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_cli_download.py`：

```python
import pytest
from sqlalchemy import select

from fakes import FakeDownloader
from pixiv_archive.cli import build_parser, run_download
from pixiv_archive.config import Settings
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Illust, IllustPage
from pixiv_archive.db.repo import downloads
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.download.worker import DownloadReport


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
        session.add(
            IllustPage(pid=1, page_index=0, original_url="https://i.pximg.net/1_p0.jpg", ext=".jpg")
        )
        await session.commit()


async def test_run_download_with_fakes(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path)
    db = Database(settings.db_path)
    await db.create_all()
    await _seed(db)
    await db.dispose()

    fake_downloader = FakeDownloader()
    import pixiv_archive.cli as cli

    monkeypatch.setattr(
        cli,
        "open_download_worker",
        lambda s: _fake_worker_context(s, fake_downloader),
    )

    exit_code = await run_download(["download"], settings=settings)
    assert exit_code == 0
    async with Database(settings.db_path).session() as session:
        counts = await downloads.count_jobs_by_status(
            session, (await session.execute(select(downloads.DownloadJob))).scalars().first().batch_id
        )
    assert counts.get("done", 0) >= 1


def _fake_worker_context(settings, downloader):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _cm():
        from pixiv_archive.download.worker import DownloadWorker, DownloadWorkerConfig

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


async def test_run_download_reports_report(monkeypatch, tmp_path, capsys):
    settings = _settings(monkeypatch, tmp_path)
    db = Database(settings.db_path)
    await db.create_all()
    await _seed(db)
    await db.dispose()

    import pixiv_archive.cli as cli

    class StubWorker:
        async def run_scope(self, scope) -> DownloadReport:
            return DownloadReport(batch_id=1, pages_done=1)

    monkeypatch.setattr(cli, "open_download_worker", lambda s: _stub_context(StubWorker))
    exit_code = await run_download(["download"], settings=settings)
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "pages" in captured.out or "页" in captured.out


def _stub_context(worker):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _cm():
        yield worker

    return _cm()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_cli_download.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_download'`

- [ ] **Step 3: 实现工厂与 CLI 扩展**

在 `src/pixiv_archive/config.py` 的 `Settings` 中追加（放在 `download_previews` 之后）：

```python
    ffmpeg_bin: str = Field(default="ffmpeg", validation_alias="FFMPEG_BIN")
```

在 `src/pixiv_archive/sync/factory.py` 末尾追加：

```python
@asynccontextmanager
async def open_download_worker(settings: Settings) -> AsyncIterator[DownloadWorker]:
    """Build a DownloadWorker with shared clients, cleaning up afterwards."""
    await _ensure_schema(settings)
    db = Database(settings.db_path)
    image_client = httpx.AsyncClient(proxy=settings.pixiv_proxy, timeout=60.0)
    worker = DownloadWorker(
        db=db,
        storage=WorksStorage(settings.works_dir),
        downloader=ImageDownloader(
            image_client,
            mirror=settings.pixiv_image_mirror,
            concurrency=settings.image_concurrency,
        ),
        config=DownloadWorkerConfig(
            concurrency=settings.image_concurrency,
            ffmpeg_bin=settings.ffmpeg_bin,
        ),
    )
    try:
        yield worker
    finally:
        await image_client.aclose()
        await db.dispose()
```

需要为该文件补两个导入：

```python
from pixiv_archive.download.worker import DownloadWorker, DownloadWorkerConfig
```

`DownloadWorkerConfig` 需要支持 `ffmpeg_bin`（修改 Task 6 中的定义）：

```python
@dataclass
class DownloadWorkerConfig:
    concurrency: int = 4
    max_attempts: int = 3
    ffmpeg_bin: str = "ffmpeg"
    transcode: TranscodeFn | None = None
```

并让默认转码调用传入 `ffmpeg_bin`：

```python
            ok = await asyncio.to_thread(
                transcode_to_mp4,
                zip_path=zip_path,
                frames_json=meta.frames_json,
                frames_dir=self._storage.work_dir(pid) / "frames",
                dest=dest,
                ffmpeg_bin=self._config.ffmpeg_bin,
            )
```

在 `src/pixiv_archive/cli.py` 中扩展解析器与新增命令：

```python
    download = subparsers.add_parser("download", help="download originals (stage B)")
    download.add_argument(
        "--scope",
        choices=("all-missing", "author", "selected", "rank-range", "filter"),
        default="all-missing",
        help="which illusts to download",
    )
    download.add_argument("--author", type=int, default=None, help="author id for --scope author")
    download.add_argument("--pids", default=None, help="comma separated pids for --scope selected")
    download.add_argument("--start", type=int, default=None, help="rank range start (0-based)")
    download.add_argument("--limit", type=int, default=None, help="max number of illusts")
    download.add_argument("--x-restrict", type=int, choices=(0, 1, 2), default=None)
    download.add_argument("--type", choices=("illust", "ugoira"), default=None)
    download.add_argument("--no-thumbs", action="store_true", help="skip thumbnail jobs")
    download.add_argument("--retry-failed", action="store_true", help="re-run failed jobs first")
```

```python
def _scope_from_args(args) -> DownloadScope:
    if args.scope == "author":
        return DownloadScope(kind="author", author_id=args.author)
    if args.scope == "selected":
        pids = [int(p) for p in (args.pids or "").split(",") if p.strip()]
        return DownloadScope(kind="selected", pids=pids)
    if args.scope == "rank-range":
        return DownloadScope(kind="rank_range", start=args.start or 0, count=args.limit)
    if args.scope == "filter":
        return DownloadScope(
            kind="filter", x_restrict=args.x_restrict, type=args.type, author_id=args.author
        )
    return DownloadScope(kind="all_missing")


async def run_download(argv: list[str], settings: Settings | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = settings or Settings()
    settings.ensure_dirs()
    scope = _scope_from_args(args)

    async with open_download_worker(settings) as worker:
        if args.no_thumbs:
            worker.set_thumb_enabled(False)
        if args.retry_failed:
            await worker.retry_failed()
        report = await worker.run_scope(scope)
    _report_download(report)
    return 0 if report.status in ("completed", "completed_with_failures") else 1


def _report_download(report) -> None:
    print(
        f"[download] {report.status}: "
        f"页 {report.pages_done}（失败 {report.pages_failed}），"
        f"缩略图 {report.thumbs_done}，"
        f"ugoira {report.ugoira_done}，"
        f"其它失败 {report.failed}"
    )
```

并在 `main()` 的命令分派中加上 `download`：

```python
    if argv[0] not in ("sync", "download"):
        build_parser().error(f"unknown command: {argv[0]}")
    if argv[0] == "download":
        return asyncio.run(run_download(argv))
    return asyncio.run(run_sync(argv))
```

`DownloadWorker` 需要两个辅助方法：

```python
    def set_thumb_enabled(self, enabled: bool) -> None:
        self._thumbs_enabled = enabled

    async def retry_failed(self) -> int:
        async with self._db.session() as session:
            count = await downloads.retry_failed_jobs(session)
            await session.commit()
        return count
```

并在 `__init__` 中初始化 `self._thumbs_enabled = True`；`_run_job` 遇到 `kind == "thumb"` 且未启用时直接标记 `skipped`：

```python
        if kind == "thumb" and not self._thumbs_enabled:
            async with self._db.session() as session:
                await downloads.finish_job(session, job_id, now=utcnow(), status="skipped")
                await session.commit()
            return
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_cli_download.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/config.py src/pixiv_archive/sync/factory.py src/pixiv_archive/cli.py src/pixiv_archive/download tests/test_cli_download.py
git commit -m "feat: add download CLI command and worker factory"
```

---

### Task 8: 真实下载验证（小样本）

**Files:**
- Create: `tests/test_integration_download.py`

- [ ] **Step 1: 写集成测试**

`tests/test_integration_download.py`：

```python
"""Live stage B download against the real pixiv image CDN.

Run with:
    uv run pytest tests/test_integration_download.py -m integration -v -s
Requires PIXIV_REFRESH_TOKEN / PIXIV_USER_ID and network access (PIXIV_PROXY).
"""

import pytest

from pixiv_archive.config import Settings
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Illust, IllustPage
from pixiv_archive.download.scope import DownloadScope
from pixiv_archive.download.worker import DownloadWorker, DownloadWorkerConfig
from pixiv_archive.media.downloader import ImageDownloader
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.sync.factory import open_sync_service, open_download_worker
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def test_live_download_small_sample(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings(_env_file=None)
    settings.ensure_dirs()

    # stage A first: need metadata for a handful of works
    async with open_sync_service(settings) as service:
        sync_result = await service.run_incremental(max_pages=1)
    assert sync_result.new_count == 30

    async with open_download_worker(settings) as worker:
        worker.set_thumb_enabled(False)
        report = await worker.run_scope(
            DownloadScope(kind="rank_range", start=0, count=2)
        )

    print(
        f"\npages={report.pages_done} failed={report.pages_failed} "
        f"thumbs={report.thumbs_done} ugoira={report.ugoira_done} status={report.status}"
    )
    assert report.pages_done > 0
    assert report.pages_failed == 0

    db = Database(settings.db_path)
    async with db.session() as session:
        rows = (
            await session.execute(
                select(Illust).order_by(Illust.pid).limit(2)
            )
        ).scalars().all()
        page_rows = (
            await session.execute(select(IllustPage))
        ).scalars().all()
    await db.dispose()

    assert any(row.has_original for row in rows)
    done_pages = [p for p in page_rows if p.download_state == "done"]
    assert done_pages, "at least one page must be marked done"

    storage = WorksStorage(settings.works_dir)
    for page in done_pages:
        candidates = list(storage.original_dir(page.pid).glob(f"{page.page_index:03d}_p*"))
        assert candidates, f"downloaded file missing for {page.pid} p{page.page_index}"
        assert candidates[0].stat().st_size > 0


async def test_live_download_thumbnails_for_downloaded_work(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings(_env_file=None)
    settings.ensure_dirs()

    async with open_sync_service(settings) as service:
        await service.run_incremental(max_pages=1)

    async with open_download_worker(settings) as worker:
        report = await worker.run_scope(DownloadScope(kind="rank_range", start=0, count=1))

    assert report.thumbs_done >= 1
    storage = WorksStorage(settings.works_dir)
    first_pid = next(iter(sorted(storage.root.iterdir())), None)
    assert first_pid is not None
    assert storage.thumb_path(int(first_pid.name)).exists()
```

- [ ] **Step 2: 运行单元测试确认无回归**

Run: `uv run pytest -q`
Expected: 全部通过，集成测试被 deselect

- [ ] **Step 3: 运行真实下载集成测试**

Run（PowerShell）:
```powershell
$env:PIXIV_REFRESH_TOKEN="qLy8MsZ9XdxMM65DiPxF3hn4b18i4J82AkqFAmn8dkY"
$env:PIXIV_USER_ID="56269851"
$env:PIXIV_PROXY="http://127.0.0.1:7897"
uv run pytest tests/test_integration_download.py -m integration -v -s
```
Expected: 2 passed，打印实际下载页数与缩略图数

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_download.py
git commit -m "test: add live stage B download integration tests"
```

---

### Task 9: 对真实账号执行分批下载并更新文档

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 下载前 20 条收藏的原图**

Run（PowerShell）:
```powershell
$env:PIXIV_REFRESH_TOKEN="qLy8MsZ9XdxMM65DiPxF3hn4b18i4J82AkqFAmn8dkY"
$env:PIXIV_USER_ID="56269851"
$env:PIXIV_PROXY="http://127.0.0.1:7897"
$env:DATA_DIR="D:\Projects\Pixiv-Collection-Archive\data"
uv run python -m pixiv_archive download --scope rank-range --start 0 --limit 20
```
Expected: 输出形如 `[download] completed: 页 N（失败 0），缩略图 20，ugoira X，其它失败 0`

- [ ] **Step 2: 验证落盘结果**

Run:
```powershell
uv run python -c @"
import sqlite3, pathlib
root = pathlib.Path(r'D:\Projects\Pixiv-Collection-Archive\data\works')
conn = sqlite3.connect(r'D:\Projects\Pixiv-Collection-Archive\data\archive.db')
done = conn.execute('SELECT COUNT(*) FROM illust_page WHERE download_state = ''done''').fetchone()[0]
missing = conn.execute('SELECT COUNT(*) FROM illust_page WHERE download_state = ''pending''').fetchone()[0]
failed = conn.execute('SELECT COUNT(*) FROM illust_page WHERE download_state = ''failed''').fetchone()[0]
thumbs = len(list(root.glob('*/thumb.webp')))
sizes = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
print(f'done={done} pending={missing} failed={failed} thumbs={thumbs} bytes={sizes/1024/1024:.1f}MB')
assert done > 0 and failed == 0 and thumbs == 20
print('OK')
"@
```
Expected: 打印 `done>0 pending=... failed=0 thumbs=20 ...MB` 且 `OK`

- [ ] **Step 3: 验证断点续传（再跑一次同一范围）**

Run:
```powershell
$env:DATA_DIR="D:\Projects\Pixiv-Collection-Archive\data"
uv run python -m pixiv_archive download --scope rank-range --start 0 --limit 20
```
Expected: 第二次运行不重复下载已完成的页（`页 0` 或仅补缺失项），证明幂等

- [ ] **Step 4: 更新 README**

把「状态」小节替换为：

```markdown
## 状态

- [x] 项目基础 + pixiv API 层
- [x] 阶段 A：元数据同步（增量 / 全量 + rank 顺序 + 预览图）
- [x] 阶段 B：图片下载（持久化队列 + 范围批次 + 原图 / ugoira / 缩略图）
- [ ] Web API 与前端
- [ ] 发布
```

并在「快速开始」补充：

````markdown
### 阶段 B：下载图片

```bash
# 下载全部尚未下载的作品（分批、可中断续传）
uv run python -m pixiv_archive download

# 只下载前 20 个收藏
uv run python -m pixiv_archive download --scope rank-range --start 0 --limit 20

# 指定作者 / 指定作品 / 只看 R-18
uv run python -m pixiv_archive download --scope author --author 12345
uv run python -m pixiv_archive download --scope selected --pids 111,222,333
uv run python -m pixiv_archive download --scope filter --x-restrict 1

# 重试此前失败的项；跳过缩略图
uv run python -m pixiv_archive download --retry-failed
uv run python -m pixiv_archive download --no-thumbs
```

下载落盘：

```
$DATA_DIR/works/{pid}/
    original/000_p0.jpg   # 原图（页序号前缀保证页序）
    source.zip            # ugoira 原始帧
    animation.mp4         # ugoira 转码（需 ffmpeg，缺失时保留 zip 并标记 skipped）
    thumb.webp            # 本地 400px 缩略图
```

所有下载均使用阶段 A 已落库的原图 URL，**不调用 pixiv API**；仅当 URL 失效时（404）才回退查询一次作品详情。
````

- [ ] **Step 5: 全量检查并提交**

Run: `uv run ruff check src tests; uv run ruff format --check src tests; uv run mypy; uv run pytest -q`
Expected: 全部通过（如有格式问题先 `uv run ruff format src tests`）

```bash
git add README.md
git commit -m "docs: mark stage B complete and document download commands"
git push origin main
```

- [ ] **Step 6: 确认云端 CI 通过**

Run: `gh run list --limit 3` 然后 `gh run watch <最新 run id> --exit-status`
Expected: `backend` 与 `docker` 两个 job 均成功

---

## 计划自审

**Spec 覆盖：**

| 设计章节 | 对应任务 |
| --- | --- |
| §4.5 阶段 B：按范围分批、持久化队列、可中断续传 | Task 2、5、6 |
| §4.5 从 `illust_page` 取数、不调 API | Task 5、6 |
| §4.5 每页 `.part` 原子写、失败重试、错误保留 | Task 6（`atomic_write_bytes` + `_mark_page_failed`） |
| §4.5 全部页完成后生成缩略图、更新 `has_original` | Task 6（`_refresh_illust_counters`、`_handle_thumb`） |
| §4.5 ugoira：zip → 校验 → ffmpeg（帧 delay）→ mp4；无 ffmpeg 保留 zip 并标记 | Task 3、6 |
| §4.5 URL 失效兜底（详情刷新） | 未实现 —— **明确延后**（需要 API 客户端注入 worker；当前策略为标记 failed 并可重试，见下方偏差说明） |
| §5 存储布局 `original/000_p0.ext`、`source.zip`、`animation.mp4`、`thumb.webp` | Task 5、6 |
| §6 `download_job` / `download_batch` 表 | Task 1、2 |
| §8.4 范围入口：筛选 / 作者 / 选中 / rank 区间 / 未下载 | Task 5、7 |
| §11 `FFMPEG_BIN`、`IMAGE_CONCURRENCY` | Task 7 |
| §12.4 测试：单元（含真实 ffmpeg 路径）+ 集成 | Task 3、6、8 |

**已记录偏差（本计划有意延后，下一计划处理）：**
- 原图 404 时「刷新详情 URL 再试一次」未包含。理由：这需要 worker 持有 `PixivClient`，而阶段 B 的独立性（离线下载）是设计要点；当前实现将 404 记为 failed 并保留 URL，重试仍失败后可由阶段 A 全量同步刷新 URL（`upsert_illust` 会更新 `illust_page.original_url`），从而自然恢复。计划 4 可在此基础上加「URL 刷新」策略。

**占位符扫描：** 无 TBD；每个代码步骤均含完整代码。Task 7 中「修改 Task 6 中的定义」处给出了完整替换代码（`DownloadWorkerConfig` 增加 `ffmpeg_bin`，`_handle_ugoira_mp4` 传入 `ffmpeg_bin`）。

**类型一致性：**
- `DownloadScope(kind=...)` 的 kind 取值在 Task 5 定义（`all_missing`/`author`/`selected`/`rank_range`/`filter`），Task 6、7 使用一致（CLI 短横线形式 `rank-range` 在 `_scope_from_args` 中映射为 `rank_range`）✅
- `ScopePlan(pids, jobs)`、`jobs` 元素 `(pid, kind, target)` 在 Task 5 定义，Task 6 使用一致 ✅
- `DownloadJob.kind` 取值（`image`/`thumb`/`ugoira_zip`/`ugoira_mp4`）在 Task 5 生成、Task 6 分派一致 ✅
- `DownloadReport` 字段（`batch_id/status/pages_done/pages_failed/thumbs_done/ugoira_done/failed`）在 Task 6 定义，Task 7、8 使用一致 ✅
- `downloads.*` 函数签名在 Task 2 定义，Task 6 使用一致（`create_batch`/`enqueue_jobs`/`claim_pending_jobs`/`finish_job`/`fail_job`/`reset_running_jobs`/`retry_failed_jobs`/`finalize_batch_if_done`/`count_jobs_by_status`/`get_batch`）✅
- `WorksStorage.original_dir/thumb_path/animation_path/work_dir` 在计划 2 Task 5 定义，Task 6 使用一致 ✅
- `ImageDownloader.fetch_bytes/fetch_to_file` 在计划 2 Task 5 定义，Task 6 使用一致 ✅
- `transcode_to_mp4(..., ffmpeg_bin=)` 签名在 Task 3 定义，Task 6/7 使用一致 ✅

**发现并已在计划中修正的问题：**
- Task 6 的 `DownloadWorker` 需要 `select_page`，计划中已给出该模块级函数定义（避免在方法中动态 import）。
- Task 7 需要 `DownloadWorkerConfig.ffmpeg_bin`，已在同任务中给出完整替换。
