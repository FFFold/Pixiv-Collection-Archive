# 计划 ①：画廊核心（筛选共享 / 批量选择 / 分页）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立共享筛选核心，使画廊、下载、导出共用同一套筛选定义；前端实现跨页批量选择、页级操作、增强分页与全部筛选条件 URL 化。

**Architecture:** 后端新增 `db/query.py`（`IllustFilters` + `build_illust_query` + `build_filtered_pids`），`gallery_query.py` 退化为排序/窗口索引包装，`download/scope.py` 的 `filter` 分支与 `export` 复用；前端新增 `useGalleryQueryState`（URL 状态）、`SelectionContext`（跨路由选择）、`GalleryFiltersContext`（供导出页读取），改造 Toolbar / Pagination / GalleryCard / IllustDetail。

**Tech Stack:** Python 3.12（SQLAlchemy 2.x async、FastAPI、pytest-asyncio）、React 19 + TS + TanStack Query + react-router 7 + Vitest。

**依赖关系：** 本计划是子项目 ② 的前置。所有命令在仓库根目录运行；前端命令在 `frontend/` 运行。`uv run` 使用仓库 `.venv`。

**约定：** 每个 Task 末尾提交一次。提交信息用 conventional commit 风格（仓库既有风格：`feat(web): ...`、`feat(db): ...`）。

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `src/pixiv_archive/db/query.py` | **新建**：`IllustFilters` + `build_illust_query` + `build_filtered_pids`（共享筛选核心） |
| `src/pixiv_archive/web/gallery_query.py` | 改造：删除 `GalleryFilters`，`query_gallery` 接收 `IllustFilters`，保留显示序号窗口 |
| `src/pixiv_archive/web/routers/gallery.py` | 改造：查询参数扩展（多标签/多作者/区间），`limit` 上限 500 |
| `src/pixiv_archive/download/scope.py` | 改造：`DownloadScope` 扩展筛选字段，`filter` 分支复用共享核心 |
| `src/pixiv_archive/web/schemas.py` | 改造：`DownloadRequest` 增加筛选字段 |
| `src/pixiv_archive/web/routers/tasks.py` | 改造：把 `DownloadRequest` 筛选字段映射进 `DownloadScope` |
| `frontend/src/api/types.ts` | 改造：`GalleryQuery` 扩展（数组与区间字段） |
| `frontend/src/api/queries.ts` | 改造：`buildGalleryUrl` 支持重复参数 |
| `frontend/src/hooks/useGalleryQueryState.ts` | **新建**：URL ↔ `GalleryQuery` 双向映射 |
| `frontend/src/contexts/SelectionContext.tsx` | **新建**：跨路由选择状态 |
| `frontend/src/contexts/GalleryFiltersContext.tsx` | **新建**：最近生效的筛选（供导出页） |
| `frontend/src/components/Toolbar.tsx` | 改造：页级选择按钮 + 页数/标签/作者/收藏数/浏览数筛选控件 |
| `frontend/src/components/Pagination.tsx` | 改造：页大小、跳页、首末页、键盘 |
| `frontend/src/components/GalleryCard.tsx` | 改造：缩略图错误回退 |
| `frontend/src/pages/Gallery.tsx` | 改造：使用 URL 状态 + SelectionContext |
| `frontend/src/pages/IllustDetail.tsx` | 改造：加入/移出选择；作者链接参数修正 |
| `frontend/src/App.tsx` / `main.tsx` | 改造：包 SelectionProvider / GalleryFiltersProvider |
| `tests/test_db_query.py` | **新建**：共享筛选核心单测 |
| `tests/test_web_gallery_query.py` | 改造：导入改 `IllustFilters`；新增新字段用例 |
| `tests/test_download_scope.py` | 改造：新增 filter 字段用例 |
| `tests/test_web_routers_gallery.py` | 改造：新增查询参数用例 |
| `frontend/src/hooks/useGalleryQueryState.test.tsx` | **新建** |
| `frontend/src/contexts/SelectionContext.test.tsx` | **新建** |
| `frontend/src/components/Pagination.test.tsx` | 改造：新增用例 |
| `frontend/src/components/Toolbar.test.tsx` | 改造：新增用例 |

---

### Task 1: 共享筛选核心 `db/query.py`

**Files:**
- Create: `src/pixiv_archive/db/query.py`
- Test: `tests/test_db_query.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_db_query.py
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust, IllustTag, Tag
from pixiv_archive.db.query import IllustFilters, build_filtered_pids, build_illust_query


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "q.db")
    await database.create_all()
    yield database
    await database.dispose()


async def _seed(
    db,
    pid: int,
    *,
    rank: int,
    author: int = 1,
    type_: str = "illust",
    x: int = 0,
    state: str = "active",
    bm_state: str = "active",
    restrict: str = "public",
    pages: int = 1,
    bookmarks: int = 0,
    views: int = 0,
    tags: tuple[str, ...] = (),
) -> None:
    async with db.session() as session:
        if await session.get(Author, author) is None:
            session.add(Author(id=author, name=f"author{author}", account=f"acct{author}"))
        session.add(
            Illust(
                pid=pid,
                title=f"作品 {pid}",
                author_id=author,
                type=type_,
                x_restrict=x,
                state=state,
                page_count=pages,
                total_bookmarks=bookmarks,
                total_view=views,
                create_date=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()
    async with db.session() as session:
        session.add(
            Bookmark(pid=pid, restrict=restrict, rank=rank, state=bm_state)
        )
        for name in tags:
            tag_id = (
                await session.execute(select(Tag.id).where(Tag.name == name))
            ).scalar_one_or_none()
            if tag_id is None:
                tag = Tag(name=name)
                session.add(tag)
                await session.flush()
                tag_id = tag.id
            session.add(IllustTag(pid=pid, tag_id=tag_id, position=0))
        await session.commit()


async def test_default_returns_active_bookmarked(db):
    await _seed(db, 1, rank=0)
    await _seed(db, 2, rank=10, bm_state="unbookmarked")
    await _seed(db, 3, rank=20, state="deleted")
    async with db.session() as session:
        rows = (await session.execute(build_filtered_pids(IllustFilters()))).scalars().all()
    assert rows == [1]


async def test_multi_tag_is_and(db):
    await _seed(db, 1, rank=0, tags=("cat", "cute"))
    await _seed(db, 2, rank=10, tags=("cat",))
    await _seed(db, 3, rank=20, tags=("cute",))
    async with db.session() as session:
        both = (
            await session.execute(build_filtered_pids(IllustFilters(tags=["cat", "cute"])))
        ).scalars().all()
        one = (await session.execute(build_filtered_pids(IllustFilters(tags=["cat"])))).scalars().all()
    assert both == [1]
    assert one == [1, 2]


async def test_multi_author_is_in(db):
    await _seed(db, 1, rank=0, author=5)
    await _seed(db, 2, rank=10, author=6)
    await _seed(db, 3, rank=20, author=7)
    async with db.session() as session:
        rows = (
            await session.execute(build_filtered_pids(IllustFilters(author_ids=[5, 7])))
        ).scalars().all()
    assert rows == [1, 3]


async def test_page_count_range(db):
    await _seed(db, 1, rank=0, pages=1)
    await _seed(db, 2, rank=10, pages=3)
    await _seed(db, 3, rank=20, pages=10)
    async with db.session() as session:
        mid = (
            await session.execute(build_filtered_pids(IllustFilters(page_min=2, page_max=5)))
        ).scalars().all()
        at_least = (
            await session.execute(build_filtered_pids(IllustFilters(page_min=3)))
        ).scalars().all()
    assert mid == [2]
    assert at_least == [2, 3]


async def test_bookmarks_and_views_range(db):
    await _seed(db, 1, rank=0, bookmarks=5, views=100)
    await _seed(db, 2, rank=10, bookmarks=50, views=1000)
    async with db.session() as session:
        hot = (
            await session.execute(build_filtered_pids(IllustFilters(bookmarks_min=10)))
        ).scalars().all()
        niche = (
            await session.execute(build_filtered_pids(IllustFilters(views_max=500)))
        ).scalars().all()
    assert hot == [2]
    assert niche == [1]


async def test_restrict_and_downloaded_filters(db):
    await _seed(db, 1, rank=0, restrict="private")
    await _seed(db, 2, rank=10, restrict="public")
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update().where(Illust.pid == 2).values(has_original=True)
        )
        await session.commit()
    async with db.session() as session:
        private = (
            await session.execute(build_filtered_pids(IllustFilters(restrict="private")))
        ).scalars().all()
        done = (
            await session.execute(build_filtered_pids(IllustFilters(downloaded=True)))
        ).scalars().all()
    assert private == [1]
    assert done == [2]


async def test_build_illust_query_returns_full_rows(db):
    await _seed(db, 1, rank=0)
    async with db.session() as session:
        stmt = build_illust_query(IllustFilters())
        rows = (await session.execute(stmt)).all()
    assert len(rows) == 1
    illust, bookmark, author = rows[0]
    assert illust.pid == 1
    assert bookmark.rank == 0
    assert author.name == "author1"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_db_query.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'pixiv_archive.db.query'`）

- [ ] **Step 3: 实现 `db/query.py`**

```python
"""Shared illust filtering used by gallery, downloads and export."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, and_, exists, or_, select

from pixiv_archive.db.models import Author, Bookmark, Illust, IllustTag, Tag


@dataclass
class IllustFilters:
    """All supported illust filters; empty means the default active set."""

    sort: str = "rank"
    tags: list[str] = field(default_factory=list)
    author_ids: list[int] = field(default_factory=list)
    q: str | None = None
    type: str | None = None
    x_restrict: int | None = None
    downloaded: bool | None = None
    restrict: str | None = None
    only_unbookmarked: bool = False
    include_unbookmarked: bool = False
    only_deleted: bool = False
    include_deleted: bool = False
    page_min: int | None = None
    page_max: int | None = None
    bookmarks_min: int | None = None
    bookmarks_max: int | None = None
    views_min: int | None = None
    views_max: int | None = None
    rank_start: int | None = None
    rank_count: int | None = None


SORTS: dict[str, tuple[Any, ...]] = {
    "rank": (Bookmark.rank.asc(),),
    "create_date": (Illust.create_date.desc(), Bookmark.rank.asc()),
    "bookmarks": (Illust.total_bookmarks.desc(), Bookmark.rank.asc()),
    "views": (Illust.total_view.desc(), Bookmark.rank.asc()),
}


def sort_order(filters: IllustFilters) -> tuple[Any, ...]:
    return SORTS.get(filters.sort, SORTS["rank"])


def _base_conditions(filters: IllustFilters) -> list[Any]:
    if filters.only_deleted:
        conditions: list[Any] = [Illust.state == "deleted"]
    elif filters.include_deleted:
        conditions = []
    else:
        conditions = [Illust.state == "active"]
    if filters.only_unbookmarked:
        conditions.append(Bookmark.state == "unbookmarked")
    elif not filters.include_unbookmarked:
        conditions.append(Bookmark.state == "active")
    if filters.author_ids:
        conditions.append(Illust.author_id.in_(filters.author_ids))
    if filters.type:
        conditions.append(Illust.type == filters.type)
    if filters.x_restrict is not None:
        conditions.append(Illust.x_restrict == filters.x_restrict)
    if filters.downloaded is True:
        conditions.append(Illust.has_original.is_(True))
    elif filters.downloaded is False:
        conditions.append(Illust.has_original.is_(False))
    if filters.restrict:
        conditions.append(Bookmark.restrict == filters.restrict)
    if filters.q:
        pattern = f"%{filters.q}%"
        conditions.append(or_(Illust.title.like(pattern), Author.name.like(pattern)))
    if filters.page_min is not None:
        conditions.append(Illust.page_count >= filters.page_min)
    if filters.page_max is not None:
        conditions.append(Illust.page_count <= filters.page_max)
    if filters.bookmarks_min is not None:
        conditions.append(Illust.total_bookmarks >= filters.bookmarks_min)
    if filters.bookmarks_max is not None:
        conditions.append(Illust.total_bookmarks <= filters.bookmarks_max)
    if filters.views_min is not None:
        conditions.append(Illust.total_view >= filters.views_min)
    if filters.views_max is not None:
        conditions.append(Illust.total_view <= filters.views_max)
    return conditions


def build_illust_query(filters: IllustFilters) -> Select[Any]:
    """Base query (Illust, Bookmark, Author) with every filter applied."""
    return _apply_filters(select(Illust, Bookmark, Author), filters)


def build_filtered_pids(filters: IllustFilters) -> Select[Any]:
    """Pid-only projection ordered by the requested sort."""
    return _apply_filters(select(Illust.pid), filters).order_by(*sort_order(filters))


def _apply_filters(stmt: Select[Any], filters: IllustFilters) -> Select[Any]:
    """Attach joins, conditions, tag EXISTS and the rank window to ``stmt``.

    Shared by the row query and the pid query so both stay in sync.
    """
    stmt = (
        stmt.join(Bookmark, Bookmark.pid == Illust.pid)
        .join(Author, Author.id == Illust.author_id)
        .where(and_(*_base_conditions(filters)))
    )
    for tag_name in filters.tags:
        stmt = stmt.where(
            exists(
                select(IllustTag.pid)
                .join(Tag, Tag.id == IllustTag.tag_id)
                .where(IllustTag.pid == Illust.pid, Tag.name == tag_name)
            )
        )
    if filters.rank_start is not None or filters.rank_count is not None:
        window = (
            select(Bookmark.pid)
            .where(Bookmark.state == "active")
            .order_by(Bookmark.rank)
            .offset(filters.rank_start or 0)
        )
        if filters.rank_count is not None:
            window = window.limit(filters.rank_count)
        stmt = stmt.where(Illust.pid.in_(window))
    return stmt
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_db_query.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/db/query.py tests/test_db_query.py
git commit -m "feat(db): add shared illust filter query module"
```

---

### Task 2: 迁移 `gallery_query.py` 到共享核心

**Files:**
- Modify: `src/pixiv_archive/web/gallery_query.py`（全部内容替换）
- Modify: `src/pixiv_archive/web/routers/gallery.py:1-52`
- Modify: `tests/test_web_gallery_query.py:1-189`（导入与类名替换，不改变断言）

- [ ] **Step 1: 改写实现（先实现，再跑现有测试验证无回归）**

`gallery_query.py` 替换为：

```python
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.query import IllustFilters, build_illust_query, sort_order
from pixiv_archive.web.schemas import GalleryItem, GalleryResponse


async def query_gallery(
    session: AsyncSession, filters: IllustFilters, *, offset: int, limit: int
) -> GalleryResponse:
    """Run the filtered/sorted query and compute absolute display indexes.

    Display indexes are 1-based positions within the *whole* filtered set, so
    they stay stable while paginating. A window function computes them in the
    database, avoiding a second full scan.
    """
    base = build_illust_query(filters)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    order = sort_order(filters)
    indexed = base.order_by(*order).add_columns(
        func.row_number().over(order_by=order).label("display_index")
    )
    rows = (await session.execute(indexed.offset(offset).limit(limit))).all()

    items = [
        GalleryItem(
            pid=illust.pid,
            index=int(display_index),
            title=illust.title,
            author_id=author.id,
            author_name=author.name,
            page_count=illust.page_count,
            type=illust.type,
            x_restrict=illust.x_restrict,
            width=illust.width,
            height=illust.height,
            create_date=illust.create_date,
            rank=bookmark.rank,
            has_original=illust.has_original,
            page_downloaded_count=illust.page_downloaded_count,
            preview_url=f"/api/illust/{illust.pid}/thumb",
            thumb_url=f"/api/illust/{illust.pid}/thumb",
            restrict=bookmark.restrict,
            unbookmarked=bookmark.state == "unbookmarked",
            state=illust.state,
        )
        for illust, bookmark, author, display_index in rows
    ]
    return GalleryResponse(items=items, total=total, offset=offset, limit=limit)
```

`routers/gallery.py` 替换为：

```python
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.query import IllustFilters
from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_session
from pixiv_archive.web.gallery_query import query_gallery
from pixiv_archive.web.schemas import GalleryResponse

router = APIRouter(
    prefix="/api",
    tags=["gallery"],
    dependencies=[Depends(require_auth)],  # noqa: B008
)


@router.get("/gallery", response_model=GalleryResponse)
async def gallery(
    session: Annotated[AsyncSession, Depends(get_session)],  # noqa: B008
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 60,
    sort: Annotated[str, Query(pattern="^(rank|create_date|bookmarks|views)$")] = "rank",
    author_id: Annotated[list[int] | None, Query()] = None,
    tag: Annotated[list[str] | None, Query()] = None,
    q: str | None = None,
    type: Annotated[str | None, Query(pattern="^(illust|ugoira)$")] = None,
    x_restrict: Annotated[int | None, Query(ge=0, le=2)] = None,
    downloaded: bool | None = None,
    restrict: Annotated[str | None, Query(pattern="^(public|private)$")] = None,
    only_unbookmarked: bool = False,
    include_unbookmarked: bool = False,
    only_deleted: bool = False,
    include_deleted: bool = False,
    page_min: Annotated[int | None, Query(ge=1)] = None,
    page_max: Annotated[int | None, Query(ge=1)] = None,
    bookmarks_min: Annotated[int | None, Query(ge=0)] = None,
    bookmarks_max: Annotated[int | None, Query(ge=0)] = None,
    views_min: Annotated[int | None, Query(ge=0)] = None,
    views_max: Annotated[int | None, Query(ge=0)] = None,
    rank_start: Annotated[int | None, Query(ge=0)] = None,
    rank_count: Annotated[int | None, Query(ge=1)] = None,
) -> GalleryResponse:
    filters = IllustFilters(
        sort=sort,
        tags=tag or [],
        author_ids=author_id or [],
        q=q,
        type=type,
        x_restrict=x_restrict,
        downloaded=downloaded,
        restrict=restrict,
        only_unbookmarked=only_unbookmarked,
        include_unbookmarked=include_unbookmarked,
        only_deleted=only_deleted,
        include_deleted=include_deleted,
        page_min=page_min,
        page_max=page_max,
        bookmarks_min=bookmarks_min,
        bookmarks_max=bookmarks_max,
        views_min=views_min,
        views_max=views_max,
        rank_start=rank_start,
        rank_count=rank_count,
    )
    return await query_gallery(session, filters, offset=offset, limit=limit)
```

- [ ] **Step 2: 更新现有测试的导入与类名**

在 `tests/test_web_gallery_query.py` 中：

- 第 7 行改为：`from pixiv_archive.db.query import IllustFilters`（移除 `GalleryFilters` 导入），保留 `from pixiv_archive.web.gallery_query import query_gallery`
- 全文把 `GalleryFilters(` 替换为 `IllustFilters(`

- [ ] **Step 3: 运行测试确认通过**

Run: `uv run pytest tests/test_web_gallery_query.py tests/test_web_routers_gallery.py -q`
Expected: 全部通过（行为与旧版一致）

- [ ] **Step 4: 运行 mypy 与 ruff**

Run: `uv run ruff check src tests && uv run mypy`
Expected: 无错误

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/web/gallery_query.py src/pixiv_archive/web/routers/gallery.py tests/test_web_gallery_query.py
git commit -m "refactor(web): use shared illust filters in gallery query"
```

---

### Task 3: 新增路由参数测试（多标签 / 多作者 / 区间 / limit 上限）+ 空 tag 兼容修复

**Files:**
- Test: `tests/test_web_routers_gallery.py`（追加用例）
- Modify: `src/pixiv_archive/web/routers/gallery.py`（空 tag 归一化）

- [ ] **Step 1: 追加失败测试**

在 `tests/test_web_routers_gallery.py` 末尾追加：

```python
async def test_gallery_multi_tag_and_author_filters(client):
    _login(client)
    database = client._transport.app.state.db  # type: ignore[union-attr]
    from pixiv_archive.db.models import IllustTag, Tag

    async with database.session() as session:
        cat = Tag(name="cat")
        cute = Tag(name="cute")
        session.add(cat)
        session.add(cute)
        await session.flush()
        session.add(IllustTag(pid=10, tag_id=cat.id, position=0))
        session.add(IllustTag(pid=10, tag_id=cute.id, position=1))
        session.add(IllustTag(pid=20, tag_id=cat.id, position=0))
        await session.commit()

    both = await client.get("/api/gallery", params=[("tag", "cat"), ("tag", "cute")])
    assert [item["pid"] for item in both.json()["items"]] == [10]

    same_author = await client.get("/api/gallery", params=[("author_id", 1)])
    assert same_author.json()["total"] == 2

    other_author = await client.get("/api/gallery", params=[("author_id", 99)])
    assert other_author.json()["total"] == 0


async def test_gallery_range_filters(client):
    _login(client)
    pages = await client.get("/api/gallery", params={"page_min": 2})
    assert [item["pid"] for item in pages.json()["items"]] == [10]

    pages_none = await client.get("/api/gallery", params={"page_min": 5})
    assert pages_none.json()["total"] == 0

    books = await client.get("/api/gallery", params={"bookmarks_min": 1})
    assert books.json()["total"] == 0

    views = await client.get("/api/gallery", params={"views_max": 0})
    assert views.json()["total"] == 2


async def test_gallery_empty_tag_is_ignored(client):
    """`?tag=` must behave like no tag filter (pre-refactor behavior)."""
    _login(client)
    response = await client.get("/api/gallery", params={"tag": ""})
    assert response.status_code == 200
    assert response.json()["total"] == 2


async def test_gallery_limit_accepts_240(client):
    _login(client)
    response = await client.get("/api/gallery", params={"limit": 240})
    assert response.status_code == 200
    assert response.json()["limit"] == 240

    too_large = await client.get("/api/gallery", params={"limit": 501})
    assert too_large.status_code == 422
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_routers_gallery.py -q`
Expected: `test_gallery_empty_tag_is_ignored` FAIL（`?tag=` 目前作为空字符串标签匹配，返回 0 条）；其余新用例应已由 Task 2 实现并直接通过。

- [ ] **Step 3: 修复空 tag 归一化**

`src/pixiv_archive/web/routers/gallery.py` 中：

- import 行 `from pixiv_archive.db.query import IllustFilters` 不变
- 在 `filters = IllustFilters(` 之前增加：

```python
    cleaned_tags = [name for name in (tag or []) if name]
    filters = IllustFilters(
        sort=sort,
        tags=cleaned_tags,
        ...
```

（即把 `tags=tag or []` 改为 `tags=cleaned_tags`；`author_id` 保持 `author_id or []`，因为 int 参数的空串会被 FastAPI 直接拒绝为 422，不存在同类问题。）

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_routers_gallery.py -q`
Expected: 全部通过

- [ ] **Step 5: 全量校验**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy && uv run pytest -q`
Expected: 全部通过

- [ ] **Step 6: Commit**

```bash
git add tests/test_web_routers_gallery.py src/pixiv_archive/web/routers/gallery.py
git commit -m "test(web): cover multi-tag, multi-author and range gallery filters"
```

---

### Task 4: 下载 scope 复用共享筛选核心

**Files:**
- Modify: `src/pixiv_archive/download/scope.py:1-131`
- Modify: `src/pixiv_archive/web/schemas.py:101-109`
- Modify: `src/pixiv_archive/web/routers/tasks.py:31-43`
- Test: `tests/test_download_scope.py`（追加用例）

- [ ] **Step 1: 追加失败测试**

在 `tests/test_download_scope.py` 末尾追加：

```python
async def test_scope_filter_honours_page_and_tag_filters(db):
    await _seed_illust(db, 10, rank=0, page_count=1)
    await _seed_illust(db, 20, rank=10, page_count=6)
    async with db.session() as session:
        from pixiv_archive.db.models import IllustTag, Tag

        tag = Tag(name="cat")
        session.add(tag)
        await session.flush()
        session.add(IllustTag(pid=20, tag_id=tag.id, position=0))
        await session.commit()
    async with db.session() as session:
        by_pages = await resolve_scope(
            session, DownloadScope(kind="filter", page_min=2, page_max=10)
        )
        by_tag = await resolve_scope(session, DownloadScope(kind="filter", tags=["cat"]))
    assert by_pages.pids == [20]
    assert by_tag.pids == [20]


async def test_scope_filter_honours_views_and_bookmarks_range(db):
    await _seed_illust(db, 1, rank=0)
    await _seed_illust(db, 2, rank=10)
    async with db.session() as session:
        await session.execute(
            Illust.__table__.update().where(Illust.pid == 1).values(total_view=5, total_bookmarks=1)
        )
        await session.execute(
            Illust.__table__.update().where(Illust.pid == 2).values(
                total_view=5000, total_bookmarks=900
            )
        )
        await session.commit()
    async with db.session() as session:
        popular = await resolve_scope(
            session, DownloadScope(kind="filter", bookmarks_min=500)
        )
        rare = await resolve_scope(session, DownloadScope(kind="filter", views_max=100))
    assert popular.pids == [2]
    assert rare.pids == [1]


async def test_scope_filter_honours_restrict_and_unbookmarked(db):
    """Unbookmarked works are excluded from the default filter set.

    ``only_unbookmarked`` + ``include_unbookmarked`` switches the bookmark
    condition to ``unbookmarked``; unrelated works must disappear.
    """
    await _seed_illust(db, 1, rank=0, state="unbookmarked")
    await _seed_illust(db, 2, rank=10, state="active")
    async with db.session() as session:
        await session.execute(
            Bookmark.__table__.update().where(Bookmark.pid == 1).values(restrict="private")
        )
        await session.commit()
    async with db.session() as session:
        private = await resolve_scope(session, DownloadScope(kind="filter", restrict="private"))
        unbookmarked = await resolve_scope(
            session,
            DownloadScope(kind="filter", only_unbookmarked=True, include_unbookmarked=True),
        )
        default = await resolve_scope(session, DownloadScope(kind="filter", type="illust"))
    assert private.pids == [1]
    assert unbookmarked.pids == [1]
    assert default.pids == [2]
```

注意：`tests/test_download_scope.py` 顶部需要新增 `Bookmark` 导入：

```python
from pixiv_archive.db.models import Author, Bookmark, Illust, IllustPage, UgoiraMeta
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_download_scope.py -q`
Expected: 新用例 FAIL（`DownloadScope` 尚无 `page_min`/`tags` 等字段）

- [ ] **Step 3: 扩展 `DownloadScope` 并复用共享核心**

`download/scope.py` 改造后（完整替换）：

```python
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Bookmark, Illust, IllustPage, UgoiraMeta
from pixiv_archive.db.query import IllustFilters, build_filtered_pids


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
    # filter-scope extras (shared with the gallery filters)
    tags: list[str] = field(default_factory=list)
    author_ids: list[int] = field(default_factory=list)
    q: str | None = None
    restrict: str | None = None
    downloaded: bool | None = None
    page_min: int | None = None
    page_max: int | None = None
    bookmarks_min: int | None = None
    bookmarks_max: int | None = None
    views_min: int | None = None
    views_max: int | None = None
    only_unbookmarked: bool = False
    include_unbookmarked: bool = False


@dataclass
class ScopePlan:
    pids: list[int]
    jobs: list[tuple[int, str, str]]


def empty_scope_matches_nothing(scope: DownloadScope) -> bool:
    """A plain filter scope with no criteria would select the whole library."""
    if scope.kind != "filter":
        return False
    return (
        all(
            value is None
            for value in (
                scope.author_id,
                scope.start,
                scope.count,
                scope.x_restrict,
                scope.type,
                scope.q,
                scope.restrict,
                scope.downloaded,
                scope.page_min,
                scope.page_max,
                scope.bookmarks_min,
                scope.bookmarks_max,
                scope.views_min,
                scope.views_max,
            )
        )
        and not scope.pids
        and not scope.tags
        and not scope.author_ids
        and not scope.only_unbookmarked
        and not scope.include_unbookmarked
    )


def _filters_from_filter_scope(scope: DownloadScope) -> IllustFilters:
    author_ids = list(scope.author_ids)
    if scope.author_id is not None and scope.author_id not in author_ids:
        author_ids.append(scope.author_id)
    return IllustFilters(
        tags=scope.tags,
        author_ids=author_ids,
        q=scope.q,
        type=scope.type,
        x_restrict=scope.x_restrict,
        downloaded=scope.downloaded,
        restrict=scope.restrict,
        page_min=scope.page_min,
        page_max=scope.page_max,
        bookmarks_min=scope.bookmarks_min,
        bookmarks_max=scope.bookmarks_max,
        views_min=scope.views_min,
        views_max=scope.views_max,
        only_unbookmarked=scope.only_unbookmarked,
        include_unbookmarked=scope.include_unbookmarked,
    )


def build_illust_filter(scope: DownloadScope) -> Select[tuple[int]]:
    """Build the pid SELECT over active, bookmarked illusts matching the scope."""
    if scope.kind == "selected":
        if not scope.pids:
            return build_filtered_pids(IllustFilters()).where(sa.false())
        return build_filtered_pids(IllustFilters()).where(Illust.pid.in_(scope.pids))
    if scope.kind == "author":
        if scope.author_id is None:
            return build_filtered_pids(IllustFilters()).where(sa.false())
        return build_filtered_pids(IllustFilters(author_ids=[scope.author_id]))
    if scope.kind == "rank_range":
        ordered = build_filtered_pids(IllustFilters())
        if scope.start is not None or scope.count is not None:
            start = scope.start or 0
            ordered = ordered.offset(start)
            if scope.count is not None and scope.count >= 0:
                ordered = ordered.limit(scope.count)
        return ordered
    if scope.kind == "filter":
        if empty_scope_matches_nothing(scope):
            return build_filtered_pids(IllustFilters()).where(sa.false())
        stmt = build_filtered_pids(_filters_from_filter_scope(scope))
        if scope.pids:
            stmt = stmt.where(Illust.pid.in_(scope.pids))
        return stmt
    # all_missing: every active, bookmarked illust
    return build_filtered_pids(IllustFilters())


async def resolve_scope(session: AsyncSession, scope: DownloadScope) -> ScopePlan:
    """Turn a scope into concrete job tuples ``(pid, kind, target)``.

    Image jobs are only created for pages that are not yet downloaded; thumb
    jobs for every selected illust; ugoira jobs for zip + transcode.
    """
    if empty_scope_matches_nothing(scope):
        return ScopePlan(pids=[], jobs=[])

    pid_rows = (await session.execute(build_illust_filter(scope))).scalars().all()
    pids = list(pid_rows)
    if not pids:
        return ScopePlan(pids=[], jobs=[])

    type_rows = (
        await session.execute(select(Illust.pid, Illust.type).where(Illust.pid.in_(pids)))
    ).all()
    types = {pid: kind for pid, kind in type_rows}

    page_rows = (
        await session.execute(
            select(
                IllustPage.pid,
                IllustPage.page_index,
                IllustPage.download_state,
                IllustPage.ext,
            )
            .where(IllustPage.pid.in_(pids))
            .order_by(IllustPage.pid, IllustPage.page_index)
        )
    ).all()
    pending_pages: dict[int, list[tuple[int, str]]] = {}
    for pid, page_index, state, ext in page_rows:
        if state != "done":
            pending_pages.setdefault(pid, []).append((page_index, ext))

    ugoira_pids = {
        row[0]
        for row in (
            await session.execute(select(UgoiraMeta.pid).where(UgoiraMeta.pid.in_(pids)))
        ).all()
    }

    jobs: list[tuple[int, str, str]] = []
    for pid in pids:
        for page_index, ext in pending_pages.get(pid, []):
            jobs.append((pid, "image", f"{page_index:03d}_p{page_index}{ext}"))
        if types.get(pid) == "ugoira" and pid in ugoira_pids:
            jobs.append((pid, "ugoira_zip", "source.zip"))
            jobs.append((pid, "ugoira_mp4", "animation.mp4"))
        jobs.append((pid, "thumb", "thumb.webp"))
    return ScopePlan(pids=pids, jobs=jobs)
```

`web/schemas.py` 的 `DownloadRequest` 替换为：

```python
class DownloadRequest(BaseModel):
    scope: str = "all_missing"
    pids: list[int] = Field(default_factory=list)
    author_id: int | None = None
    start: int | None = None
    count: int | None = None
    x_restrict: int | None = None
    type: str | None = None
    with_thumbs: bool = True
    # filter-scope extras (same fields as the gallery filters)
    tags: list[str] = Field(default_factory=list)
    author_ids: list[int] = Field(default_factory=list)
    q: str | None = None
    restrict: str | None = None
    downloaded: bool | None = None
    page_min: int | None = None
    page_max: int | None = None
    bookmarks_min: int | None = None
    bookmarks_max: int | None = None
    views_min: int | None = None
    views_max: int | None = None
    only_unbookmarked: bool = False
    include_unbookmarked: bool = False
```

`web/routers/tasks.py` 的 `_scope_from_request` 替换为：

```python
def _scope_from_request(payload: DownloadRequest) -> DownloadScope:
    kind = _SCOPE_ALIASES.get(payload.scope)
    if kind is None:
        raise HTTPException(status_code=422, detail=f"unknown scope {payload.scope}")
    return DownloadScope(
        kind=kind,
        pids=payload.pids,
        author_id=payload.author_id,
        start=payload.start,
        count=payload.count,
        x_restrict=payload.x_restrict,
        type=payload.type,
        tags=payload.tags,
        author_ids=payload.author_ids,
        q=payload.q,
        restrict=payload.restrict,
        downloaded=payload.downloaded,
        page_min=payload.page_min,
        page_max=payload.page_max,
        bookmarks_min=payload.bookmarks_min,
        bookmarks_max=payload.bookmarks_max,
        views_min=payload.views_min,
        views_max=payload.views_max,
        only_unbookmarked=payload.only_unbookmarked,
        include_unbookmarked=payload.include_unbookmarked,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_download_scope.py tests/test_web_routers_tasks.py tests/test_cli_download.py -q`
Expected: 全部通过（旧语义不变：`selected`/`author`/`rank_range`/`all_missing` 行为与原来一致）

- [ ] **Step 5: lint / mypy / 全量单测**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy && uv run pytest -q`
Expected: 全部通过

- [ ] **Step 6: Commit**

```bash
git add src/pixiv_archive/download/scope.py src/pixiv_archive/web/schemas.py src/pixiv_archive/web/routers/tasks.py tests/test_download_scope.py
git commit -m "feat(download): honour full gallery filters in filter scope"
```

---

### Task 5: 前端 API 类型与 URL 构建支持多值与区间

**Files:**
- Modify: `frontend/src/api/types.ts:115-143`
- Modify: `frontend/src/api/queries.ts:15-39`
- Test: `frontend/src/api/queries.test.tsx`（追加用例）

- [ ] **Step 1: 追加失败测试**

在 `frontend/src/api/queries.test.tsx` 的 `describe("useGallery", ...)` 内追加：

```tsx
  it("serializes repeated tags and author ids", async () => {
    const fetchMock = mockJson({ items: [], total: 0, offset: 0, limit: 60 });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(
      () =>
        useGallery({
          limit: 60,
          tags: ["cat", "cute"],
          author_ids: [1, 2],
          page_min: 2,
          page_max: 5,
        }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("tag=cat");
    expect(url).toContain("tag=cute");
    expect(url).toContain("author_id=1");
    expect(url).toContain("author_id=2");
    expect(url).toContain("page_min=2");
    expect(url).toContain("page_max=5");
  });
```

- [ ] **Step 2: 运行测试确认失败**

Run（在 `frontend/`）: `npm test -- src/api/queries.test.tsx`
Expected: FAIL（类型上不存在 `tags` 字段 → TS 报错；运行时 URL 无重复参数）

- [ ] **Step 3: 实现类型与 URL 构建**

`frontend/src/api/types.ts` 中 `GalleryQuery` 替换为：

```ts
export interface GalleryQuery {
  offset?: number;
  limit?: number;
  sort?: "rank" | "create_date" | "bookmarks" | "views";
  author_ids?: number[];
  tags?: string[];
  q?: string;
  type?: "illust" | "ugoira";
  x_restrict?: number;
  downloaded?: boolean;
  restrict?: "public" | "private";
  only_unbookmarked?: boolean;
  include_unbookmarked?: boolean;
  only_deleted?: boolean;
  include_deleted?: boolean;
  page_min?: number;
  page_max?: number;
  bookmarks_min?: number;
  bookmarks_max?: number;
  views_min?: number;
  views_max?: number;
  rank_start?: number;
  rank_count?: number;
}
```

同文件 `DownloadRequest` 替换为：

```ts
export interface DownloadRequest {
  scope: "all_missing" | "author" | "selected" | "rank_range" | "filter";
  pids?: number[];
  author_id?: number;
  start?: number;
  count?: number;
  x_restrict?: number;
  type?: "illust" | "ugoira";
  with_thumbs?: boolean;
  tags?: string[];
  author_ids?: number[];
  q?: string;
  restrict?: "public" | "private";
  downloaded?: boolean;
  page_min?: number;
  page_max?: number;
  bookmarks_min?: number;
  bookmarks_max?: number;
  views_min?: number;
  views_max?: number;
  only_unbookmarked?: boolean;
  include_unbookmarked?: boolean;
}
```

`frontend/src/api/queries.ts` 中 `buildGalleryUrl` 替换为：

```ts
const REPEATED_KEYS: Partial<Record<keyof GalleryQuery, string>> = {
  tags: "tag",
  author_ids: "author_id",
};

export function buildGalleryUrl(query: GalleryQuery): string {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    const paramName = REPEATED_KEYS[key as keyof GalleryQuery] ?? key;
    if (Array.isArray(value)) {
      value.forEach((entry) => {
        if (entry === undefined || entry === null || entry === "") return;
        params.append(paramName, String(entry));
      });
      return;
    }
    params.set(paramName, String(value));
  });
  const suffix = params.toString();
  return suffix ? `/api/gallery?${suffix}` : "/api/gallery";
}
```

- [ ] **Step 4: 运行测试确认通过**

Run（在 `frontend/`）: `npm test -- src/api/queries.test.tsx`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/queries.ts frontend/src/api/queries.test.tsx
git commit -m "feat(web): support repeated and range gallery query params"
```

---

### Task 6: `useGalleryQueryState`（URL 状态）

**Files:**
- Create: `frontend/src/hooks/useGalleryQueryState.ts`
- Test: `frontend/src/hooks/useGalleryQueryState.test.tsx`

- [ ] **Step 1: 写失败的测试**

```tsx
// frontend/src/hooks/useGalleryQueryState.test.tsx
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { useGalleryQueryState } from "./useGalleryQueryState";

function wrapperFor(initialEntry: string) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={[initialEntry]}>{children}</MemoryRouter>;
  };
}

describe("useGalleryQueryState", () => {
  it("parses repeated params into arrays", () => {
    const { result } = renderHook(() => useGalleryQueryState(), {
      wrapper: wrapperFor("/?tag=cat&tag=cute&author_id=1&author_id=2&page_min=2"),
    });
    expect(result.current.query.tags).toEqual(["cat", "cute"]);
    expect(result.current.query.author_ids).toEqual([1, 2]);
    expect(result.current.query.page_min).toBe(2);
  });

  it("omits default values when serializing", () => {
    const { result } = renderHook(
      () => {
        const state = useGalleryQueryState();
        return { state, location: useLocation() };
      },
      { wrapper: wrapperFor("/") },
    );
    act(() => result.current.state.patch({ sort: "rank", offset: 0, limit: 60 }));
    expect(result.current.location.search).toBe("");
  });

  it("resets offset when a filter changes", () => {
    const { result } = renderHook(
      () => {
        const state = useGalleryQueryState();
        return { state, location: useLocation() };
      },
      { wrapper: wrapperFor("/?offset=120") },
    );
    act(() => result.current.state.patch({ tags: ["cat"] }));
    expect(result.current.state.query.offset).toBe(0);
    expect(result.current.location.search).toContain("tag=cat");
  });

  it("applies the provided initial filter", () => {
    const { result } = renderHook(
      () => useGalleryQueryState({ only_unbookmarked: true }),
      { wrapper: wrapperFor("/") },
    );
    expect(result.current.query.only_unbookmarked).toBe(true);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run（在 `frontend/`）: `npm test -- src/hooks/useGalleryQueryState.test.tsx`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 hook**

```ts
// frontend/src/hooks/useGalleryQueryState.ts
import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import type { GalleryQuery } from "../api/types";
import { PAGE_SIZE } from "../lib/constants";

const SINGLE_KEYS = [
  "offset",
  "limit",
  "sort",
  "q",
  "type",
  "x_restrict",
  "downloaded",
  "restrict",
  "only_unbookmarked",
  "include_unbookmarked",
  "only_deleted",
  "include_deleted",
  "page_min",
  "page_max",
  "bookmarks_min",
  "bookmarks_max",
  "views_min",
  "views_max",
  "rank_start",
  "rank_count",
] as const;

type SingleKey = (typeof SINGLE_KEYS)[number];
type ListKey = "tags" | "author_ids";

const LIST_PARAM_NAMES: Record<ListKey, string> = {
  tags: "tag",
  author_ids: "author_id",
};

const INT_KEYS = new Set<SingleKey>([
  "offset",
  "limit",
  "x_restrict",
  "page_min",
  "page_max",
  "bookmarks_min",
  "bookmarks_max",
  "views_min",
  "views_max",
  "rank_start",
  "rank_count",
]);

const BOOL_KEYS = new Set<SingleKey>([
  "downloaded",
  "only_unbookmarked",
  "include_unbookmarked",
  "only_deleted",
  "include_deleted",
]);

const DEFAULT_VALUES: Partial<Record<SingleKey, string>> = {
  offset: "0",
  limit: String(PAGE_SIZE),
  sort: "rank",
};

function parseSingle(key: SingleKey, raw: string): unknown {
  if (INT_KEYS.has(key)) {
    const value = Number(raw);
    return Number.isFinite(value) ? value : undefined;
  }
  if (BOOL_KEYS.has(key)) {
    return raw === "true" ? true : raw === "false" ? false : undefined;
  }
  return raw === "" ? undefined : raw;
}

export interface UseGalleryQueryState {
  query: GalleryQuery;
  patch: (update: Partial<GalleryQuery>) => void;
  reset: () => void;
}

export function useGalleryQueryState(
  initial: Partial<GalleryQuery> = {},
): UseGalleryQueryState {
  const [searchParams, setSearchParams] = useSearchParams();

  const query = useMemo(() => {
    const parsed: GalleryQuery = { offset: 0, limit: PAGE_SIZE, sort: "rank" };
    SINGLE_KEYS.forEach((key) => {
      if (key in initial) return;
      const raw = searchParams.get(key);
      if (raw === null || raw === "") return;
      (parsed as Record<string, unknown>)[key] = parseSingle(key, raw);
    });
    (Object.keys(LIST_PARAM_NAMES) as ListKey[]).forEach((key) => {
      const raw = searchParams.getAll(LIST_PARAM_NAMES[key]);
      if (raw.length === 0) return;
      if (key === "author_ids") {
        const ids = raw.map(Number).filter((value) => Number.isFinite(value));
        if (ids.length > 0) (parsed as Record<string, unknown>)[key] = ids;
        return;
      }
      (parsed as Record<string, unknown>)[key] = raw;
    });
    return { ...parsed, ...initial };
  }, [searchParams, initial]);

  const patch = useCallback(
    (update: Partial<GalleryQuery>) => {
      const next = new URLSearchParams(searchParams);
      Object.entries(update).forEach(([key, value]) => {
        if (key === "tags" || key === "author_ids") {
          const paramName = LIST_PARAM_NAMES[key];
          next.delete(paramName);
          if (Array.isArray(value) && value.length > 0) {
            value.forEach((entry) => next.append(paramName, String(entry)));
          }
          return;
        }
        if (value === undefined || value === null || value === "") {
          next.delete(key);
          return;
        }
        const defaultValue = DEFAULT_VALUES[key as SingleKey];
        if (defaultValue !== undefined && String(value) === defaultValue) {
          next.delete(key);
          return;
        }
        if (Array.isArray(value)) return;
        next.set(key, String(value));
      });
      if (!("offset" in update)) {
        next.delete("offset");
      }
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const reset = useCallback(() => {
    setSearchParams(new URLSearchParams(), { replace: true });
  }, [setSearchParams]);

  return { query, patch, reset };
}
```

- [ ] **Step 4: 运行测试确认通过**

Run（在 `frontend/`）: `npm test -- src/hooks/useGalleryQueryState.test.tsx`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useGalleryQueryState.ts frontend/src/hooks/useGalleryQueryState.test.tsx
git commit -m "feat(web): sync gallery filters with the URL"
```

---

### Task 7: SelectionContext（跨路由选择）

**Files:**
- Create: `frontend/src/contexts/SelectionContext.tsx`
- Test: `frontend/src/contexts/SelectionContext.test.tsx`

- [ ] **Step 1: 写失败的测试**

```tsx
// frontend/src/contexts/SelectionContext.test.tsx
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { SelectionProvider, useSelection } from "./SelectionContext";

function wrapper({ children }: { children: ReactNode }) {
  return <SelectionProvider>{children}</SelectionProvider>;
}

describe("SelectionContext", () => {
  it("toggles pids on and off", () => {
    const { result } = renderHook(() => useSelection(), { wrapper });
    act(() => result.current.toggle(1));
    expect(result.current.selected.has(1)).toBe(true);
    act(() => result.current.toggle(1));
    expect(result.current.selected.has(1)).toBe(false);
  });

  it("accumulates across pages via selectMany", () => {
    const { result } = renderHook(() => useSelection(), { wrapper });
    act(() => result.current.selectMany([1, 2]));
    act(() => result.current.selectMany([3]));
    expect(result.current.count).toBe(3);
  });

  it("removes a subset and clears", () => {
    const { result } = renderHook(() => useSelection(), { wrapper });
    act(() => result.current.selectMany([1, 2, 3]));
    act(() => result.current.removeMany([1, 3]));
    expect([...result.current.selected]).toEqual([2]);
    act(() => result.current.clear());
    expect(result.current.count).toBe(0);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run（在 `frontend/`）: `npm test -- src/contexts/SelectionContext.test.tsx`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 SelectionContext**

```tsx
// frontend/src/contexts/SelectionContext.tsx
import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

export interface SelectionValue {
  selected: Set<number>;
  count: number;
  toggle: (pid: number) => void;
  selectMany: (pids: number[]) => void;
  removeMany: (pids: number[]) => void;
  clear: () => void;
}

const SelectionContext = createContext<SelectionValue | null>(null);

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [selected, setSelected] = useState<Set<number>>(() => new Set());

  const toggle = useCallback((pid: number) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(pid)) next.delete(pid);
      else next.add(pid);
      return next;
    });
  }, []);

  const selectMany = useCallback((pids: number[]) => {
    setSelected((current) => {
      const next = new Set(current);
      pids.forEach((pid) => next.add(pid));
      return next;
    });
  }, []);

  const removeMany = useCallback((pids: number[]) => {
    setSelected((current) => {
      const next = new Set(current);
      pids.forEach((pid) => next.delete(pid));
      return next;
    });
  }, []);

  const clear = useCallback(() => setSelected(new Set()), []);

  const value = useMemo(
    () => ({ selected, count: selected.size, toggle, selectMany, removeMany, clear }),
    [selected, toggle, selectMany, removeMany, clear],
  );

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}

export function useSelection(): SelectionValue {
  const value = useContext(SelectionContext);
  if (value === null) {
    throw new Error("useSelection must be used inside SelectionProvider");
  }
  return value;
}
```

- [ ] **Step 4: 运行测试确认通过**

Run（在 `frontend/`）: `npm test -- src/contexts/SelectionContext.test.tsx`
Expected: 全部通过

- [ ] **Step 5: 删除旧 hook 与其测试**

删除 `frontend/src/hooks/useSelection.ts` 与 `frontend/src/hooks/useSelection.test.ts`（由 Context 取代；`Gallery.tsx` 在 Task 10 改为使用 Context，两者同一提交内完成替换以免中间态报错——**因此本步骤与 Task 10 合并提交**，此处先不删除，见 Task 10）。

- [ ] **Step 6: Commit（仅新增 Context）**

```bash
git add frontend/src/contexts/SelectionContext.tsx frontend/src/contexts/SelectionContext.test.tsx
git commit -m "feat(web): add cross-route selection context"
```

---

### Task 8: GalleryFiltersContext（供导出页读取筛选）

**Files:**
- Create: `frontend/src/contexts/GalleryFiltersContext.tsx`
- Test: `frontend/src/contexts/GalleryFiltersContext.test.tsx`

- [ ] **Step 1: 写失败的测试**

```tsx
// frontend/src/contexts/GalleryFiltersContext.test.tsx
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { GalleryFiltersProvider, useGalleryFilters } from "./GalleryFiltersContext";

function wrapper({ children }: { children: ReactNode }) {
  return <GalleryFiltersProvider>{children}</GalleryFiltersProvider>;
}

describe("GalleryFiltersContext", () => {
  it("starts empty", () => {
    const { result } = renderHook(() => useGalleryFilters(), { wrapper });
    expect(result.current.filters).toEqual({});
  });

  it("stores the latest gallery filters", () => {
    const { result } = renderHook(() => useGalleryFilters(), { wrapper });
    act(() => result.current.setFilters({ tags: ["cat"], downloaded: false }));
    expect(result.current.filters).toEqual({ tags: ["cat"], downloaded: false });
  });

  it("clears filters back to empty", () => {
    const { result } = renderHook(() => useGalleryFilters(), { wrapper });
    act(() => result.current.setFilters({ q: "fox" }));
    act(() => result.current.setFilters({}));
    expect(result.current.filters).toEqual({});
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run（在 `frontend/`）: `npm test -- src/contexts/GalleryFiltersContext.test.tsx`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 GalleryFiltersContext**

```tsx
// frontend/src/contexts/GalleryFiltersContext.tsx
import { createContext, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

import type { GalleryQuery } from "../api/types";

export interface GalleryFiltersValue {
  filters: Partial<GalleryQuery>;
  setFilters: (filters: Partial<GalleryQuery>) => void;
}

const GalleryFiltersContext = createContext<GalleryFiltersValue | null>(null);

export function GalleryFiltersProvider({ children }: { children: ReactNode }) {
  const [filters, setFilters] = useState<Partial<GalleryQuery>>({});
  const value = useMemo(() => ({ filters, setFilters }), [filters]);
  return (
    <GalleryFiltersContext.Provider value={value}>{children}</GalleryFiltersContext.Provider>
  );
}

export function useGalleryFilters(): GalleryFiltersValue {
  const value = useContext(GalleryFiltersContext);
  if (value === null) {
    throw new Error("useGalleryFilters must be used inside GalleryFiltersProvider");
  }
  return value;
}
```

- [ ] **Step 4: 运行测试确认通过**

Run（在 `frontend/`）: `npm test -- src/contexts/GalleryFiltersContext.test.tsx`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add frontend/src/contexts/GalleryFiltersContext.tsx frontend/src/contexts/GalleryFiltersContext.test.tsx
git commit -m "feat(web): expose latest gallery filters to other pages"
```

---

### Task 9: Pagination 增强

**Files:**
- Modify: `frontend/src/components/Pagination.tsx`（完整替换）
- Modify: `frontend/src/components/Pagination.test.tsx`（追加用例）
- Modify: `frontend/src/lib/constants.ts`（新增 `PAGE_SIZE_OPTIONS`）

- [ ] **Step 1: 追加失败测试**

在 `frontend/src/components/Pagination.test.tsx` 末尾追加：

```tsx
  it("offers page size options and reports a change", async () => {
    const onLimitChange = vi.fn();
    render(
      <Pagination
        offset={0}
        limit={60}
        total={200}
        onChange={() => undefined}
        onLimitChange={onLimitChange}
      />,
    );
    await userEvent.selectOptions(screen.getByLabelText("每页数量"), "240");
    expect(onLimitChange).toHaveBeenCalledWith(240);
  });

  it("jumps to a page number", async () => {
    const onChange = vi.fn();
    render(<Pagination offset={0} limit={60} total={600} onChange={onChange} />);
    const input = screen.getByLabelText("页码");
    await userEvent.clear(input);
    await userEvent.type(input, "5{Enter}");
    expect(onChange).toHaveBeenCalledWith(240);
  });

  it("jumps to the last page", async () => {
    const onChange = vi.fn();
    render(<Pagination offset={0} limit={60} total={130} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "末页" }));
    expect(onChange).toHaveBeenCalledWith(120);
  });

  it("changes pages with arrow keys", async () => {
    const onChange = vi.fn();
    render(<Pagination offset={60} limit={60} total={200} onChange={onChange} />);
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalledWith(120);
  });
```

- [ ] **Step 2: 运行测试确认失败**

Run（在 `frontend/`）: `npm test -- src/components/Pagination.test.tsx`
Expected: 新用例 FAIL（props / 元素不存在）

- [ ] **Step 3: 实现新 Pagination**

`frontend/src/lib/constants.ts` 追加：

```ts
export const PAGE_SIZE_OPTIONS = [60, 120, 240] as const;
```

`frontend/src/components/Pagination.tsx` 替换为：

```tsx
import { useEffect, useState } from "react";

import { PAGE_SIZE_OPTIONS } from "../lib/constants";

interface Props {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
  onLimitChange?: (limit: number) => void;
}

const NAV_KEYS = new Set(["ArrowLeft", "ArrowRight"]);

export default function Pagination({
  offset,
  limit,
  total,
  onChange,
  onLimitChange,
}: Props) {
  const pageCount = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.min(pageCount, Math.floor(offset / limit) + 1);
  const [pageInput, setPageInput] = useState(String(currentPage));

  useEffect(() => setPageInput(String(currentPage)), [currentPage]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (!NAV_KEYS.has(event.key)) return;
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (event.key === "ArrowRight" && offset + limit < total) {
        onChange(offset + limit);
      }
      if (event.key === "ArrowLeft" && offset > 0) {
        onChange(Math.max(0, offset - limit));
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [offset, limit, total, onChange]);

  const start = total === 0 ? 0 : Math.min(offset + 1, total);
  const end = Math.min(offset + limit, total);
  const hasPrevious = offset > 0;
  const hasNext = offset + limit < total;
  const lastOffset = Math.max(0, (pageCount - 1) * limit);

  const jumpToPage = () => {
    const parsed = Number(pageInput);
    if (!Number.isFinite(parsed)) {
      setPageInput(String(currentPage));
      return;
    }
    const clamped = Math.min(pageCount, Math.max(1, Math.trunc(parsed)));
    setPageInput(String(clamped));
    onChange((clamped - 1) * limit);
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-4 text-sm text-text-muted">
      <span>
        {start}–{end} / 共 {total}
      </span>
      <div className="flex flex-wrap items-center gap-2">
        {onLimitChange ? (
          <label className="flex items-center gap-1.5">
            每页
            <select
              aria-label="每页数量"
              value={limit}
              onChange={(event) => onLimitChange(Number(event.target.value))}
              className="rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5"
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <button
          type="button"
          disabled={!hasPrevious}
          onClick={() => onChange(0)}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          首页
        </button>
        <button
          type="button"
          disabled={!hasPrevious}
          onClick={() => onChange(Math.max(0, offset - limit))}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          上一页
        </button>
        <label className="flex items-center gap-1.5">
          第
          <input
            aria-label="页码"
            value={pageInput}
            onChange={(event) => setPageInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") jumpToPage();
            }}
            onBlur={() => setPageInput(String(currentPage))}
            className="w-14 rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5 text-center"
          />
          / {pageCount} 页
        </label>
        <button
          type="button"
          disabled={!hasNext}
          onClick={() => onChange(offset + limit)}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          下一页
        </button>
        <button
          type="button"
          disabled={!hasNext}
          onClick={() => onChange(lastOffset)}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          末页
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run（在 `frontend/`）: `npm test -- src/components/Pagination.test.tsx`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Pagination.tsx frontend/src/components/Pagination.test.tsx frontend/src/lib/constants.ts
git commit -m "feat(web): add page size, jump and keyboard navigation"
```

---

### Task 10: Gallery 页面接入 SelectionContext 与 URL 状态；删除旧 hook

**Files:**
- Modify: `frontend/src/pages/Gallery.tsx`（完整替换）
- Modify: `frontend/src/App.tsx`（挂 Provider）
- Delete: `frontend/src/hooks/useSelection.ts`、`frontend/src/hooks/useSelection.test.ts`
- Test: `frontend/src/pages/Gallery.test.tsx`（新建）

- [ ] **Step 1: 写失败的测试**

```tsx
// frontend/src/pages/Gallery.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GalleryFiltersProvider } from "../contexts/GalleryFiltersContext";
import { SelectionProvider } from "../contexts/SelectionContext";
import Gallery from "./Gallery";

const ITEM = {
  pid: 1,
  index: 1,
  title: "作品一",
  author_id: 1,
  author_name: "画师",
  page_count: 1,
  type: "illust",
  x_restrict: 0,
  width: 100,
  height: 100,
  create_date: null,
  rank: 0,
  has_original: false,
  page_downloaded_count: 0,
  preview_url: "/api/illust/1/thumb",
  thumb_url: "/api/illust/1/thumb",
  restrict: "public",
  unbookmarked: false,
  state: "active",
};

function wrapper(initialEntry = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[initialEntry]}>
          <SelectionProvider>
            <GalleryFiltersProvider>{children}</GalleryFiltersProvider>
          </SelectionProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
  };
}

afterEach(() => vi.restoreAllMocks());

function mockGallery() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.includes("/api/gallery")
        ? { items: [ITEM], total: 1, offset: 0, limit: 60 }
        : { task_id: "t", filename: "f" };
      return Promise.resolve(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    }),
  );
}

describe("Gallery", () => {
  it("selects the whole page", async () => {
    mockGallery();
    render(<Gallery />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("作品一")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "全选本页" }));
    expect(screen.getByText(/下载选中 \(1\)/)).toBeInTheDocument();
  });

  it("inverts the page selection", async () => {
    mockGallery();
    render(<Gallery />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("作品一")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "反选本页" }));
    expect(screen.getByText(/下载选中 \(1\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "反选本页" }));
    expect(screen.getByText(/下载选中 \(0\)/)).toBeInTheDocument();
  });

  it("keeps selection across pages (selection context)", async () => {
    mockGallery();
    render(<Gallery />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("作品一")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByText(/下载选中 \(1\)/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run（在 `frontend/`）: `npm test -- src/pages/Gallery.test.tsx`
Expected: FAIL（`全选本页` 按钮不存在）

- [ ] **Step 3: 改写 Gallery 与 Toolbar，挂 Provider**

`frontend/src/pages/Gallery.tsx` 替换为：

```tsx
import { useEffect, useMemo } from "react";

import { useStartDownload } from "../api/mutations";
import { useGallery } from "../api/queries";
import type { GalleryQuery } from "../api/types";
import GalleryGrid from "../components/GalleryGrid";
import Pagination from "../components/Pagination";
import Toolbar from "../components/Toolbar";
import { useGalleryFilters } from "../contexts/GalleryFiltersContext";
import { useSelection } from "../contexts/SelectionContext";
import { useGalleryQueryState } from "../hooks/useGalleryQueryState";
import { PAGE_SIZE } from "../lib/constants";

interface Props {
  initialOnlyUnbookmarked?: boolean;
}

export default function Gallery({ initialOnlyUnbookmarked = false }: Props) {
  const initial = useMemo(
    () => (initialOnlyUnbookmarked ? { only_unbookmarked: true } : {}),
    [initialOnlyUnbookmarked],
  );
  const { query, patch } = useGalleryQueryState(initial);
  const { filters, setFilters } = useGalleryFilters();
  const { data, isLoading, isError, error } = useGallery(query);
  const selection = useSelection();
  const download = useStartDownload();

  const items = useMemo(() => data?.items ?? [], [data]);
  const pagePids = useMemo(() => items.map((item) => item.pid), [items]);
  const undownloadedPids = useMemo(
    () => items.filter((item) => !item.has_original).map((item) => item.pid),
    [items],
  );

  useEffect(() => {
    setFilters(query);
  }, [query, setFilters]);

  const downloadSelected = () => {
    const pids = Array.from(selection.selected);
    download.mutate(
      { scope: "selected", pids, with_thumbs: true },
      { onSuccess: () => selection.clear() },
    );
  };

  const downloadAllMissing = () => {
    const filter: Partial<GalleryQuery> = {
      tags: query.tags,
      author_ids: query.author_ids,
      q: query.q,
      type: query.type,
      x_restrict: query.x_restrict,
      downloaded: false,
      restrict: query.restrict,
      only_unbookmarked: query.only_unbookmarked,
      include_unbookmarked: query.include_unbookmarked,
      page_min: query.page_min,
      page_max: query.page_max,
      bookmarks_min: query.bookmarks_min,
      bookmarks_max: query.bookmarks_max,
      views_min: query.views_min,
      views_max: query.views_max,
    };
    download.mutate({
      scope: "filter",
      ...filter,
      with_thumbs: true,
    });
  };

  return (
    <div className="flex min-h-full flex-col">
      <Toolbar
        query={query}
        onChange={patch}
        pagePids={pagePids}
        undownloadedPids={undownloadedPids}
        onDownloadSelected={downloadSelected}
        onDownloadAllMissing={downloadAllMissing}
        downloadPending={download.isPending}
      />

      <div className="flex-1 px-4 pt-4">
        {isLoading ? (
          <div className="flex min-h-[240px] items-center justify-center text-sm text-text-muted">
            加载中…
          </div>
        ) : isError ? (
          <div className="flex min-h-[240px] items-center justify-center text-sm text-red-400">
            加载失败：{error instanceof Error ? error.message : "未知错误"}
          </div>
        ) : (
          <GalleryGrid
            items={items}
            selected={selection.selected}
            onToggle={selection.toggle}
          />
        )}
      </div>

      <div className="px-4">
        <Pagination
          offset={query.offset ?? 0}
          limit={query.limit ?? PAGE_SIZE}
          total={data?.total ?? 0}
          onChange={(offset) => patch({ offset })}
          onLimitChange={(limit) => patch({ limit, offset: 0 })}
        />
      </div>
    </div>
  );
}
```

`frontend/src/App.tsx` 中 `App` 返回值外层包裹 Provider（`Routes` 外）：

```tsx
import { SelectionProvider } from "./contexts/SelectionContext";
import { GalleryFiltersProvider } from "./contexts/GalleryFiltersContext";
// ...现有 import 不变

  return (
    <SelectionProvider>
      <GalleryFiltersProvider>
        <Routes>
          {/* ...现有路由不变... */}
        </Routes>
      </GalleryFiltersProvider>
    </SelectionProvider>
  );
```

- [ ] **Step 4: 更新 Toolbar 的 props 与实现（页级按钮 + 选择面板）**

`frontend/src/components/Toolbar.tsx` 替换为：

```tsx
import { useEffect, useState } from "react";

import type { GalleryQuery } from "../api/types";
import { useSelection } from "../contexts/SelectionContext";
import {
  DOWNLOAD_OPTIONS,
  R18_OPTIONS,
  RESTRICT_OPTIONS,
  SORT_OPTIONS,
  STATUS_OPTIONS,
  TYPE_OPTIONS,
} from "../lib/constants";

interface Props {
  query: GalleryQuery;
  onChange: (patch: Partial<GalleryQuery>) => void;
  pagePids: number[];
  undownloadedPids: number[];
  onDownloadSelected: () => void;
  onDownloadAllMissing: () => void;
  downloadPending: boolean;
}

function Select({
  value,
  options,
  onChange,
  ariaLabel,
}: {
  value: string;
  options: readonly { value: string; label: string }[];
  onChange: (value: string) => void;
  ariaLabel: string;
}) {
  return (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5 text-sm outline-none focus:border-accent"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

function RangeInputs({
  ariaLabel,
  minValue,
  maxValue,
  onApply,
}: {
  ariaLabel: string;
  minValue?: number;
  maxValue?: number;
  onApply: (min?: number, max?: number) => void;
}) {
  const [min, setMin] = useState(minValue === undefined ? "" : String(minValue));
  const [max, setMax] = useState(maxValue === undefined ? "" : String(maxValue));

  useEffect(() => {
    setMin(minValue === undefined ? "" : String(minValue));
    setMax(maxValue === undefined ? "" : String(maxValue));
  }, [minValue, maxValue]);

  const apply = () => {
    const parse = (raw: string) => {
      if (raw.trim() === "") return undefined;
      const value = Number(raw);
      return Number.isFinite(value) ? value : undefined;
    };
    onApply(parse(min), parse(max));
  };
  return (
    <span className="flex items-center gap-1 text-xs text-text-muted">
      {ariaLabel}
      <input
        aria-label={`${ariaLabel}最小值`}
        value={min}
        onChange={(event) => setMin(event.target.value)}
        onBlur={apply}
        onKeyDown={(event) => {
          if (event.key === "Enter") apply();
        }}
        className="w-16 rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5 text-sm"
      />
      <span>–</span>
      <input
        aria-label={`${ariaLabel}最大值`}
        value={max}
        onChange={(event) => setMax(event.target.value)}
        onBlur={apply}
        onKeyDown={(event) => {
          if (event.key === "Enter") apply();
        }}
        className="w-16 rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5 text-sm"
      />
    </span>
  );
}

export default function Toolbar({
  query,
  onChange,
  pagePids,
  undownloadedPids,
  onDownloadSelected,
  onDownloadAllMissing,
  downloadPending,
}: Props) {
  const selection = useSelection();
  const [panelOpen, setPanelOpen] = useState(false);
  const filterCount = [
    query.tags?.length,
    query.author_ids?.length,
    query.q,
    query.type,
    query.x_restrict !== undefined ? 1 : undefined,
    query.downloaded !== undefined ? 1 : undefined,
    query.restrict,
    query.page_min ?? query.page_max,
    query.bookmarks_min ?? query.bookmarks_max,
    query.views_min ?? query.views_max,
    query.only_unbookmarked,
    query.only_deleted || query.include_deleted,
  ].filter((value) => value !== undefined && value !== null && value !== false && value !== "")
    .length;

  return (
    <div className="sticky top-0 z-20 space-y-2 border-b border-border-subtle bg-surface/95 px-4 py-3 backdrop-blur">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          ariaLabel="排序"
          value={query.sort ?? "rank"}
          options={SORT_OPTIONS}
          onChange={(value) => onChange({ sort: value as GalleryQuery["sort"], offset: 0 })}
        />
        <Select
          ariaLabel="类型"
          value={query.type ?? ""}
          options={TYPE_OPTIONS}
          onChange={(value) =>
            onChange({ type: (value || undefined) as GalleryQuery["type"], offset: 0 })
          }
        />
        <Select
          ariaLabel="下载状态"
          value={query.downloaded === undefined ? "" : query.downloaded ? "yes" : "no"}
          options={DOWNLOAD_OPTIONS}
          onChange={(value) =>
            onChange({
              downloaded: value === "" ? undefined : value === "yes",
              offset: 0,
            })
          }
        />
        <Select
          ariaLabel="收藏夹"
          value={query.restrict ?? ""}
          options={RESTRICT_OPTIONS}
          onChange={(value) =>
            onChange({
              restrict: (value || undefined) as GalleryQuery["restrict"],
              offset: 0,
            })
          }
        />
        <Select
          ariaLabel="分级"
          value={query.x_restrict === undefined ? "" : String(query.x_restrict)}
          options={R18_OPTIONS}
          onChange={(value) =>
            onChange({
              x_restrict: value === "" ? undefined : Number(value),
              offset: 0,
            })
          }
        />
        <Select
          ariaLabel="状态"
          value={query.only_deleted ? "deleted" : query.include_deleted ? "all" : "active"}
          options={STATUS_OPTIONS}
          onChange={(value) => {
            const patch: Partial<GalleryQuery> = {
              only_deleted: value === "deleted" ? true : undefined,
              include_deleted: value === "all" ? true : undefined,
              offset: 0,
            };
            if (value === "active") {
              delete patch.only_deleted;
              delete patch.include_deleted;
            }
            onChange(patch);
          }}
        />
        <Select
          ariaLabel="页数预设"
          value={
            query.page_min === 1 && query.page_max === 1
              ? "1"
              : query.page_min === 2 && query.page_max === 5
                ? "2-5"
                : query.page_min === 6 && query.page_max === 10
                  ? "6-10"
                  : query.page_min === 11 && query.page_max === undefined
                    ? "11+"
                    : ""
          }
          options={[
            { value: "", label: "全部页数" },
            { value: "1", label: "1P" },
            { value: "2-5", label: "2–5P" },
            { value: "6-10", label: "6–10P" },
            { value: "11+", label: "11P+" },
          ]}
          onChange={(value) => {
            const preset: Record<string, Partial<GalleryQuery>> = {
              "": { page_min: undefined, page_max: undefined },
              "1": { page_min: 1, page_max: 1 },
              "2-5": { page_min: 2, page_max: 5 },
              "6-10": { page_min: 6, page_max: 10 },
              "11+": { page_min: 11, page_max: undefined },
            };
            onChange({ ...preset[value], offset: 0 });
          }}
        />
        <RangeInputs
          ariaLabel="页数自定义"
          minValue={query.page_min}
          maxValue={query.page_max}
          onApply={(min, max) => onChange({ page_min: min, page_max: max, offset: 0 })}
        />
        <RangeInputs
          ariaLabel="收藏"
          minValue={query.bookmarks_min}
          maxValue={query.bookmarks_max}
          onApply={(min, max) =>
            onChange({ bookmarks_min: min, bookmarks_max: max, offset: 0 })
          }
        />
        <RangeInputs
          ariaLabel="浏览"
          minValue={query.views_min}
          maxValue={query.views_max}
          onApply={(min, max) => onChange({ views_min: min, views_max: max, offset: 0 })}
        />

        <input
          type="search"
          placeholder="搜索标题或画师（回车）"
          defaultValue={query.q ?? ""}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              onChange({ q: event.currentTarget.value || undefined, offset: 0 });
            }
          }}
          className="min-w-[180px] flex-1 rounded-md border border-border-subtle bg-surface-raised px-3 py-1.5 text-sm outline-none focus:border-accent"
        />
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <button
          type="button"
          onClick={() => selection.selectMany(pagePids)}
          disabled={pagePids.length === 0}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          全选本页
        </button>
        <button
          type="button"
          onClick={() => selection.removeMany(pagePids)}
          disabled={pagePids.length === 0}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          取消本页
        </button>
        <button
          type="button"
          onClick={() => {
            const toRemove = pagePids.filter((pid) => selection.selected.has(pid));
            const toAdd = pagePids.filter((pid) => !selection.selected.has(pid));
            selection.removeMany(toRemove);
            selection.selectMany(toAdd);
          }}
          disabled={pagePids.length === 0}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          反选本页
        </button>
        <button
          type="button"
          onClick={() => selection.selectMany(undownloadedPids)}
          disabled={undownloadedPids.length === 0}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          仅选本页未下载
        </button>

        <button
          type="button"
          onClick={() => setPanelOpen((open) => !open)}
          disabled={selection.count === 0}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          已选 {selection.count}
        </button>
        {panelOpen ? (
          <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
            <span>已选 {selection.count} 项（跨页累积）</span>
            <button
              type="button"
              onClick={() => selection.removeMany(pagePids)}
              className="rounded border border-border-subtle px-2 py-0.5"
            >
              移除本页选中
            </button>
            <button
              type="button"
              onClick={selection.clear}
              className="rounded border border-border-subtle px-2 py-0.5"
            >
              清空
            </button>
          </div>
        ) : null}

        <div className="flex-1" />
        {filterCount > 0 ? (
          <button
            type="button"
            onClick={() =>
              onChange({
                tags: undefined,
                author_ids: undefined,
                q: undefined,
                type: undefined,
                x_restrict: undefined,
                downloaded: undefined,
                restrict: undefined,
                page_min: undefined,
                page_max: undefined,
                bookmarks_min: undefined,
                bookmarks_max: undefined,
                views_min: undefined,
                views_max: undefined,
                only_unbookmarked: undefined,
                only_deleted: undefined,
                include_deleted: undefined,
                offset: 0,
              })
            }
            className="rounded-md border border-border-subtle px-3 py-1.5 text-xs"
          >
            清空筛选（{filterCount}）
          </button>
        ) : null}
        <button
          type="button"
          onClick={onDownloadSelected}
          disabled={selection.count === 0 || downloadPending}
          className="rounded-md border border-border-subtle px-3 py-1.5 disabled:opacity-40"
        >
          下载选中 ({selection.count})
        </button>
        <button
          type="button"
          onClick={onDownloadAllMissing}
          disabled={downloadPending}
          className="rounded-md bg-accent px-3 py-1.5 font-medium text-white disabled:opacity-40"
        >
          下载全部未下载
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: 删除旧 hook 与旧测试**

```bash
git rm frontend/src/hooks/useSelection.ts frontend/src/hooks/useSelection.test.ts
```

- [ ] **Step 6: 运行测试确认通过**

Run（在 `frontend/`）: `npm test -- src/pages/Gallery.test.tsx src/components/Toolbar.test.tsx src/components/GalleryCard.test.tsx`
Expected: 新 Gallery 用例通过；`Toolbar.test.tsx` 与 `GalleryCard.test.tsx` 若因 props 变更失败，按下述方式修正后再跑：

`Toolbar.test.tsx` 的 `renderToolbar` 更新为：

```tsx
function renderToolbar(onChange = vi.fn()) {
  render(
    <SelectionProvider>
      <Toolbar
        query={{ offset: 0, limit: 60, sort: "rank" }}
        onChange={onChange}
        pagePids={[]}
        undownloadedPids={[]}
        onDownloadSelected={() => undefined}
        onDownloadAllMissing={() => undefined}
        downloadPending={false}
      />
    </SelectionProvider>,
  );
  return onChange;
}
```

（第二个 `render(` 调用同样包裹 `<SelectionProvider>` 并补充新 props。）

- [ ] **Step 7: 全量前端验证**

Run（在 `frontend/`）: `npm run lint; npm run typecheck; npm test`
Expected: 全部通过

- [ ] **Step 8: Commit**

```bash
git add -A frontend/src
git commit -m "feat(web): cross-page selection and URL-driven gallery filters"
```

---

### Task 11: 详情页选择按钮与作者链接修正

**Files:**
- Modify: `frontend/src/pages/IllustDetail.tsx`
- Test: `frontend/src/pages/IllustDetail.test.tsx`（新建）

- [ ] **Step 1: 写失败的测试**

```tsx
// frontend/src/pages/IllustDetail.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SelectionProvider, useSelection } from "../contexts/SelectionContext";
import IllustDetail from "./IllustDetail";

const DETAIL = {
  pid: 42,
  index: 1,
  title: "作品",
  description: "",
  author_id: 7,
  author_name: "画师",
  author_account: "acct",
  page_count: 1,
  type: "illust",
  x_restrict: 0,
  sanity_level: 0,
  width: 100,
  height: 100,
  create_date: null,
  total_view: 0,
  total_bookmarks: 0,
  state: "active",
  has_original: true,
  page_downloaded_count: 1,
  tags: [],
  translated_tags: [],
  pages: [{ page_index: 0, download_state: "done", ext: ".jpg" }],
  restrict: "public",
  bookmark_state: "active",
  rank: 0,
  pixiv_url: "https://www.pixiv.net/artworks/42",
  animation_available: false,
  frame_count: null,
  unbookmarked: false,
};

function Probe() {
  const selection = useSelection();
  return <span data-testid="probe">{selection.count}</span>;
}

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/illust/42"]}>
          <SelectionProvider>
            <Routes>
              <Route path="/illust/:pid" element={children} />
            </Routes>
            <Probe />
          </SelectionProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
  };
}

afterEach(() => vi.restoreAllMocks());

function mockDetail() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(DETAIL), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
}

describe("IllustDetail", () => {
  it("adds and removes the work from the selection", async () => {
    mockDetail();
    render(<IllustDetail />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("作品")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "加入选择" }));
    expect(screen.getByTestId("probe")).toHaveTextContent("1");

    await userEvent.click(screen.getByRole("button", { name: "移出选择" }));
    expect(screen.getByTestId("probe")).toHaveTextContent("0");
  });

  it("links the author with author_id parameter", async () => {
    mockDetail();
    render(<IllustDetail />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("画师")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "画师" })).toHaveAttribute(
      "href",
      "/?author_id=7",
    );
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run（在 `frontend/`）: `npm test -- src/pages/IllustDetail.test.tsx`
Expected: FAIL（无"加入选择"按钮；作者链接为 `/?author=7`）

- [ ] **Step 3: 实现**

`frontend/src/pages/IllustDetail.tsx` 修改三处：

1. import 增加：

```tsx
import { useSelection } from "../contexts/SelectionContext";
```

2. 组件内增加：

```tsx
  const selection = useSelection();
  const isSelected = data ? selection.selected.has(data.pid) : false;
```

3. 作者链接改为：

```tsx
            <Link
              to={`/?author_id=${data.author_id}`}
              className="hover:text-text-primary"
            >
              {data.author_name}
            </Link>
```

4. 在"下载缺失的 N 页"按钮之前插入选择按钮：

```tsx
          <button
            type="button"
            onClick={() => selection.toggle(data.pid)}
            className="rounded-md border border-border-subtle px-3 py-2 text-sm hover:border-accent"
          >
            {isSelected ? "移出选择" : "加入选择"}
          </button>
```

- [ ] **Step 4: 运行测试确认通过**

Run（在 `frontend/`）: `npm test -- src/pages/IllustDetail.test.tsx`
Expected: 全部通过

- [ ] **Step 5: 全量前端验证与构建**

Run（在 `frontend/`）: `npm run lint; npm run typecheck; npm test; npm run build`
Expected: 全部通过；`npm run build` 更新 `src/pixiv_archive/web/static/`

- [ ] **Step 6: Commit**

```bash
git add -A frontend/src src/pixiv_archive/web/static
git commit -m "feat(web): select works from the detail page and fix author links"
```

---

### Task 12: GalleryCard 缩略图回退

**Files:**
- Modify: `frontend/src/components/GalleryCard.tsx`
- Test: `frontend/src/components/GalleryCard.test.tsx`（追加用例）

- [ ] **Step 1: 追加失败测试**

在 `frontend/src/components/GalleryCard.test.tsx` 末尾追加：

```tsx
  it("falls back to an inline placeholder when the thumbnail fails", () => {
    renderCard(ITEM);
    const image = screen.getByRole("img");
    fireEvent.error(image);
    expect(image.dataset.fallback).toBe("true");
    expect(image).toHaveAttribute("src", expect.stringContaining("data:image/svg+xml"));
  });
```

并在文件顶部补 import：

```tsx
import { fireEvent } from "@testing-library/react";
```

- [ ] **Step 2: 运行测试确认失败**

Run（在 `frontend/`）: `npm test -- src/components/GalleryCard.test.tsx`
Expected: FAIL（无 `data-fallback`）

- [ ] **Step 3: 实现**

`frontend/src/components/GalleryCard.tsx` 中 `img` 替换为：

```tsx
        <img
          src={item.thumb_url}
          alt={item.title}
          loading="lazy"
          data-fallback="false"
          onError={(event) => {
            const image = event.currentTarget;
            if (image.dataset.fallback === "true") return;
            image.dataset.fallback = "true";
            image.src =
              "data:image/svg+xml;utf8," +
              encodeURIComponent(
                '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400">' +
                  '<rect width="100%" height="100%" fill="#1d2531"/>' +
                  '<text x="50%" y="50%" fill="#9aa4b2" font-family="sans-serif" ' +
                  'font-size="16" text-anchor="middle">图片不可用</text></svg>',
              );
          }}
          className="w-full bg-surface object-cover transition-opacity group-hover:opacity-90"
        />
```

**注意：** 用 data URI 而不是 `frontend/public/placeholder.svg`，因为 FastAPI 的 SPA 兜底路由会把任何非 `/assets` 路径都返回 `index.html`，`public/` 下的文件在静态托管时拿不到。data URI 无服务器依赖，测试也可直接断言。

- [ ] **Step 4: 运行测试确认通过**

Run（在 `frontend/`）: `npm test -- src/components/GalleryCard.test.tsx`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/GalleryCard.tsx frontend/src/components/GalleryCard.test.tsx
git commit -m "feat(web): fall back when a gallery thumbnail fails to load"
```

---

### Task 13: 后端全量验证与文档更新

**Files:**
- Modify: `README.md`（接口表：画廊筛选参数、下载 filter 范围）
- Modify: `AGENTS.md`（如涉及命令或架构说明的变更）

- [ ] **Step 1: 跑完整后端校验**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy && uv run pytest -q`
Expected: 全部通过

- [ ] **Step 2: 更新 README 接口表**

在 `README.md` 的"主要接口"表中，把 `GET /api/gallery` 行替换为：

```markdown
| GET | `/api/gallery` | 画廊（排序 / 搜索 / 多标签 AND / 多作者 / 页数 / 收藏数 / 浏览数 / 状态 / 分页，含显示序号；`tag` 与 `author_id` 可重复） |
```

把 `POST /api/downloads` 行替换为：

```markdown
| POST | `/api/downloads` | 触发阶段 B（scope: all_missing/author/selected/rank-range/filter；filter 支持与画廊相同的筛选字段） |
```

- [ ] **Step 3: 更新 AGENTS.md 架构说明**

在 `AGENTS.md` 的 Architecture 列表中，`sync/` 之后新增一行：

```markdown
- `db/query.py` = gallery/download/export 共用的 illust 筛选核心（`IllustFilters` + `build_illust_query`）；`web/gallery_query.py` 只负责排序与显示序号窗口。
```

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: document gallery filter and download scope changes"
```
