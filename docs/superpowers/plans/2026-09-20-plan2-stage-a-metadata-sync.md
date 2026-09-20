# 计划 2：阶段 A 元数据同步

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 pixiv 收藏的元数据同步（阶段 A）：把收藏列表的元数据、顺序（rank）、标签、原图 URL、ugoira 元数据落库，并拉取预览图，使画廊可在不下载原图的情况下完整浏览。

**Architecture:** 新增 `db/repo/` 仓储层（illust/author/tag/page 的 upsert、bookmark 的 rank 操作、sync_run 记录）；`media/` 提供作品目录管理（`WorksStorage`）与图片字节下载（`ImageDownloader`，含镜像回退与原子写）；`sync/` 提供纯函数 rank 分配（`rank.py`）、元数据同步编排（`orchestrator.py`，增量 + 全量）、APScheduler 调度（`scheduler.py`）与服务工厂（`factory.py`）；`cli.py` 提供 `python -m pixiv_archive sync` 入口。

**Tech Stack:** Python 3.12、SQLAlchemy 2.x async（SQLite upsert via `sqlite.insert`）、pydantic、httpx、APScheduler 3.x、pytest + pytest-asyncio

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `src/pixiv_archive/db/models.py` | 追加 Tag / IllustTag / IllustPage / UgoiraMeta / SyncRun |
| `src/pixiv_archive/db/migrations/versions/0002_metadata_tables.py` | 对应迁移 |
| `src/pixiv_archive/db/repo/__init__.py` | 导出 |
| `src/pixiv_archive/db/repo/illusts.py` | author/illust/tag/page/ugoira_meta 的 upsert 与查询 |
| `src/pixiv_archive/db/repo/bookmarks.py` | rank 分配、seen 更新、取消收藏标记、查询 |
| `src/pixiv_archive/db/repo/sync_runs.py` | 同步运行记录 |
| `src/pixiv_archive/media/__init__.py` | 导出 |
| `src/pixiv_archive/media/storage.py` | 作品目录布局、原子写、meta.json 快照 |
| `src/pixiv_archive/media/downloader.py` | 图片字节下载（镜像回退、重试、并发信号量） |
| `src/pixiv_archive/sync/__init__.py` | 导出 |
| `src/pixiv_archive/sync/rank.py` | rank 分配纯函数 |
| `src/pixiv_archive/sync/orchestrator.py` | `MetadataSyncService`：增量/全量同步编排 |
| `src/pixiv_archive/sync/scheduler.py` | 间隔解析与 APScheduler 装配 |
| `src/pixiv_archive/sync/factory.py` | `open_sync_service` 异步上下文管理器 |
| `src/pixiv_archive/cli.py` | `sync` 子命令 |
| `src/pixiv_archive/__main__.py` | 分发 CLI 或 uvicorn |
| `tests/test_metadata_models.py` 等 | 单元与集成测试 |

---

### Task 1: 元数据表模型与迁移 0002

**Files:**
- Modify: `src/pixiv_archive/db/models.py`
- Create: `src/pixiv_archive/db/migrations/versions/0002_metadata_tables.py`
- Test: `tests/test_metadata_models.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_metadata_models.py`：

```python
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import (
    Author,
    Illust,
    IllustPage,
    IllustTag,
    SyncRun,
    Tag,
    UgoiraMeta,
)


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "meta.db")
    await database.create_all()
    yield database
    await database.dispose()


async def test_metadata_tables_exist(db):
    from sqlalchemy import text

    async with db.session() as session:
        rows = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        names = {r[0] for r in rows}
    assert {"tag", "illust_tag", "illust_page", "ugoira_meta", "sync_run"} <= names


async def test_illust_page_composite_key(db):
    async with db.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=10, title="x", author_id=1, page_count=2))
        await session.commit()
    async with db.session() as session:
        session.add(IllustPage(pid=10, page_index=0, original_url="u0", ext=".jpg"))
        session.add(IllustPage(pid=10, page_index=1, original_url="u1", ext=".png"))
        await session.commit()
    with pytest.raises(IntegrityError):
        async with db.session() as session:
            session.add(IllustPage(pid=10, page_index=0, original_url="dup", ext=".jpg"))
            await session.commit()


async def test_tag_name_unique(db):
    async with db.session() as session:
        session.add(Tag(name="R-18"))
        await session.commit()
    with pytest.raises(IntegrityError):
        async with db.session() as session:
            session.add(Tag(name="R-18"))
            await session.commit()


async def test_illust_tag_position(db):
    async with db.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=10, title="x", author_id=1))
        session.add(Tag(name="t1"))
        session.add(Tag(name="t2"))
        await session.flush()
        tags = (await session.execute(select(Tag.id, Tag.name))).all()
        tag_ids = {name: tid for tid, name in tags}
        session.add(IllustTag(pid=10, tag_id=tag_ids["t1"], position=0))
        session.add(IllustTag(pid=10, tag_id=tag_ids["t2"], position=1))
        await session.commit()
    async with db.session() as session:
        rows = (
            await session.execute(
                select(IllustTag.tag_id, IllustTag.position).where(IllustTag.pid == 10)
            )
        ).all()
    assert sorted(p for _, p in rows) == [0, 1]


async def test_ugoira_meta_roundtrip(db):
    async with db.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=10, title="u", author_id=1, type="ugoira"))
        await session.commit()
    async with db.session() as session:
        session.add(
            UgoiraMeta(
                pid=10,
                zip_url="https://i.pximg.net/u.zip",
                frames_json='[{"file": "000000.jpg", "delay": 33}]',
                frame_count=1,
            )
        )
        await session.commit()
    async with db.session() as session:
        row = (await session.execute(select(UgoiraMeta).where(UgoiraMeta.pid == 10))).scalar_one()
    assert row.frame_count == 1
    assert "000000.jpg" in row.frames_json


async def test_sync_run_defaults(db):
    async with db.session() as session:
        session.add(SyncRun(kind="incremental"))
        await session.commit()
    async with db.session() as session:
        row = (await session.execute(select(SyncRun))).scalar_one()
    assert row.status == "running"
    assert row.pages_fetched == 0
    assert row.finished_at is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_metadata_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'IllustPage'`

- [ ] **Step 3: 追加模型**

在 `src/pixiv_archive/db/models.py` 末尾追加：

```python
class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    translated_name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class IllustTag(Base):
    __tablename__ = "illust_tag"

    pid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("illust.pid"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id"), primary_key=True)
    position: Mapped[int] = mapped_column(default=0)


class IllustPage(Base):
    __tablename__ = "illust_page"

    pid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("illust.pid"), primary_key=True
    )
    page_index: Mapped[int] = mapped_column(primary_key=True)
    original_url: Mapped[str] = mapped_column(String(1024))
    ext: Mapped[str] = mapped_column(String(16), default=".jpg")
    download_state: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class UgoiraMeta(Base):
    __tablename__ = "ugoira_meta"

    pid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("illust.pid"), primary_key=True
    )
    zip_url: Mapped[str] = mapped_column(String(1024), default="")
    frames_json: Mapped[str] = mapped_column(Text, default="[]")
    frame_count: Mapped[int] = mapped_column(default=0)


class SyncRun(Base):
    __tablename__ = "sync_run"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    pages_fetched: Mapped[int] = mapped_column(default=0)
    new_count: Mapped[int] = mapped_column(default=0)
    unbookmarked_count: Mapped[int] = mapped_column(default=0)
    rank_rebuilt_count: Mapped[int] = mapped_column(default=0)
    previews_fetched: Mapped[int] = mapped_column(default=0)
    previews_failed: Mapped[int] = mapped_column(default=0)
    failed_count: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: 写迁移 0002**

`src/pixiv_archive/db/migrations/versions/0002_metadata_tables.py`：

```python
"""metadata tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-20

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("translated_name", sa.String(255), nullable=True),
    )
    op.create_table(
        "illust_tag",
        sa.Column("pid", sa.BigInteger(), sa.ForeignKey("illust.pid"), primary_key=True),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tag.id"), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "illust_page",
        sa.Column("pid", sa.BigInteger(), sa.ForeignKey("illust.pid"), primary_key=True),
        sa.Column("page_index", sa.Integer(), primary_key=True),
        sa.Column("original_url", sa.String(1024), nullable=False),
        sa.Column("ext", sa.String(16), nullable=False, server_default=".jpg"),
        sa.Column("download_state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_table(
        "ugoira_meta",
        sa.Column("pid", sa.BigInteger(), sa.ForeignKey("illust.pid"), primary_key=True),
        sa.Column("zip_url", sa.String(1024), nullable=False, server_default=""),
        sa.Column("frames_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("frame_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "sync_run",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unbookmarked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rank_rebuilt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("previews_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("previews_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sync_run")
    op.drop_table("ugoira_meta")
    op.drop_table("illust_page")
    op.drop_table("illust_tag")
    op.drop_table("tag")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_metadata_models.py tests/test_migrations.py -v`
Expected: 7 passed（含旧的迁移测试，验证 0001→0002 链路可用）

- [ ] **Step 6: Commit**

```bash
git add src/pixiv_archive/db/models.py src/pixiv_archive/db/migrations/versions/0002_metadata_tables.py tests/test_metadata_models.py
git commit -m "feat: add metadata tables (tag, illust_tag, illust_page, ugoira_meta, sync_run)"
```

---

### Task 2: rank 分配纯函数

**Files:**
- Create: `src/pixiv_archive/sync/__init__.py`
- Create: `src/pixiv_archive/sync/rank.py`
- Test: `tests/test_rank.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_rank.py`：

```python
from pixiv_archive.sync.rank import RANK_SPACING, full_rank, incremental_ranks


def test_incremental_ranks_empty():
    assert incremental_ranks(None, 0) == []
    assert incremental_ranks(500, 0) == []


def test_incremental_ranks_first_batch_places_newest_first():
    ranks = incremental_ranks(None, 3)
    assert ranks == [-3072, -2048, -1024]
    # index 0 is the newest bookmark -> smallest rank -> appears first
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == 3


def test_incremental_ranks_second_batch_is_placed_in_front():
    first = incremental_ranks(None, 2)
    second = incremental_ranks(min(first), 2)
    assert all(r < min(first) for r in second)
    assert second == sorted(second)


def test_incremental_ranks_preserve_listing_order_within_batch():
    ranks = incremental_ranks(0, 4)
    assert ranks[0] < ranks[1] < ranks[2] < ranks[3]


def test_incremental_ranks_spacing_is_constant():
    ranks = incremental_ranks(None, 5)
    gaps = {b - a for a, b in zip(ranks, ranks[1:], strict=False)}
    assert gaps == {RANK_SPACING}


def test_full_rank_is_position_times_spacing():
    assert full_rank(0) == 0
    assert full_rank(1) == RANK_SPACING
    assert full_rank(100) == 100 * RANK_SPACING
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_rank.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.sync'`

- [ ] **Step 3: 实现 rank.py**

`src/pixiv_archive/sync/rank.py`：

```python
"""Rank allocation for bookmark ordering.

Rank is an integer where smaller means "more recently bookmarked", so that
ordering by rank ascending reproduces the pixiv bookmark list order.

Bookmarks are given sparse ranks (multiples of ``RANK_SPACING``) so that new
batches can always be inserted in front with O(1) work and without touching
existing rows.
"""

RANK_SPACING = 1024


def incremental_ranks(min_rank: int | None, count: int) -> list[int]:
    """Ranks for a batch of newly discovered bookmarks, newest first.

    The whole batch is placed in front of every existing bookmark while
    preserving the listing order: index 0 receives the smallest rank.
    """
    if count <= 0:
        return []
    base = (min_rank if min_rank is not None else 0) - RANK_SPACING * count
    return [base + RANK_SPACING * i for i in range(count)]


def full_rank(position: int) -> int:
    """Rank for a bookmark at a known global list position (0 = newest)."""
    return position * RANK_SPACING
```

`src/pixiv_archive/sync/__init__.py`：

```python
from pixiv_archive.sync.rank import RANK_SPACING, full_rank, incremental_ranks

__all__ = ["RANK_SPACING", "full_rank", "incremental_ranks"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_rank.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/sync/__init__.py src/pixiv_archive/sync/rank.py tests/test_rank.py
git commit -m "feat: add sparse rank allocation functions"
```

---

### Task 3: 仓储层 — illust / author / tag / page / ugoira

**Files:**
- Create: `src/pixiv_archive/db/repo/__init__.py`
- Create: `src/pixiv_archive/db/repo/illusts.py`
- Test: `tests/test_repo_illusts.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_repo_illusts.py`：

```python
import pytest
from sqlalchemy import select

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Illust, IllustPage, IllustTag, Tag
from pixiv_archive.db.repo import illusts
from pixiv_archive.pixiv.models import Illust as PixivIllust


def make_illust(**overrides) -> PixivIllust:
    payload = {
        "id": 100,
        "title": "hello",
        "description": "desc",
        "type": "illust",
        "page_count": 2,
        "width": 1000,
        "height": 2000,
        "x_restrict": 1,
        "sanity_level": 6,
        "illust_ai_type": 2,
        "total_view": 10,
        "total_bookmarks": 20,
        "create_date": "2026-01-02T03:04:05+09:00",
        "user": {"id": 7, "name": "artist", "account": "acct"},
        "tags": [
            {"name": "R-18", "translated_name": None},
            {"name": "オリジナル", "translated_name": "原创"},
        ],
        "meta_pages": [
            {"image_urls": {"original": "https://i.pximg.net/a_p0.jpg"}},
            {"image_urls": {"original": "https://i.pximg.net/a_p1.png"}},
        ],
        "image_urls": {"square_medium": "https://i.pximg.net/a_sq.jpg"},
    }
    payload.update(overrides)
    return PixivIllust.model_validate(payload)


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "repo.db")
    await database.create_all()
    yield database
    await database.dispose()


async def test_url_ext():
    assert illusts.url_ext("https://i.pximg.net/img/a_p0.jpg") == ".jpg"
    assert illusts.url_ext("https://i.pximg.net/img/a_p1.PNG?x=1") == ".png"
    assert illusts.url_ext("https://i.pximg.net/img/noext") == ".jpg"


async def test_upsert_illust_inserts_everything(db):
    illust = make_illust()
    async with db.session() as session:
        await illusts.upsert_illust(session, illust, meta_json='{"id": 100}')
        await session.commit()

    async with db.session() as session:
        row = (await session.execute(select(Illust))).scalar_one()
        assert row.title == "hello"
        assert row.author_id == 7
        assert row.x_restrict == 1
        assert row.meta_json == '{"id": 100}'

        pages = (
            await session.execute(select(IllustPage).order_by(IllustPage.page_index))
        ).scalars().all()
        assert [p.original_url for p in pages] == [
            "https://i.pximg.net/a_p0.jpg",
            "https://i.pximg.net/a_p1.png",
        ]
        assert [p.ext for p in pages] == [".jpg", ".png"]
        assert all(p.download_state == "pending" for p in pages)

        tag_rows = (
            await session.execute(select(Tag.name, Tag.translated_name).order_by(Tag.id))
        ).all()
        assert ("R-18", None) in tag_rows
        assert ("オリジナル", "原创") in tag_rows

        links = (
            await session.execute(
                select(IllustTag.position).where(IllustTag.pid == 100).order_by(IllustTag.position)
            )
        ).scalars().all()
        assert links == [0, 1]


async def test_upsert_illust_updates_without_duplicating(db):
    async with db.session() as session:
        await illusts.upsert_illust(session, make_illust(), meta_json=None)
        await session.commit()
    async with db.session() as session:
        await illusts.upsert_illust(
            session, make_illust(title="renamed", total_bookmarks=999), meta_json=None
        )
        await session.commit()

    async with db.session() as session:
        rows = (await session.execute(select(Illust))).scalars().all()
        assert len(rows) == 1
        assert rows[0].title == "renamed"
        assert rows[0].total_bookmarks == 999
        tags = (await session.execute(select(Tag))).scalars().all()
        assert len(tags) == 2  # tags are replaced, not duplicated


async def test_upsert_illust_preserves_page_download_state(db):
    async with db.session() as session:
        await illusts.upsert_illust(session, make_illust(), meta_json=None)
        await session.commit()
    async with db.session() as session:
        page = (
            await session.execute(select(IllustPage).where(IllustPage.page_index == 0))
        ).scalar_one()
        page.download_state = "done"
        page.attempts = 2
        await session.commit()
    async with db.session() as session:
        await illusts.upsert_illust(
            session,
            make_illust(
                meta_pages=[
                    {"image_urls": {"original": "https://i.pximg.net/a_p0_v2.jpg"}},
                    {"image_urls": {"original": "https://i.pximg.net/a_p1.png"}},
                ]
            ),
            meta_json=None,
        )
        await session.commit()
    async with db.session() as session:
        page = (
            await session.execute(select(IllustPage).where(IllustPage.page_index == 0))
        ).scalar_one()
    assert page.original_url == "https://i.pximg.net/a_p0_v2.jpg"
    assert page.download_state == "done"  # preserved
    assert page.attempts == 2  # preserved


async def test_upsert_illust_handles_single_page(db):
    illust = make_illust(
        page_count=1,
        meta_pages=[],
        meta_single_page={"original_image_url": "https://i.pximg.net/single.jpg"},
    )
    async with db.session() as session:
        await illusts.upsert_illust(session, illust, meta_json=None)
        await session.commit()
    async with db.session() as session:
        pages = (await session.execute(select(IllustPage))).scalars().all()
    assert len(pages) == 1
    assert pages[0].original_url == "https://i.pximg.net/single.jpg"


async def test_get_known_pids(db):
    async with db.session() as session:
        await illusts.upsert_illust(session, make_illust(), meta_json=None)
        await session.commit()
    async with db.session() as session:
        known = await illusts.get_known_pids(session)
    assert known == {100}


async def test_upsert_ugoira_meta(db):
    async with db.session() as session:
        await illusts.upsert_illust(session, make_illust(type="ugoira"), meta_json=None)
        await illusts.upsert_ugoira_meta(
            session,
            pid=100,
            zip_url="https://i.pximg.net/u.zip",
            frames_json='[{"file": "000000.jpg", "delay": 33}]',
            frame_count=1,
        )
        await session.commit()
    async with db.session() as session:
        await illusts.upsert_ugoira_meta(
            session, pid=100, zip_url="https://i.pximg.net/u2.zip", frames_json="[]", frame_count=0
        )
        await session.commit()
    from pixiv_archive.db.models import UgoiraMeta

    async with db.session() as session:
        row = (await session.execute(select(UgoiraMeta))).scalar_one()
    assert row.zip_url == "https://i.pximg.net/u2.zip"
    assert row.frame_count == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_repo_illusts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.db.repo'`

- [ ] **Step 3: 实现 repo/illusts.py**

`src/pixiv_archive/db/repo/illusts.py`：

```python
import os
from urllib.parse import urlsplit

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import (
    Author,
    Illust,
    IllustPage,
    IllustTag,
    Tag,
    UgoiraMeta,
    utcnow,
)
from pixiv_archive.pixiv.models import Illust as PixivIllust

_DEFAULT_EXT = ".jpg"


def url_ext(url: str) -> str:
    ext = os.path.splitext(urlsplit(url).path)[1].lower()
    return ext or _DEFAULT_EXT


async def upsert_illust(
    session: AsyncSession, illust: PixivIllust, *, meta_json: str | None
) -> None:
    """Insert or refresh one illust with its author, tags and pages.

    Existing rows keep their ``page.download_state``/``attempts`` and
    ``bookmark`` linkage; only metadata columns are refreshed.
    """
    await _upsert_author(session, illust)
    values = {
        "pid": illust.pid,
        "title": illust.title,
        "description": illust.description,
        "author_id": illust.user.id,
        "create_date": illust.create_date.replace(tzinfo=None) if illust.create_date else None,
        "page_count": illust.page_count,
        "width": illust.width,
        "height": illust.height,
        "type": illust.type,
        "x_restrict": illust.x_restrict,
        "sanity_level": illust.sanity_level,
        "illust_ai_type": illust.illust_ai_type,
        "total_view": illust.total_view,
        "total_bookmarks": illust.total_bookmarks,
        "state": "active",
        "meta_json": meta_json,
        "updated_at": utcnow(),
    }
    stmt = insert(Illust).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Illust.pid],
        set_={key: value for key, value in values.items() if key != "pid"},
    )
    await session.execute(stmt)
    await _replace_tags(session, illust)
    await _upsert_pages(session, illust)


async def _upsert_author(session: AsyncSession, illust: PixivIllust) -> None:
    stmt = insert(Author).values(
        id=illust.user.id, name=illust.user.name, account=illust.user.account
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Author.id],
        set_={"name": illust.user.name, "account": illust.user.account},
    )
    await session.execute(stmt)


async def _replace_tags(session: AsyncSession, illust: PixivIllust) -> None:
    await session.execute(delete(IllustTag).where(IllustTag.pid == illust.pid))
    for position, tag in enumerate(illust.tags):
        if not tag.name:
            continue
        tag_id = await _ensure_tag(session, tag.name, tag.translated_name)
        link = insert(IllustTag).values(pid=illust.pid, tag_id=tag_id, position=position)
        link = link.on_conflict_do_nothing(index_elements=[IllustTag.pid, IllustTag.tag_id])
        await session.execute(link)


async def _ensure_tag(session: AsyncSession, name: str, translated_name: str | None) -> int:
    existing = (
        await session.execute(select(Tag.id).where(Tag.name == name))
    ).scalar_one_or_none()
    if existing is not None:
        if translated_name:
            await session.execute(
                update(Tag).where(Tag.id == existing).values(translated_name=translated_name)
            )
        return existing
    tag = Tag(name=name, translated_name=translated_name)
    session.add(tag)
    await session.flush()
    return tag.id


async def _upsert_pages(session: AsyncSession, illust: PixivIllust) -> None:
    for index, url in enumerate(illust.original_urls):
        ext = url_ext(url)
        stmt = insert(IllustPage).values(
            pid=illust.pid, page_index=index, original_url=url, ext=ext
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[IllustPage.pid, IllustPage.page_index],
            set_={"original_url": url, "ext": ext},
        )
        await session.execute(stmt)


async def upsert_ugoira_meta(
    session: AsyncSession,
    *,
    pid: int,
    zip_url: str,
    frames_json: str,
    frame_count: int,
) -> None:
    stmt = insert(UgoiraMeta).values(
        pid=pid, zip_url=zip_url, frames_json=frames_json, frame_count=frame_count
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[UgoiraMeta.pid],
        set_={"zip_url": zip_url, "frames_json": frames_json, "frame_count": frame_count},
    )
    await session.execute(stmt)


async def get_known_pids(session: AsyncSession) -> set[int]:
    rows = await session.execute(select(Illust.pid))
    return {row[0] for row in rows}
```

`src/pixiv_archive/db/repo/__init__.py`：

```python
from pixiv_archive.db.repo import bookmarks, illusts, sync_runs

__all__ = ["bookmarks", "illusts", "sync_runs"]
```

> 注意：`__init__.py` 同时导入 `bookmarks` 与 `sync_runs`，它们会在 Task 4 创建。若在本任务后立即运行导入测试会失败——因此本任务的 `__init__.py` 先写成：

```python
from pixiv_archive.db.repo import illusts

__all__ = ["illusts"]
```

（Task 4 中再补全另外两个。）

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_repo_illusts.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/db/repo tests/test_repo_illusts.py
git commit -m "feat: add illust/author/tag/page/ugoira repository with upserts"
```

---

### Task 4: 仓储层 — bookmark 与 sync_run

**Files:**
- Create: `src/pixiv_archive/db/repo/bookmarks.py`
- Create: `src/pixiv_archive/db/repo/sync_runs.py`
- Modify: `src/pixiv_archive/db/repo/__init__.py`
- Test: `tests/test_repo_bookmarks.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_repo_bookmarks.py`：

```python
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Illust, SyncRun
from pixiv_archive.db.repo import bookmarks, sync_runs


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "bm.db")
    await database.create_all()
    yield database
    await database.dispose()


async def _seed_illust(db, pid: int) -> None:
    async with db.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=pid, title=f"t{pid}", author_id=1))
        await session.commit()


async def test_set_active_rank_inserts(db):
    await _seed_illust(db, 1)
    async with db.session() as session:
        created = await bookmarks.set_active_rank(
            session, pid=1, restrict="public", rank=100, now=datetime.now(UTC)
        )
        await session.commit()
    assert created is True
    async with db.session() as session:
        states = await bookmarks.get_bookmark_states(session)
    assert states == {1: "active"}


async def test_set_active_rank_reactivates_unbookmarked(db):
    await _seed_illust(db, 1)
    now = datetime.now(UTC)
    async with db.session() as session:
        await bookmarks.set_active_rank(session, pid=1, restrict="public", rank=100, now=now)
        await session.commit()
    async with db.session() as session:
        await bookmarks.mark_unbookmarked(session, [1], now=now)
        await session.commit()
    async with db.session() as session:
        states = await bookmarks.get_bookmark_states(session)
    assert states == {1: "unbookmarked"}

    async with db.session() as session:
        created = await bookmarks.set_active_rank(
            session, pid=1, restrict="private", rank=-500, now=now + timedelta(hours=1)
        )
        await session.commit()
    assert created is False  # row existed, was reactivated
    async with db.session() as session:
        states = await bookmarks.get_bookmark_states(session)
        min_rank = await bookmarks.get_min_rank(session)
    assert states == {1: "active"}
    assert min_rank == -500


async def test_touch_seen_updates_last_seen_only(db):
    await _seed_illust(db, 1)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 6, 1, tzinfo=UTC)
    async with db.session() as session:
        await bookmarks.set_active_rank(session, pid=1, restrict="public", rank=0, now=t0)
        await session.commit()
    async with db.session() as session:
        await bookmarks.touch_seen(session, [1], now=t1)
        await session.commit()
    async with db.session() as session:
        row = (await session.execute(select(bookmarks.Bookmark))).scalar_one()
    assert row.first_seen_at == t0.replace(tzinfo=None)
    assert row.last_seen_at == t1.replace(tzinfo=None)
    assert row.rank == 0


async def test_mark_unbookmarked_sets_state_and_timestamp(db):
    await _seed_illust(db, 1)
    await _seed_illust(db, 2)
    now = datetime(2026, 2, 2, tzinfo=UTC)
    async with db.session() as session:
        await bookmarks.set_active_rank(session, pid=1, restrict="public", rank=0, now=now)
        await bookmarks.set_active_rank(session, pid=2, restrict="public", rank=10, now=now)
        await session.commit()
    async with db.session() as session:
        count = await bookmarks.mark_unbookmarked(session, [2], now=now)
        await session.commit()
    assert count == 1
    async with db.session() as session:
        states = await bookmarks.get_bookmark_states(session)
        row = (
            await session.execute(select(bookmarks.Bookmark).where(bookmarks.Bookmark.pid == 2))
        ).scalar_one()
    assert states == {1: "active", 2: "unbookmarked"}
    assert row.unbookmarked_at == now.replace(tzinfo=None)


async def test_get_min_rank_and_rank_map(db):
    await _seed_illust(db, 1)
    await _seed_illust(db, 2)
    now = datetime.now(UTC)
    async with db.session() as session:
        await bookmarks.set_active_rank(session, pid=1, restrict="public", rank=500, now=now)
        await bookmarks.set_active_rank(session, pid=2, restrict="public", rank=100, now=now)
        await session.commit()
    async with db.session() as session:
        assert await bookmarks.get_min_rank(session) == 100
        assert await bookmarks.get_rank_map(session) == {1: 500, 2: 100}


async def test_get_min_rank_returns_none_when_empty(db):
    async with db.session() as session:
        assert await bookmarks.get_min_rank(session) is None
        assert await bookmarks.get_rank_map(session) == {}


async def test_ordered_pids_puts_active_first_by_rank(db):
    await _seed_illust(db, 1)
    await _seed_illust(db, 2)
    await _seed_illust(db, 3)
    now = datetime.now(UTC)
    async with db.session() as session:
        await bookmarks.set_active_rank(session, pid=2, restrict="public", rank=200, now=now)
        await bookmarks.set_active_rank(session, pid=1, restrict="public", rank=100, now=now)
        await bookmarks.set_active_rank(session, pid=3, restrict="public", rank=300, now=now)
        await bookmarks.mark_unbookmarked(session, [3], now=now)
        await session.commit()
    async with db.session() as session:
        pids = await bookmarks.ordered_pids(session)
    assert pids == [1, 2, 3]  # rank order; unbookmarked last


async def test_sync_runs_lifecycle(db):
    now = datetime(2026, 3, 3, tzinfo=UTC)
    async with db.session() as session:
        run_id = await sync_runs.create_run(session, "incremental", now=now)
        await session.commit()
    assert run_id > 0
    async with db.session() as session:
        await sync_runs.finish_run(
            session,
            run_id,
            status="completed",
            pages_fetched=3,
            new_count=5,
            unbookmarked_count=1,
            rank_rebuilt_count=0,
            previews_fetched=5,
            previews_failed=0,
            failed_count=0,
            error=None,
            now=now + timedelta(minutes=1),
        )
        await session.commit()
    async with db.session() as session:
        row = (await session.execute(select(SyncRun))).scalar_one()
    assert row.status == "completed"
    assert row.new_count == 5
    assert row.finished_at is not None
    async with db.session() as session:
        last_full = await sync_runs.get_last_full_sync(session)
    assert last_full is None


async def test_get_last_full_sync(db):
    now = datetime(2026, 4, 4, tzinfo=UTC)
    async with db.session() as session:
        run_id = await sync_runs.create_run(session, "full", now=now)
        await sync_runs.finish_run(
            session,
            run_id,
            status="completed",
            pages_fetched=69,
            new_count=0,
            unbookmarked_count=0,
            rank_rebuilt_count=0,
            previews_fetched=0,
            previews_failed=0,
            failed_count=0,
            error=None,
            now=now,
        )
        await session.commit()
    async with db.session() as session:
        last_full = await sync_runs.get_last_full_sync(session)
    assert last_full == now.replace(tzinfo=None)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_repo_bookmarks.py -v`
Expected: FAIL — `ImportError: cannot import name 'bookmarks'`

- [ ] **Step 3: 实现 bookmarks.py 与 sync_runs.py**

`src/pixiv_archive/db/repo/bookmarks.py`：

```python
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Bookmark


async def get_bookmark_states(session: AsyncSession) -> dict[int, str]:
    rows = await session.execute(select(Bookmark.pid, Bookmark.state))
    return {pid: state for pid, state in rows}


async def get_rank_map(session: AsyncSession) -> dict[int, int]:
    rows = await session.execute(select(Bookmark.pid, Bookmark.rank))
    return {pid: rank for pid, rank in rows}


async def get_min_rank(session: AsyncSession) -> int | None:
    return (await session.execute(select(Bookmark.rank).order_by(Bookmark.rank).limit(1))).scalar()


async def set_active_rank(
    session: AsyncSession, *, pid: int, restrict: str, rank: int, now: datetime
) -> bool:
    """Insert a bookmark or reactivate/relocate an existing one.

    Returns True when a new row was created.
    """
    existing = (
        await session.execute(select(Bookmark.id).where(Bookmark.pid == pid))
    ).scalar_one_or_none()
    stmt = insert(Bookmark).values(
        pid=pid,
        restrict=restrict,
        rank=rank,
        state="active",
        first_seen_at=now,
        last_seen_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Bookmark.pid],
        set_={
            "restrict": restrict,
            "rank": rank,
            "state": "active",
            "last_seen_at": now,
            "unbookmarked_at": None,
        },
    )
    await session.execute(stmt)
    return existing is None


async def touch_seen(session: AsyncSession, pids: list[int], *, now: datetime) -> None:
    if not pids:
        return
    await session.execute(
        update(Bookmark).where(Bookmark.pid.in_(pids)).values(last_seen_at=now)
    )


async def mark_unbookmarked(session: AsyncSession, pids: list[int], *, now: datetime) -> int:
    if not pids:
        return 0
    result = await session.execute(
        update(Bookmark)
        .where(Bookmark.pid.in_(pids), Bookmark.state == "active")
        .values(state="unbookmarked", unbookmarked_at=now)
    )
    return result.rowcount or 0


async def ordered_pids(session: AsyncSession) -> list[int]:
    """All bookmarked pids ordered by rank; unbookmarked rows sort last."""
    rows = await session.execute(
        select(Bookmark.pid)
        .where(Bookmark.state == "active")
        .order_by(Bookmark.rank)
    )
    active = [row[0] for row in rows]
    if active:
        return active
    rows = await session.execute(select(Bookmark.pid).order_by(Bookmark.rank))
    return [row[0] for row in rows]
```

`src/pixiv_archive/db/repo/sync_runs.py`：

```python
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import SyncRun


async def create_run(session: AsyncSession, kind: str, *, now: datetime) -> int:
    run = SyncRun(kind=kind, status="running", started_at=now)
    session.add(run)
    await session.flush()
    return run.id


async def finish_run(
    session: AsyncSession,
    run_id: int,
    *,
    status: str,
    pages_fetched: int,
    new_count: int,
    unbookmarked_count: int,
    rank_rebuilt_count: int,
    previews_fetched: int,
    previews_failed: int,
    failed_count: int,
    error: str | None,
    now: datetime,
) -> None:
    run = await session.get(SyncRun, run_id)
    if run is None:
        return
    run.status = status
    run.finished_at = now
    run.pages_fetched = pages_fetched
    run.new_count = new_count
    run.unbookmarked_count = unbookmarked_count
    run.rank_rebuilt_count = rank_rebuilt_count
    run.previews_fetched = previews_fetched
    run.previews_failed = previews_failed
    run.failed_count = failed_count
    run.error = error


async def get_last_full_sync(session: AsyncSession) -> datetime | None:
    return (
        await session.execute(
            select(SyncRun.finished_at)
            .where(SyncRun.kind == "full", SyncRun.status == "completed")
            .order_by(SyncRun.finished_at.desc())
            .limit(1)
        )
    ).scalar()
```

补全 `src/pixiv_archive/db/repo/__init__.py`：

```python
from pixiv_archive.db.repo import bookmarks, illusts, sync_runs

__all__ = ["bookmarks", "illusts", "sync_runs"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_repo_bookmarks.py tests/test_repo_illusts.py -v`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/db/repo tests/test_repo_bookmarks.py
git commit -m "feat: add bookmark rank operations and sync run repository"
```

---

### Task 5: 媒体层 — 作品存储与图片下载

**Files:**
- Create: `src/pixiv_archive/media/__init__.py`
- Create: `src/pixiv_archive/media/storage.py`
- Create: `src/pixiv_archive/media/downloader.py`
- Test: `tests/test_media.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_media.py`：

```python
import httpx
import pytest

from pixiv_archive.media.downloader import ImageDownloader, apply_image_mirror
from pixiv_archive.media.storage import WorksStorage, atomic_write_bytes


def test_apply_image_mirror_replaces_official_hosts():
    mirror = "mirror.example.com"
    assert (
        apply_image_mirror("https://i.pximg.net/img/a.jpg?x=1", mirror)
        == "https://mirror.example.com/img/a.jpg?x=1"
    )
    assert (
        apply_image_mirror("https://s.pximg.net/av/b.png", mirror)
        == "https://mirror.example.com/av/b.png"
    )


def test_apply_image_mirror_ignores_other_hosts_and_empty_mirror():
    url = "https://example.com/a.jpg"
    assert apply_image_mirror(url, "mirror.example.com") == url
    assert apply_image_mirror("https://i.pximg.net/a.jpg", None) == "https://i.pximg.net/a.jpg"


def test_apply_image_mirror_accepts_scheme_and_strips_slashes():
    assert (
        apply_image_mirror("https://i.pximg.net/a.jpg", "https://mirror.example.com/")
        == "https://mirror.example.com/a.jpg"
    )


def test_apply_image_mirror_rejects_invalid_mirror():
    url = "https://i.pximg.net/a.jpg"
    assert apply_image_mirror(url, "bad mirror with spaces") == url


def test_storage_layout(tmp_path):
    storage = WorksStorage(tmp_path)
    assert storage.work_dir(123) == tmp_path / "123"
    assert storage.preview_path(123) == tmp_path / "123" / "preview.jpg"
    assert storage.thumb_path(123) == tmp_path / "123" / "thumb.webp"
    assert storage.original_dir(123) == tmp_path / "123" / "original"
    assert storage.meta_path(123) == tmp_path / "123" / "meta.json"
    assert storage.animation_path(123) == tmp_path / "123" / "animation.mp4"


def test_atomic_write_bytes(tmp_path):
    dest = tmp_path / "sub" / "file.bin"
    atomic_write_bytes(dest, b"payload")
    assert dest.read_bytes() == b"payload"
    assert not (tmp_path / "sub" / "file.bin.part").exists()


def test_storage_save_meta_json_and_preview(tmp_path):
    storage = WorksStorage(tmp_path)
    storage.save_meta_json(42, {"id": 42, "title": "t"})
    assert storage.meta_path(42).exists()
    assert storage.has_preview(42) is False
    storage.save_preview(42, b"jpegbytes")
    assert storage.has_preview(42) is True
    assert storage.preview_path(42).read_bytes() == b"jpegbytes"


def _image_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_downloader_fetch_to_file(tmp_path):
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, content=b"img-bytes")

    downloader = ImageDownloader(_image_client(handler), mirror=None, concurrency=2)
    dest = tmp_path / "x.jpg"
    assert await downloader.fetch_to_file("https://i.pximg.net/x.jpg", dest) is True
    assert dest.read_bytes() == b"img-bytes"
    assert seen_headers["referer"] == "https://www.pixiv.net/"


async def test_downloader_returns_false_on_404(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    downloader = ImageDownloader(_image_client(handler), mirror=None, concurrency=1)
    assert await downloader.fetch_to_file("https://i.pximg.net/gone.jpg", tmp_path / "g.jpg") is False
    assert calls["n"] == 1  # 404 must not be retried
    assert not (tmp_path / "g.jpg").exists()


async def test_downloader_retries_transient_errors(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, content=b"ok")

    downloader = ImageDownloader(_image_client(handler), mirror=None, concurrency=1)
    assert await downloader.fetch_to_file("https://i.pximg.net/r.jpg", tmp_path / "r.jpg") is True
    assert calls["n"] == 3


async def test_downloader_mirror_falls_back_to_official(tmp_path):
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.host == "mirror.example.com":
            return httpx.Response(403)
        return httpx.Response(200, content=b"official")

    downloader = ImageDownloader(
        _image_client(handler), mirror="mirror.example.com", concurrency=1
    )
    dest = tmp_path / "m.jpg"
    assert await downloader.fetch_to_file("https://i.pximg.net/m.jpg", dest) is True
    assert hosts == ["mirror.example.com", "i.pximg.net"]
    assert dest.read_bytes() == b"official"


async def test_downloader_prefers_mirror_when_it_works(tmp_path):
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(200, content=b"mirrored")

    downloader = ImageDownloader(
        _image_client(handler), mirror="mirror.example.com", concurrency=1
    )
    dest = tmp_path / "n.jpg"
    assert await downloader.fetch_to_file("https://i.pximg.net/n.jpg", dest) is True
    assert hosts == ["mirror.example.com"]
    assert dest.read_bytes() == b"mirrored"


async def test_downloader_fetch_bytes_returns_none_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    downloader = ImageDownloader(_image_client(handler), mirror=None, concurrency=1)
    assert await downloader.fetch_bytes("https://i.pximg.net/x.jpg") is None


async def test_downloader_does_not_leave_part_files(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    downloader = ImageDownloader(_image_client(handler), mirror=None, concurrency=1)
    await downloader.fetch_to_file("https://i.pximg.net/x.jpg", tmp_path / "x.jpg")
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_media.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.media'`

- [ ] **Step 3: 实现 storage.py 与 downloader.py**

`src/pixiv_archive/media/storage.py`：

```python
import json
import os
from pathlib import Path
from typing import Any


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes to ``path`` atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                os.remove(tmp)
            except OSError:
                pass


class WorksStorage:
    """Manages the on-disk layout of ``DATA_DIR/works/{pid}``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def work_dir(self, pid: int) -> Path:
        return self.root / str(pid)

    def preview_path(self, pid: int) -> Path:
        return self.work_dir(pid) / "preview.jpg"

    def thumb_path(self, pid: int) -> Path:
        return self.work_dir(pid) / "thumb.webp"

    def original_dir(self, pid: int) -> Path:
        return self.work_dir(pid) / "original"

    def meta_path(self, pid: int) -> Path:
        return self.work_dir(pid) / "meta.json"

    def animation_path(self, pid: int) -> Path:
        return self.work_dir(pid) / "animation.mp4"

    def has_preview(self, pid: int) -> bool:
        return self.preview_path(pid).exists()

    def save_preview(self, pid: int, data: bytes) -> None:
        atomic_write_bytes(self.preview_path(pid), data)

    def save_meta_json(self, pid: int, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        atomic_write_bytes(self.meta_path(pid), text.encode("utf-8"))
```

`src/pixiv_archive/media/downloader.py`：

```python
import asyncio
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from pixiv_archive.media.storage import atomic_write_bytes
from pixiv_archive.pixiv.auth import APP_HEADERS
from pixiv_archive.pixiv.errors import NetworkError, NotFoundError, PixivError
from pixiv_archive.pixiv.ratelimit import retry_async

PIXIV_IMAGE_HOSTS = frozenset({"i.pximg.net", "i-f.pximg.net", "s.pximg.net"})
_SCHEME_RE = re.compile(r"^https?://")
_REFERER = "https://www.pixiv.net/"


def _normalize_mirror(mirror: str | None) -> str | None:
    if not mirror:
        return None
    value = _SCHEME_RE.sub("", mirror.strip()).strip().rstrip("/")
    if not value or re.search(r"\s", value):
        return None
    return value


def apply_image_mirror(url: str, mirror: str | None) -> str:
    """Rewrite official pixiv image hosts to a configured mirror host."""
    normalized = _normalize_mirror(mirror)
    if not normalized or not url:
        return url
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    if (parsed.hostname or "").lower() not in PIXIV_IMAGE_HOSTS:
        return url
    suffix = f"?{parsed.query}" if parsed.query else ""
    return f"https://{normalized}{parsed.path}{suffix}"


class ImageDownloader:
    """Fetches image bytes with retry, mirror fallback and a concurrency cap."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        mirror: str | None = None,
        concurrency: int = 4,
        on_error: Callable[[str, str], None] | None = None,
    ) -> None:
        self._client = client
        self._mirror = _normalize_mirror(mirror)
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._on_error = on_error

    def _candidates(self, url: str) -> list[str]:
        mirrored = apply_image_mirror(url, self._mirror)
        if mirrored != url:
            return [mirrored, url]
        return [url]

    async def fetch_bytes(self, url: str) -> bytes | None:
        async with self._semaphore:
            for candidate in self._candidates(url):
                data = await self._fetch_once(candidate)
                if data is not None:
                    return data
            return None

    async def _fetch_once(self, url: str) -> bytes | None:
        async def _attempt() -> httpx.Response:
            try:
                return await self._client.get(
                    url, headers={"Referer": _REFERER, "User-Agent": APP_HEADERS["User-Agent"]}
                )
            except httpx.HTTPError as exc:
                raise NetworkError(str(exc)) from exc

        try:
            response = await retry_async(_attempt, attempts=3, base_delay=0.6)
        except NotFoundError:
            return None
        except NetworkError:
            return None
        except PixivError:
            return None
        if response.status_code in (403, 404):
            return None
        if response.status_code >= 300:
            return None
        return response.content

    async def fetch_to_file(self, url: str, dest: Path) -> bool:
        data = await self.fetch_bytes(url)
        if data is None:
            return False
        atomic_write_bytes(dest, data)
        return True
```

`src/pixiv_archive/media/__init__.py`：

```python
from pixiv_archive.media.downloader import ImageDownloader, apply_image_mirror
from pixiv_archive.media.storage import WorksStorage, atomic_write_bytes

__all__ = ["ImageDownloader", "WorksStorage", "apply_image_mirror", "atomic_write_bytes"]
```

> 说明：`_fetch_once` 中非 2xx 一律返回 `None`（不抛异常），由 `fetch_bytes` 尝试下一个候选 URL（镜像 → 官方）。因此 retry 只覆盖连接层与 5xx（由 `retry_async` 处理）。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_media.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/media tests/test_media.py
git commit -m "feat: add works storage layout and image downloader with mirror fallback"
```

---

### Task 6: 同步编排 — 增量模式

**Files:**
- Create: `tests/fakes.py`（共享测试替身，供本计划后续任务复用）
- Create: `src/pixiv_archive/sync/orchestrator.py`
- Test: `tests/test_sync_incremental.py`

- [ ] **Step 1: 写共享测试替身与失败的测试**

`tests/fakes.py`：

```python
"""Shared test doubles for sync tests.

Imported as ``from fakes import ...`` (pytest puts ``tests/`` on sys.path).
"""

from pixiv_archive.pixiv.models import BookmarkPage, Illust as PixivIllust, UgoiraMetadata


def make_illust(pid: int, *, type_: str = "illust", **overrides) -> PixivIllust:
    payload = {
        "id": pid,
        "title": f"t{pid}",
        "type": type_,
        "page_count": 1,
        "user": {"id": 1, "name": "artist", "account": "acct"},
        "tags": [{"name": "tag1", "translated_name": None}],
        "meta_single_page": {"original_image_url": f"https://i.pximg.net/{pid}.jpg"},
        "image_urls": {"square_medium": f"https://i.pximg.net/{pid}_sq.jpg"},
    }
    payload.update(overrides)
    return PixivIllust.model_validate(payload)


def page(illusts: list[PixivIllust], cursor: int | None) -> BookmarkPage:
    next_url = (
        f"https://app-api.pixiv.net/v1/user/bookmarks/illust?user_id=1&max_bookmark_id={cursor}"
        if cursor is not None
        else None
    )
    return BookmarkPage(illusts=illusts, next_url=next_url)


class FakeClient:
    """Replays predefined bookmark pages and records requests."""

    def __init__(self, pages: dict[str, list[BookmarkPage]]) -> None:
        self.pages = {key: list(value) for key, value in pages.items()}
        self.page_requests: list[tuple[str, int | None]] = []
        self.ugoira_calls: list[int] = []
        self.ugoira_error: Exception | None = None
        self.ugoira_frames: list[dict[str, object]] = []

    async def list_bookmarks(self, restrict: str, *, max_bookmark_id: int | None = None):
        self.page_requests.append((restrict, max_bookmark_id))
        queue = self.pages.get(restrict, [])
        if not queue:
            return BookmarkPage(illusts=[], next_url=None)
        return queue.pop(0)

    async def get_ugoira_metadata(self, illust_id: int) -> UgoiraMetadata:
        self.ugoira_calls.append(illust_id)
        if self.ugoira_error is not None:
            raise self.ugoira_error
        from pixiv_archive.pixiv.models import UgoiraFrame

        return UgoiraMetadata(
            zip_url=f"https://i.pximg.net/{illust_id}.zip",
            frames=[UgoiraFrame.model_validate(f) for f in self.ugoira_frames],
        )


class FakeDownloader:
    """Writes fake preview bytes; records requested urls."""

    def __init__(self, fail_urls: set[str] | None = None) -> None:
        self.urls: list[str] = []
        self.fail_urls = fail_urls or set()

    async def fetch_to_file(self, url: str, dest) -> bool:
        self.urls.append(url)
        if url in self.fail_urls:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"preview")
        return True

    async def fetch_bytes(self, url: str) -> bytes | None:
        self.urls.append(url)
        if url in self.fail_urls:
            return None
        return b"preview"
```

`tests/test_sync_incremental.py`：

```python
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from fakes import FakeClient, FakeDownloader, make_illust, page
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Illust, UgoiraMeta
from pixiv_archive.db.repo import bookmarks, sync_runs
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.pixiv.errors import NetworkError
from pixiv_archive.sync.orchestrator import MetadataSyncService


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


async def test_incremental_writes_readable_meta_json(db, tmp_path):
    client = FakeClient({"public": [page([make_illust(90)], cursor=None)], "private": []})
    await build_service(db, tmp_path, client, FakeDownloader()).run_incremental()
    payload = json.loads((WorksStorage(tmp_path / "works").meta_path(90)).read_text("utf-8"))
    assert payload["id"] == 90
    assert payload["title"] == "t90"
    assert payload["user"]["name"] == "artist"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_sync_incremental.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.sync.orchestrator'`

- [ ] **Step 3: 实现 orchestrator.py（增量部分 + 共用工具）**

`src/pixiv_archive/sync/orchestrator.py`：

```python
import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import utcnow
from pixiv_archive.db.repo import bookmarks, illusts, sync_runs
from pixiv_archive.media.downloader import ImageDownloader
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.pixiv.client import PixivClient
from pixiv_archive.pixiv.errors import PixivError
from pixiv_archive.pixiv.models import Illust as PixivIllust
from pixiv_archive.sync import rank as rank_mod

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, int, int, str], None]

RESTRICTS = ("public", "private")


@dataclass
class SyncResult:
    run_id: int
    kind: str
    status: str = "completed"
    pages_fetched: int = 0
    new_count: int = 0
    unbookmarked_count: int = 0
    rank_rebuilt_count: int = 0
    previews_fetched: int = 0
    previews_failed: int = 0
    ugoira_meta_fetched: int = 0
    failed_count: int = 0
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


class MetadataSyncService:
    """Implements stage A: bookmark metadata synchronisation."""

    def __init__(
        self,
        *,
        db: Database,
        client: PixivClient,
        storage: WorksStorage,
        downloader: ImageDownloader,
        download_previews: bool = True,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self._db = db
        self._client = client
        self._storage = storage
        self._downloader = downloader
        self._download_previews = download_previews
        self._on_progress = on_progress
        self._cancel = asyncio.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def set_download_previews(self, enabled: bool) -> None:
        """Override preview fetching for this run (used by the CLI flag)."""
        self._download_previews = enabled

    def _progress(self, phase: str, done: int, total: int, message: str) -> None:
        if self._on_progress is not None:
            self._on_progress(phase, done, total, message)

    async def run_incremental(self, *, max_pages: int | None = None) -> SyncResult:
        """Fetch the front of both bookmark lists and register new bookmarks."""
        self._cancel.clear()
        started = utcnow()
        async with self._db.session() as session:
            run_id = await sync_runs.create_run(session, "incremental", now=started)
            await session.commit()

        result = SyncResult(run_id=run_id, kind="incremental")
        try:
            async with self._db.session() as session:
                known_pids = await illusts.get_known_pids(session)
                states = await bookmarks.get_bookmark_states(session)
                min_rank = await bookmarks.get_min_rank(session)

            discovered: list[tuple[PixivIllust, str]] = []
            seen: set[int] = set()
            stop_public = False
            for restrict in RESTRICTS:
                cursor: int | None = None
                while not stop_public and not self._cancel.is_set():
                    page = await self._client.list_bookmarks(
                        restrict, max_bookmark_id=cursor
                    )
                    result.pages_fetched += 1
                    self._progress(
                        "fetch",
                        result.pages_fetched,
                        0,
                        f"读取{restrict}收藏第 {result.pages_fetched} 页",
                    )
                    if not page.illusts:
                        break
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
                        stop_public = True
                        break

            if self._cancel.is_set():
                result.status = "cancelled"
                await self._finish(result, started)
                return result

            ranks = rank_mod.incremental_ranks(min_rank, len(discovered))
            now = utcnow()
            preview_targets: list[PixivIllust] = []
            ugoira_targets: list[PixivIllust] = []

            async with self._db.session() as session:
                for (illust, restrict), rank_value in zip(discovered, ranks, strict=True):
                    try:
                        await illusts.upsert_illust(
                            session, illust, meta_json=self._meta_json(illust)
                        )
                        await bookmarks.set_active_rank(
                            session,
                            pid=illust.pid,
                            restrict=restrict,
                            rank=rank_value,
                            now=now,
                        )
                        result.new_count += 1
                        preview_targets.append(illust)
                        if illust.type == "ugoira":
                            ugoira_targets.append(illust)
                    except Exception as exc:  # noqa: BLE001 - keep the batch going
                        result.failed_count += 1
                        result.warnings.append(f"作品 {illust.pid} 元数据写入失败: {exc}")
                await session.commit()

            await self._finalize(result, preview_targets, ugoira_targets)
            result.status = "cancelled" if self._cancel.is_set() else "completed"
        except Exception as exc:  # noqa: BLE001 - persist failure then re-raise
            result.status = "failed"
            result.error = str(exc)
            await self._finish(result, started)
            raise
        await self._finish(result, started)
        return result

    async def run_full(self, *, max_pages: int | None = None) -> SyncResult:
        raise NotImplementedError  # implemented in the next task

    async def _finalize(
        self,
        result: SyncResult,
        works: list[PixivIllust],
        ugoira_works: list[PixivIllust],
    ) -> None:
        """Fetch previews and ugoira metadata, then write meta.json snapshots."""
        if self._download_previews:
            fetched, failed = await self._fetch_previews(works)
            result.previews_fetched += fetched
            result.previews_failed += failed
        ugoira_fetched, ugoira_failed = await self._fetch_ugoira_metadata(ugoira_works)
        result.ugoira_meta_fetched += ugoira_fetched
        result.failed_count += ugoira_failed
        for illust in works:
            try:
                self._storage.save_meta_json(illust.pid, illust.model_dump(mode="json"))
            except OSError as exc:
                result.warnings.append(f"作品 {illust.pid} meta.json 写入失败: {exc}")

    async def _fetch_previews(self, works: list[PixivIllust]) -> tuple[int, int]:
        targets: list[tuple[str, Path]] = []
        for illust in works:
            url = illust.preview_url
            if not url:
                continue
            dest = self._storage.preview_path(illust.pid)
            if dest.exists():
                continue
            targets.append((url, dest))
        if not targets:
            return 0, 0
        results = await asyncio.gather(
            *(self._downloader.fetch_to_file(url, dest) for url, dest in targets)
        )
        fetched = sum(1 for ok in results if ok)
        return fetched, len(results) - fetched

    async def _fetch_ugoira_metadata(self, works: list[PixivIllust]) -> tuple[int, int]:
        fetched = 0
        failed = 0
        for illust in works:
            try:
                meta = await self._client.get_ugoira_metadata(illust.pid)
            except PixivError:
                failed += 1
                continue
            frames_json = json.dumps(
                [frame.model_dump() for frame in meta.frames], ensure_ascii=False
            )
            async with self._db.session() as session:
                await illusts.upsert_ugoira_meta(
                    session,
                    pid=illust.pid,
                    zip_url=meta.zip_url or "",
                    frames_json=frames_json,
                    frame_count=len(meta.frames),
                )
                await session.commit()
            fetched += 1
        return fetched, failed

    def _meta_json(self, illust: PixivIllust) -> str:
        return json.dumps(illust.model_dump(mode="json"), ensure_ascii=False)

    async def _finish(self, result: SyncResult, started: datetime) -> None:
        async with self._db.session() as session:
            await sync_runs.finish_run(
                session,
                result.run_id,
                status=result.status,
                pages_fetched=result.pages_fetched,
                new_count=result.new_count,
                unbookmarked_count=result.unbookmarked_count,
                rank_rebuilt_count=result.rank_rebuilt_count,
                previews_fetched=result.previews_fetched,
                previews_failed=result.previews_failed,
                failed_count=result.failed_count,
                error=result.error,
                now=utcnow(),
            )
            await session.commit()
        logger.info(
            "sync run %s finished: status=%s new=%s pages=%s",
            result.run_id,
            result.status,
            result.new_count,
            result.pages_fetched,
        )
```

需要在文件顶部补两个导入（`Path` 与 `datetime`）：

```python
from datetime import datetime
from pathlib import Path
```

> 说明：`_finalize` 在事务提交后执行（网络 I/O 不占用数据库连接），失败不回滚已写入的元数据；预览图失败只计数，不影响同步状态。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_sync_incremental.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/sync/orchestrator.py tests/test_sync_incremental.py
git commit -m "feat: implement incremental metadata sync orchestration"
```

---

### Task 7: 同步编排 — 全量模式

**Files:**
- Modify: `src/pixiv_archive/sync/orchestrator.py`（替换 `run_full` 占位实现）
- Test: `tests/test_sync_full.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_sync_full.py`：

```python
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from fakes import FakeClient, FakeDownloader, make_illust, page
from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Illust
from pixiv_archive.db.repo import bookmarks
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.sync.orchestrator import MetadataSyncService


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "full.db")
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


async def test_full_sync_rebuilds_ranks_by_position(db, tmp_path):
    client = FakeClient(
        {
            "public": [
                page([make_illust(1), make_illust(2)], cursor=777),
                page([make_illust(3)], cursor=None),
            ],
            "private": [page([make_illust(4)], cursor=None)],
        }
    )
    result = await build_service(db, tmp_path, client, FakeDownloader()).run_full()
    assert result.status == "completed"
    assert result.new_count == 4
    assert result.pages_fetched == 3
    async with db.session() as session:
        pids = await bookmarks.ordered_pids(session)
        ranks = await bookmarks.get_rank_map(session)
    assert pids == [1, 2, 3, 4]
    assert ranks == {1: 0, 2: 1024, 3: 2048, 4: 3072}


async def test_full_sync_marks_missing_as_unbookmarked(db, tmp_path):
    setup = FakeClient(
        {
            "public": [page([make_illust(1), make_illust(2)], cursor=None)],
            "private": [],
        }
    )
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()

    shrunk = FakeClient({"public": [page([make_illust(2)], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, shrunk, FakeDownloader()).run_full()
    assert result.unbookmarked_count == 1
    async with db.session() as session:
        states = await bookmarks.get_bookmark_states(session)
        pids = await bookmarks.ordered_pids(session)
    assert states == {1: "unbookmarked", 2: "active"}
    assert pids == [2]


async def test_full_sync_refreshes_metadata(db, tmp_path):
    setup = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()

    refreshed = FakeClient(
        {
            "public": [page([make_illust(1, title="new title", total_bookmarks=999)], cursor=None)],
            "private": [],
        }
    )
    await build_service(db, tmp_path, refreshed, FakeDownloader()).run_full()
    async with db.session() as session:
        row = (await session.execute(select(Illust))).scalar_one()
    assert row.title == "new title"
    assert row.total_bookmarks == 999


async def test_full_sync_counts_rank_corrections(db, tmp_path):
    setup = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()
    async with db.session() as session:
        await bookmarks.set_active_rank(
            session, pid=1, restrict="public", rank=-99999, now=datetime.now(UTC)
        )
        await session.commit()
    again = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    result = await build_service(db, tmp_path, again, FakeDownloader()).run_full()
    assert result.rank_rebuilt_count == 1
    async with db.session() as session:
        assert await bookmarks.get_rank_map(session) == {1: 0}


async def test_full_sync_reactivates_and_repositions(db, tmp_path):
    setup = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()
    async with db.session() as session:
        await bookmarks.mark_unbookmarked(session, [1], now=datetime.now(UTC))
        await session.commit()

    again = FakeClient(
        {
            "public": [page([make_illust(2), make_illust(1)], cursor=None)],
            "private": [],
        }
    )
    await build_service(db, tmp_path, again, FakeDownloader()).run_full()
    async with db.session() as session:
        pids = await bookmarks.ordered_pids(session)
        states = await bookmarks.get_bookmark_states(session)
    assert pids == [2, 1]
    assert states == {1: "active", 2: "active"}


async def test_full_sync_backfills_missing_previews(db, tmp_path):
    setup = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    downloader = FakeDownloader()
    await build_service(db, tmp_path, setup, downloader).run_full()
    storage = WorksStorage(tmp_path / "works")
    storage.preview_path(1).unlink()

    again = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    downloader2 = FakeDownloader()
    await build_service(db, tmp_path, again, downloader2).run_full()
    assert downloader2.urls == ["https://i.pximg.net/1_sq.jpg"]
    assert storage.preview_path(1).exists()


async def test_full_sync_does_not_refetch_existing_previews(db, tmp_path):
    setup = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    await build_service(db, tmp_path, setup, FakeDownloader()).run_full()
    again = FakeClient({"public": [page([make_illust(1)], cursor=None)], "private": []})
    downloader = FakeDownloader()
    await build_service(db, tmp_path, again, downloader).run_full()
    assert downloader.urls == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_sync_full.py -v`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: 用真实实现替换 `run_full`**

把 `orchestrator.py` 中的

```python
    async def run_full(self, *, max_pages: int | None = None) -> SyncResult:
        raise NotImplementedError  # implemented in the next task
```

替换为：

```python
    async def run_full(self, *, max_pages: int | None = None) -> SyncResult:
        """Walk both bookmark lists completely, rebuilding ranks and states."""
        self._cancel.clear()
        started = utcnow()
        async with self._db.session() as session:
            run_id = await sync_runs.create_run(session, "full", now=started)
            await session.commit()

        result = SyncResult(run_id=run_id, kind="full")
        try:
            listed: list[tuple[PixivIllust, str, int]] = []
            position = 0
            truncated = False
            for restrict in RESTRICTS:
                cursor: int | None = None
                while not self._cancel.is_set():
                    page = await self._client.list_bookmarks(
                        restrict, max_bookmark_id=cursor
                    )
                    result.pages_fetched += 1
                    self._progress(
                        "fetch",
                        result.pages_fetched,
                        position,
                        f"读取{restrict}收藏第 {result.pages_fetched} 页",
                    )
                    if not page.illusts:
                        break
                    for illust in page.illusts:
                        listed.append((illust, restrict, position))
                        position += 1
                    if page.next_bookmark_id is None:
                        break
                    cursor = page.next_bookmark_id
                    if max_pages is not None and result.pages_fetched >= max_pages:
                        truncated = True
                        break
                if truncated:
                    break

            async with self._db.session() as session:
                known_pids = await illusts.get_known_pids(session)
                old_ranks = await bookmarks.get_rank_map(session)

            listed_pids = {illust.pid for illust, _, _ in listed}
            missing = sorted(pid for pid in known_pids if pid not in listed_pids)

            now = utcnow()
            preview_targets: list[PixivIllust] = []
            ugoira_targets: list[PixivIllust] = []

            async with self._db.session() as session:
                for illust, restrict, pos in listed:
                    try:
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

            await self._finalize(result, preview_targets, ugoira_targets)
            result.status = "cancelled" if self._cancel.is_set() else "completed"
        except Exception as exc:  # noqa: BLE001 - persist failure then re-raise
            result.status = "failed"
            result.error = str(exc)
            await self._finish(result, started)
            raise
        await self._finish(result, started)
        return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_sync_full.py tests/test_sync_incremental.py -v`
Expected: 19 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/sync/orchestrator.py tests/test_sync_full.py
git commit -m "feat: implement full metadata sync with rank rebuild and unbookmark detection"
```

---

### Task 8: 调度器

**Files:**
- Create: `src/pixiv_archive/sync/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_scheduler.py`：

```python
from datetime import timedelta

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from pixiv_archive.sync.scheduler import create_scheduler, parse_interval


def test_parse_interval_supported_units():
    assert parse_interval("30s") == timedelta(seconds=30)
    assert parse_interval("15m") == timedelta(minutes=15)
    assert parse_interval("6h") == timedelta(hours=6)
    assert parse_interval("1d") == timedelta(days=1)
    assert parse_interval(" 12H ") == timedelta(hours=12)


@pytest.mark.parametrize("value", ["", "6", "h", "6x", "-1h", "0h", "6 h"])
def test_parse_interval_rejects_invalid(value):
    with pytest.raises(ValueError):
        parse_interval(value)


def test_create_scheduler_registers_incremental_job():
    scheduler = create_scheduler(lambda: None, interval="6h")
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"sync-incremental"}
    assert isinstance(jobs["sync-incremental"].trigger, IntervalTrigger)
    assert jobs["sync-incremental"].max_instances == 1


def test_create_scheduler_registers_cron_job_when_configured():
    scheduler = create_scheduler(lambda: None, interval="6h", full_cron="0 3 * * 0")
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"sync-incremental", "sync-full"}
    assert isinstance(jobs["sync-full"].trigger, CronTrigger)


def test_create_scheduler_skips_cron_when_absent():
    scheduler = create_scheduler(lambda: None, interval="1h", full_cron=None)
    assert {job.id for job in scheduler.get_jobs()} == {"sync-incremental"}


def test_create_scheduler_returns_async_scheduler():
    scheduler = create_scheduler(lambda: None, interval="1h")
    assert isinstance(scheduler, AsyncIOScheduler)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.sync.scheduler'`

- [ ] **Step 3: 实现 scheduler.py**

`src/pixiv_archive/sync/scheduler.py`：

```python
import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

_INTERVAL_RE = re.compile(r"^(\d+)\s*([smhd])$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_interval(value: str) -> timedelta:
    """Parse "30m" / "6h" / "1d" style intervals."""
    match = _INTERVAL_RE.match((value or "").strip())
    if not match:
        raise ValueError(f"invalid interval {value!r}; expected e.g. '6h', '30m', '1d'")
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError(f"interval must be positive: {value!r}")
    return timedelta(seconds=amount * _UNIT_SECONDS[match.group(2).lower()])


def create_scheduler(
    incremental_job: Callable[[], Any],
    *,
    interval: str,
    full_cron: str | None = None,
    full_job: Callable[[], Any] | None = None,
) -> AsyncIOScheduler:
    """Build an AsyncIOScheduler with the incremental (and optional cron) sync jobs.

    Jobs are registered with ``max_instances=1`` so a slow sync run can never
    overlap with the next scheduled one.
    """
    scheduler = AsyncIOScheduler()
    delta = parse_interval(interval)
    scheduler.add_job(
        incremental_job,
        IntervalTrigger(seconds=delta.total_seconds()),
        id="sync-incremental",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    if full_cron:
        scheduler.add_job(
            full_job or incremental_job,
            CronTrigger.from_crontab(full_cron),
            id="sync-full",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
    return scheduler
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/sync/scheduler.py tests/test_scheduler.py
git commit -m "feat: add sync scheduler with interval parsing"
```

---

### Task 9: 服务工厂与 CLI

**Files:**
- Create: `src/pixiv_archive/sync/factory.py`
- Create: `src/pixiv_archive/cli.py`
- Modify: `src/pixiv_archive/__main__.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_cli.py`：

```python
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
    db = Database(settings.db_path)
    await db.create_all()
    await db.dispose()

    async with open_sync_service(settings) as service:
        assert service is not None
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
        pids = (
            await session.execute(select(Illust.pid).order_by(Illust.pid))
        ).scalars().all()
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
```

> 说明：`run_sync(argv, settings=None)` 接收含子命令的完整 argv；测试通过 monkeypatch 替换模块级 `open_sync_service` 注入假客户端。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.cli'`

- [ ] **Step 3: 实现 factory.py 与 cli.py，并更新 __main__.py**

`src/pixiv_archive/sync/factory.py`：

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from pixiv_archive.config import Settings
from pixiv_archive.db.engine import Database
from pixiv_archive.media.downloader import ImageDownloader
from pixiv_archive.media.storage import WorksStorage
from pixiv_archive.pixiv.client import PixivClient
from pixiv_archive.sync.orchestrator import MetadataSyncService


@asynccontextmanager
async def open_sync_service(settings: Settings) -> AsyncIterator[MetadataSyncService]:
    """Build a fully wired MetadataSyncService and clean everything up after use."""
    db = Database(settings.db_path)
    image_client = httpx.AsyncClient(proxy=settings.pixiv_proxy, timeout=30.0)
    captured: dict[str, str] = {}

    client = PixivClient(
        settings.pixiv_refresh_token,
        settings.pixiv_user_id,
        proxy=settings.pixiv_proxy,
        min_interval_ms=settings.api_min_interval_ms,
        on_refresh_token=lambda token: captured.__setitem__("refresh_token", token),
    )
    service = MetadataSyncService(
        db=db,
        client=client,
        storage=WorksStorage(settings.works_dir),
        downloader=ImageDownloader(
            image_client,
            mirror=settings.pixiv_image_mirror,
            concurrency=settings.image_concurrency,
        ),
        download_previews=settings.download_previews,
    )
    try:
        yield service
        if "refresh_token" in captured:
            await db.update_setting("pixiv_refresh_token", captured["refresh_token"])
    finally:
        await client.aclose()
        await image_client.aclose()
        await db.dispose()
```

`src/pixiv_archive/cli.py`：

```python
import argparse
import asyncio
import logging
import sys

from pixiv_archive.config import Settings
from pixiv_archive.sync.factory import open_sync_service
from pixiv_archive.sync.orchestrator import SyncResult


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pixiv_archive")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync = subparsers.add_parser("sync", help="run a metadata sync (stage A)")
    sync.add_argument(
        "--mode",
        choices=("incremental", "full"),
        default="incremental",
        help="incremental (default) or full bookmark walk",
    )
    sync.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="stop after N pages (debug/backfill testing)",
    )
    sync.add_argument(
        "--no-previews",
        action="store_true",
        help="skip preview image downloads for this run",
    )
    return parser


async def run_sync(argv: list[str], settings: Settings | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = settings or Settings()
    settings.ensure_dirs()

    async with open_sync_service(settings) as service:
        if args.no_previews:
            service.set_download_previews(False)
        if args.mode == "full":
            result = await service.run_full(max_pages=args.max_pages)
        else:
            result = await service.run_incremental(max_pages=args.max_pages)
    _report(result)
    return 0 if result.status == "completed" else 1


def _report(result: SyncResult) -> None:
    print(
        f"[{result.kind}] {result.status}: "
        f"新增 {result.new_count}，取消 {result.unbookmarked_count}，"
        f"rank 修正 {result.rank_rebuilt_count}，"
        f"页数 {result.pages_fetched}，"
        f"预览图 {result.previews_fetched}（失败 {result.previews_failed}），"
        f"ugoira {result.ugoira_meta_fetched}，"
        f"其它失败 {result.failed_count}"
    )
    for warning in result.warnings:
        print(f"  ! {warning}", file=sys.stderr)
    if result.error:
        print(f"  错误: {result.error}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        from pixiv_archive.web.app import create_app
        import uvicorn

        uvicorn.run(create_app(), host="0.0.0.0", port=8000)
        return 0
    if argv[0] != "sync":
        build_parser().error(f"unknown command: {argv[0]}")
    return asyncio.run(run_sync(argv))
```

`src/pixiv_archive/__main__.py`：

```python
import sys

from pixiv_archive.cli import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/sync/factory.py src/pixiv_archive/cli.py src/pixiv_archive/__main__.py tests/test_cli.py
git commit -m "feat: add sync service factory and sync CLI command"
```

---

### Task 10: 真实 API 集成验证

**Files:**
- Create: `tests/test_integration_sync.py`

- [ ] **Step 1: 写集成测试**

`tests/test_integration_sync.py`：

```python
"""Live stage A sync against the real pixiv API.

Run with:
    uv run pytest tests/test_integration_sync.py -m integration -v -s
Requires PIXIV_REFRESH_TOKEN / PIXIV_USER_ID and network access (PIXIV_PROXY).
"""

import pytest

from pixiv_archive.config import Settings
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
    print(f"\nnew={result.new_count} previews={result.previews_fetched} pages={result.pages_fetched}")

    from pixiv_archive.db.engine import Database

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
```

- [ ] **Step 2: 运行单元测试确认无回归**

Run: `uv run pytest -q`
Expected: 全部通过，集成测试被 deselect

- [ ] **Step 3: 运行真实 API 集成测试**

Run（PowerShell）:
```powershell
$env:PIXIV_REFRESH_TOKEN="qLy8MsZ9XdxMM65DiPxF3hn4b18i4J82AkqFAmn8dkY"
$env:PIXIV_USER_ID="56269851"
$env:PIXIV_PROXY="http://127.0.0.1:7897"
uv run pytest tests/test_integration_sync.py -m integration -v -s
```
Expected: 2 passed，第一条测试打印 `new=60 ...`；第二次增量 `new=0`、`pages_fetched=2`（证明「整页已知即停」生效）

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_sync.py
git commit -m "test: add live stage A sync integration tests"
```

---

### Task 11: 对真实账号执行完整同步并更新文档

**Files:**
- Modify: `README.md`（状态勾选 + 阶段 A 使用说明）

- [ ] **Step 1: 对真实账号跑一次全量同步（2047 条收藏）**

Run（PowerShell，独立 DATA_DIR 避免污染测试目录）:
```powershell
$env:PIXIV_REFRESH_TOKEN="qLy8MsZ9XdxMM65DiPxF3hn4b18i4J82AkqFAmn8dkY"
$env:PIXIV_USER_ID="56269851"
$env:PIXIV_PROXY="http://127.0.0.1:7897"
$env:DATA_DIR="D:\Projects\Pixiv-Collection-Archive\data"
uv run python -m pixiv_archive sync --mode full
```
Expected: 输出形如
```
[full] completed: 新增 2047，取消 0，rank 修正 0，页数 69，预览图 2047（失败 0），ugoira N，其它失败 0
```
（首次全量：`新增 2047`，`取消 0`；再次运行为 `新增 0，rank 修正 0`）

- [ ] **Step 2: 用 SQL 验证顺序与列表一致**

Run:
```powershell
uv run python -c "
import sqlite3
conn = sqlite3.connect(r'D:\Projects\Pixiv-Collection-Archive\data\archive.db')
rows = conn.execute('SELECT b.pid, b.rank FROM bookmark b WHERE b.state = \"active\" ORDER BY b.rank LIMIT 5').fetchall()
print('前 5 条（rank 升序）:', rows)
assert conn.execute('SELECT COUNT(*) FROM bookmark').fetchone()[0] == 2047
assert conn.execute('SELECT COUNT(*) FROM illust_page').fetchone()[0] > 2047
assert conn.execute('SELECT COUNT(*) FROM tag').fetchone()[0] > 100
print('OK: bookmark=2047, illust_page>2047, tag>100')
conn.close()
"
```
Expected: 打印前 5 条并把断言全部通过

- [ ] **Step 3: 再跑一次增量，确认幂等与停止条件**

Run:
```powershell
$env:DATA_DIR="D:\Projects\Pixiv-Collection-Archive\data"
uv run python -m pixiv_archive sync --mode incremental
```
Expected: `新增 0，页数 2`（public 首页全已知即停 + private 空列表）

- [ ] **Step 4: 更新 README**

把 `README.md` 的「状态」小节替换为：

```markdown
## 状态

- [x] 项目基础 + pixiv API 层
- [x] 阶段 A：元数据同步（增量 / 全量 + rank 顺序 + 预览图）
- [ ] 阶段 B：图片下载
- [ ] Web API 与前端
- [ ] 发布
```

并在「快速开始」中补充：

````markdown
### 阶段 A：同步收藏元数据

```bash
# 增量（默认；稳定态只请求前 1-2 页）
uv run python -m pixiv_archive sync --mode incremental

# 全量（首次同步、或需要重建顺序 / 检出取消收藏时）
uv run python -m pixiv_archive sync --mode full

# 调试：只翻 N 页、跳过预览图
uv run python -m pixiv_archive sync --max-pages 2 --no-previews
```

数据落盘结构：`$DATA_DIR/works/{pid}/meta.json`（元数据快照）、`preview.jpg`（列表预览图）。
````

- [ ] **Step 5: 运行全量检查并提交**

Run: `uv run ruff check src tests; uv run ruff format --check src tests; uv run mypy; uv run pytest -q`
Expected: 全部通过（若格式不符先运行 `uv run ruff format src tests`）

```bash
git add README.md
git commit -m "docs: mark stage A complete and document sync commands"
git push origin main
```

- [ ] **Step 6: 确认云端 CI 通过**

Run: `gh run list --limit 3` 然后 `gh run watch <最新 run id> --exit-status`
Expected: `backend`（含 lint/typecheck/tests）与 `docker` 两个 job 均成功

---

## 计划自审

**Spec 覆盖：**

| 设计章节 | 对应任务 |
| --- | --- |
| §4.2 rank 模型（全量重建 `position * spacing`；增量 `min - spacing * n`；显示序号由查询计算） | Task 2、6、7 |
| §4.4 增量：整页已知即停、不判取消、不设页数上限（仅调试用 `--max-pages`） | Task 6、9、10 |
| §4.4 全量：翻完、重建 rank、标记取消、刷新元数据、补预览图 | Task 7 |
| §4.4 ugoira 元数据在阶段 A 落库 | Task 6（`_fetch_ugoira_metadata`） |
| §4.6 取消后又重新收藏（`unbookmarked` → 恢复 active 并插到最前） | Task 6（增量发现规则）、Task 7（全量重排） |
| §4.6 预览图失败不阻塞 | Task 6、7（计数不回滚） |
| §5 存储布局（`works/{pid}/meta.json`、`preview.jpg`） | Task 5 |
| §6 表：tag / illust_tag / illust_page / ugoira_meta / sync_run | Task 1、3、4 |
| §7.3 镜像回退（i.pximg.net 域名替换，失败回退官方） | Task 5 |
| §11 配置：`SYNC_INTERVAL`、`SYNC_FULL_CRON`、`DOWNLOAD_PREVIEWS` | Task 8、9 |
| §12.4 测试：respx 之外用 Fake 客户端；真实 API 集成测试 | Task 6、7、10 |

**未覆盖（后续计划，符合拆分）：** 阶段 B 下载队列/原图/ugoira 转码（计划 3）、Web API + SSE + 前端（计划 4）、调度器接入 uvicorn 生命周期（计划 4，需要 Web 层先存在）。

**占位符扫描：** `run_full` 在 Task 6 以 `NotImplementedError` 明确占位，并在 Task 7 用完整实现替换（不是 TBD，是任务顺序）。其余步骤均含完整代码。

**类型一致性：**
- `SyncResult` 字段在 Task 6 定义，Task 7/9/10 使用一致（`ugoira_meta_fetched`、`rank_rebuilt_count`、`warnings`）✅
- `bookmarks.set_active_rank / touch_seen / mark_unbookmarked / get_min_rank / get_rank_map / ordered_pids / get_bookmark_states` 在 Task 4 定义，Task 6/7 使用一致 ✅
- `illusts.upsert_illust(session, illust, meta_json=...)`、`upsert_ugoira_meta(session, pid=..., zip_url=..., frames_json=..., frame_count=...)`、`get_known_pids` 在 Task 3 定义，Task 6/7 使用一致 ✅
- `WorksStorage.preview_path / meta_path / save_meta_json / save_preview / has_preview` 在 Task 5 定义，Task 6/7/10 使用一致 ✅
- `ImageDownloader.fetch_to_file(url, dest) -> bool` 在 Task 5 定义，Task 6 使用一致 ✅
- `open_sync_service(settings)` 在 Task 9 定义，Task 10 使用一致 ✅
- `tests/test_sync_incremental.py` 中的 `FakeClient / FakeDownloader / make_illust / page` 被 Task 7 与 Task 9 复用（同一批 helper，签名一致）✅

**已知风险与决策：**
- 增量模式对「已存在但本轮未出现」的作品不做任何处理（设计明确：增量不判取消）——由全量模式负责。
- `create_date` 写入 SQLite 时去掉 tzinfo（naive UTC），与 Plan 1 的 `DateTime()` 列一致；查询展示时按 UTC 解释。
- `_finalize` 的网络 I/O 不持有数据库事务，避免长时间占用 SQLite 写锁。
