# 计划 4a：Web API（FastAPI 路由 + SSE + 认证）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现完整的 FastAPI 后端：单用户认证、画廊查询（分页/排序/过滤/搜索）、作品详情与文件服务（原图/Range/缩略图/动图）、同步与下载任务触发、SSE 实时进度、统计与导出。

**Architecture:** `web/` 包按职责拆分：`auth.py`（token 登录 + 签名 cookie session）、`schemas.py`（响应模型）、`deps.py`（依赖注入：settings/db/服务）、`routers/`（gallery / illust / tasks / stats / export / auth）、`sse.py`（进程内事件总线 + 事件流）、`app.py`（装配 + 后台任务管理器 + 静态文件）。图像文件服务直接读本地磁盘，支持 ETag 与 Range（视频拖动所需）。同步与下载在后台任务中执行，通过事件总线推送到 SSE。

**Tech Stack:** FastAPI、uvicorn、SQLAlchemy 2.x async、itsdangerous（cookie 签名）、Pillow、pytest + httpx ASGITransport

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `src/pixiv_archive/web/auth.py` | 登录/登出、session cookie 签名与校验依赖 |
| `src/pixiv_archive/web/schemas.py` | 所有响应/请求的 pydantic 模型 |
| `src/pixiv_archive/web/deps.py` | `get_settings` / `get_db` / `require_auth` 等依赖 |
| `src/pixiv_archive/web/gallery_query.py` | 画廊查询构建（排序/过滤/搜索/序号计算） |
| `src/pixiv_archive/web/files.py` | 文件响应（ETag、Range、Content-Type、占位图） |
| `src/pixiv_archive/web/sse.py` | `EventBus`（进程内发布订阅）与 SSE 响应 |
| `src/pixiv_archive/web/tasks.py` | `TaskManager`：后台执行 sync/download/export，广播进度 |
| `src/pixiv_archive/web/routers/__init__.py` | 路由聚合 |
| `src/pixiv_archive/web/routers/auth.py` | `/api/auth/*` |
| `src/pixiv_archive/web/routers/gallery.py` | `/api/gallery`、`/api/authors`、`/api/tags` |
| `src/pixiv_archive/web/routers/illust.py` | `/api/illust/{pid}` 与文件端点 |
| `src/pixiv_archive/web/routers/tasks.py` | `/api/sync`、`/api/downloads`、`/api/tasks`、`/api/events`(SSE) |
| `src/pixiv_archive/web/routers/stats.py` | `/api/stats` |
| `src/pixiv_archive/web/routers/export.py` | `/api/export` + 下载 |
| `src/pixiv_archive/web/app.py` | 装配（含静态文件挂载与 lifespan） |
| `tests/test_web_auth.py` 等 | 测试 |

---

### Task 1: 认证与 session

**Files:**
- Create: `src/pixiv_archive/web/auth.py`
- Create: `src/pixiv_archive/web/schemas.py`
- Create: `src/pixiv_archive/web/deps.py`
- Modify: `src/pixiv_archive/config.py`（追加 `session_secret`）
- Test: `tests/test_web_auth.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_web_auth.py`：

```python
import httpx
import pytest
from fastapi import FastAPI

from pixiv_archive.config import Settings
from pixiv_archive.web.auth import SessionSigner, require_auth
from pixiv_archive.web.deps import get_settings


@pytest.fixture
def signer(tmp_path):
    return SessionSigner("test-secret", max_age_seconds=60)


def test_signer_roundtrip(signer):
    token = signer.sign("ok")
    assert signer.verify(token) is True


def test_signer_rejects_tampered_token(signer):
    token = signer.sign("ok")
    assert signer.verify(token + "x") is False
    assert signer.verify("garbage") is False


def test_signer_rejects_expired(monkeypatch):
    signer = SessionSigner("test-secret", max_age_seconds=-1)
    token = signer.sign("ok")
    assert signer.verify(token) is False


def _make_app(signer: SessionSigner) -> FastAPI:
    app = FastAPI()

    @app.get("/protected")
    async def protected(_: str = pytest.importorskip("fastapi").Depends(require_auth)):
        return {"ok": True}

    app.state.session_signer = signer
    return app


async def test_require_auth_rejects_without_cookie(signer):
    app = _make_app(signer)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/protected")).status_code == 401


async def test_require_auth_accepts_valid_cookie(signer):
    app = _make_app(signer)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        client.cookies.set("session", signer.sign("ok"))
        assert (await client.get("/protected")).status_code == 200


async def test_require_auth_rejects_invalid_cookie(signer):
    app = _make_app(signer)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        client.cookies.set("session", "bad")
        assert (await client.get("/protected")).status_code == 401


def test_session_secret_generated_when_missing(tmp_path):
    settings = Settings(
        _env_file=None,
        PIXIV_REFRESH_TOKEN="t",
        PIXIV_USER_ID=1,
        DATA_DIR=tmp_path,
    )
    secret = settings.session_secret
    assert secret
    assert (tmp_path / "session.secret").exists()
    # stable across reads
    again = Settings(
        _env_file=None, PIXIV_REFRESH_TOKEN="t", PIXIV_USER_ID=1, DATA_DIR=tmp_path
    )
    assert again.session_secret == secret
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.web.auth'`

- [ ] **Step 3: 实现 config 扩展、auth、schemas、deps**

在 `src/pixiv_archive/config.py` 中追加属性（`Settings` 类内，放在 `logs_dir` 之前）：

```python
    @property
    def session_secret(self) -> str:
        """Persistent session signing key, generated on first use."""
        from secrets import token_urlsafe

        secret_file = self.data_dir / "session.secret"
        if secret_file.exists():
            value = secret_file.read_text("utf-8").strip()
            if value:
                return value
        self.data_dir.mkdir(parents=True, exist_ok=True)
        value = token_urlsafe(48)
        secret_file.write_text(value, encoding="utf-8")
        return value
```

`src/pixiv_archive/web/auth.py`：

```python
from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SESSION_COOKIE = "session"
_TOKEN_SALT = "pixiv-archive-session"
_DEFAULT_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


class SessionSigner:
    """Signs and verifies session cookies with a persistent secret."""

    def __init__(self, secret: str, *, max_age_seconds: int = _DEFAULT_MAX_AGE) -> None:
        self._serializer = URLSafeTimedSerializer(secret, salt=_TOKEN_SALT)
        self._max_age = max_age_seconds

    def sign(self, value: str) -> str:
        return self._serializer.dumps(value)

    def verify(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            self._serializer.loads(token, max_age=self._max_age)
        except (BadSignature, SignatureExpired):
            return False
        return True


def get_signer(request: Request) -> SessionSigner:
    signer = getattr(request.app.state, "session_signer", None)
    if signer is None:
        raise HTTPException(status_code=500, detail="session signer not configured")
    return signer


async def require_auth(request: Request, signer: SessionSigner = Depends(get_signer)) -> str:
    """Dependency that rejects unauthenticated requests with 401."""
    token = request.cookies.get(SESSION_COOKIE)
    if not signer.verify(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return "ok"


def set_session_cookie(response: Response, signer: SessionSigner) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        signer.sign("ok"),
        httponly=True,
        samesite="lax",
        max_age=_DEFAULT_MAX_AGE,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
```

`src/pixiv_archive/web/schemas.py`：

```python
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    token: str


class MeResponse(BaseModel):
    authenticated: bool


class GalleryItem(BaseModel):
    pid: int
    index: int  # display sequence number (1-based, by rank among active)
    title: str
    author_id: int
    author_name: str
    page_count: int
    type: str
    x_restrict: int
    width: int
    height: int
    create_date: datetime | None
    rank: int
    has_original: bool
    page_downloaded_count: int
    preview_url: str
    thumb_url: str
    restrict: str
    unbookmarked: bool


class GalleryResponse(BaseModel):
    items: list[GalleryItem]
    total: int
    offset: int
    limit: int


class IllustPageOut(BaseModel):
    page_index: int
    download_state: str
    ext: str
    width: int | None = None
    height: int | None = None


class IllustDetailOut(BaseModel):
    pid: int
    index: int
    title: str
    description: str
    author_id: int
    author_name: str
    author_account: str
    page_count: int
    type: str
    x_restrict: int
    sanity_level: int
    width: int
    height: int
    create_date: datetime | None
    total_view: int
    total_bookmarks: int
    state: str
    has_original: bool
    page_downloaded_count: int
    tags: list[str]
    translated_tags: list[str]
    pages: list[IllustPageOut]
    restrict: str
    bookmark_state: str
    rank: int | None
    pixiv_url: str
    animation_available: bool
    frame_count: int | None
    unbookmarked: bool


class AuthorOut(BaseModel):
    id: int
    name: str
    account: str
    illust_count: int


class TagOut(BaseModel):
    name: str
    translated_name: str | None
    illust_count: int


class SyncRequest(BaseModel):
    mode: str = "incremental"


class DownloadRequest(BaseModel):
    scope: str = "all_missing"
    pids: list[int] = Field(default_factory=list)
    author_id: int | None = None
    start: int | None = None
    count: int | None = None
    x_restrict: int | None = None
    type: str | None = None
    with_thumbs: bool = True


class TaskOut(BaseModel):
    id: str
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


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


class ExportRequest(BaseModel):
    include_metadata: bool = True
    include_originals: bool = False
    pids: list[int] = Field(default_factory=list)
    x_restrict: int | None = None
    only_downloaded: bool = False


class ExportOut(BaseModel):
    task_id: str
    filename: str


class EventOut(BaseModel):
    type: str
    payload: dict[str, Any]
```

`src/pixiv_archive/web/deps.py`：

```python
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.config import Settings
from pixiv_archive.db.engine import Database


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_database(request: Request) -> Database:
    return request.app.state.db


def get_tasks(request: Request):
    return request.app.state.tasks


def get_events(request: Request):
    return request.app.state.events


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.db
    async with database.session() as session:
        yield session
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_auth.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/config.py src/pixiv_archive/web tests/test_web_auth.py
git commit -m "feat: add session auth, schemas and web dependencies"
```

---

### Task 2: 画廊查询

**Files:**
- Create: `src/pixiv_archive/web/gallery_query.py`
- Test: `tests/test_web_gallery_query.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_web_gallery_query.py`：

```python
from datetime import UTC, datetime

import pytest

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust, IllustTag, Tag
from pixiv_archive.web.gallery_query import GalleryFilters, query_gallery


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "gq.db")
    await database.create_all()
    yield database
    await database.dispose()


async def _seed(db, pid: int, *, rank: int, author=1, type_="illust", x=0,
                state="active", bm_state="active", tags=(), has_original=False) -> None:
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
                has_original=has_original,
                page_count=1,
                create_date=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()
    async with db.session() as session:
        session.add(Bookmark(pid=pid, restrict="public", rank=rank, state=bm_state))
        for name in tags:
            tag = Tag(name=name)
            session.add(tag)
            await session.flush()
            session.add(IllustTag(pid=pid, tag_id=tag.id, position=0))
        await session.commit()


async def test_query_returns_items_in_rank_order_with_index(db):
    await _seed(db, 1, rank=100)
    await _seed(db, 2, rank=0)
    await _seed(db, 3, rank=200)
    async with db.session() as session:
        result = await query_gallery(session, GalleryFilters(), offset=0, limit=10)
    assert [item.pid for item in result.items] == [2, 1, 3]
    assert [item.index for item in result.items] == [1, 2, 3]
    assert result.total == 3


async def test_query_pagination_keeps_absolute_index(db):
    for i, pid in enumerate([10, 20, 30, 40, 50]):
        await _seed(db, pid, rank=i * 1024)
    async with db.session() as session:
        page = await query_gallery(session, GalleryFilters(), offset=2, limit=2)
    assert [item.pid for item in page.items] == [30, 40]
    assert [item.index for item in page.items] == [3, 4]


async def test_query_sorts_by_create_date_and_bookmarks(db):
    await _seed(db, 1, rank=0)
    await _seed(db, 2, rank=10)
    async with db.session() as session:
        newest = await query_gallery(
            session, GalleryFilters(sort="create_date"), offset=0, limit=10
        )
    assert newest.total == 2

    async with db.session() as session:
        popular = await query_gallery(
            session, GalleryFilters(sort="bookmarks"), offset=0, limit=10
        )
    assert len(popular.items) == 2


async def test_query_filters_by_x_restrict_and_type(db):
    await _seed(db, 1, rank=0, x=0, type_="illust")
    await _seed(db, 2, rank=10, x=1, type_="ugoira")
    async with db.session() as session:
        result = await query_gallery(
            session, GalleryFilters(x_restrict=1, type="ugoira"), offset=0, limit=10
        )
    assert [item.pid for item in result.items] == [2]


async def test_query_filters_download_state(db):
    await _seed(db, 1, rank=0, has_original=True)
    await _seed(db, 2, rank=10, has_original=False)
    async with db.session() as session:
        downloaded = await query_gallery(
            session, GalleryFilters(downloaded=True), offset=0, limit=10
        )
        pending = await query_gallery(
            session, GalleryFilters(downloaded=False), offset=0, limit=10
        )
    assert [item.pid for item in downloaded.items] == [1]
    assert [item.pid for item in pending.items] == [2]


async def test_query_filters_by_author_and_tag(db):
    await _seed(db, 1, rank=0, author=5, tags=("猫",))
    await _seed(db, 2, rank=10, author=6, tags=("犬",))
    async with db.session() as session:
        by_author = await query_gallery(
            session, GalleryFilters(author_id=5), offset=0, limit=10
        )
        by_tag = await query_gallery(session, GalleryFilters(tag="犬"), offset=0, limit=10)
    assert [item.pid for item in by_author.items] == [1]
    assert [item.pid for item in by_tag.items] == [2]


async def test_query_search_matches_title_and_author_name(db):
    await _seed(db, 777, rank=0)
    async with db.session() as session:
        by_title = await query_gallery(session, GalleryFilters(q="777"), offset=0, limit=10)
        by_author = await query_gallery(
            session, GalleryFilters(q="author1"), offset=0, limit=10
        )
    assert [item.pid for item in by_title.items] == [777]
    assert [item.pid for item in by_author.items] == [777]


async def test_query_unbookmarked_scope(db):
    await _seed(db, 1, rank=0, bm_state="unbookmarked")
    await _seed(db, 2, rank=10)
    async with db.session() as session:
        default = await query_gallery(session, GalleryFilters(), offset=0, limit=10)
        unbookmarked = await query_gallery(
            session, GalleryFilters(include_unbookmarked=True, only_unbookmarked=True),
            offset=0, limit=10,
        )
    assert [item.pid for item in default.items] == [2]
    assert [item.pid for item in unbookmarked.items] == [1]


async def test_query_excludes_deleted_illusts(db):
    await _seed(db, 1, rank=0, state="deleted")
    await _seed(db, 2, rank=10)
    async with db.session() as session:
        result = await query_gallery(session, GalleryFilters(), offset=0, limit=10)
    assert [item.pid for item in result.items] == [2]


async def test_query_rank_range(db):
    for i, pid in enumerate([10, 20, 30]):
        await _seed(db, pid, rank=i * 1024)
    async with db.session() as session:
        result = await query_gallery(
            session, GalleryFilters(rank_start=1, rank_count=1), offset=0, limit=10
        )
    assert [item.pid for item in result.items] == [20]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_gallery_query.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.web.gallery_query'`

- [ ] **Step 3: 实现 gallery_query.py**

`src/pixiv_archive/web/gallery_query.py`：

```python
from dataclasses import dataclass

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Author, Bookmark, Illust, IllustTag, Tag
from pixiv_archive.web.schemas import GalleryItem, GalleryResponse

_SORTS = {
    "rank": (Bookmark.rank.asc(),),
    "create_date": (Illust.create_date.desc(), Bookmark.rank.asc()),
    "bookmarks": (Illust.total_bookmarks.desc(), Bookmark.rank.asc()),
    "views": (Illust.total_view.desc(), Bookmark.rank.asc()),
}


@dataclass
class GalleryFilters:
    sort: str = "rank"
    include_unbookmarked: bool = False
    only_unbookmarked: bool = False
    author_id: int | None = None
    tag: str | None = None
    q: str | None = None
    type: str | None = None
    x_restrict: int | None = None
    downloaded: bool | None = None
    rank_start: int | None = None
    rank_count: int | None = None
    restrict: str | None = None


def _base_conditions(filters: GalleryFilters) -> list:
    conditions = [Illust.state == "active"]
    if filters.only_unbookmarked:
        conditions.append(Bookmark.state == "unbookmarked")
    elif not filters.include_unbookmarked:
        conditions.append(Bookmark.state == "active")
    if filters.author_id is not None:
        conditions.append(Illust.author_id == filters.author_id)
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
        conditions.append(
            or_(Illust.title.like(pattern), Author.name.like(pattern))
        )
    return conditions


def _apply_rank_range(stmt: Select, filters: GalleryFilters) -> Select:
    if filters.rank_start is None and filters.rank_count is None:
        return stmt
    ranked = stmt
    if filters.rank_count is not None:
        ranked = ranked.limit(filters.rank_count)
    if filters.rank_start:
        ranked = ranked.offset(filters.rank_start)
    return ranked


def _build_base_select(filters: GalleryFilters) -> Select:
    stmt = (
        select(Illust, Bookmark, Author)
        .join(Bookmark, Bookmark.pid == Illust.pid)
        .join(Author, Author.id == Illust.author_id)
        .where(and_(*_base_conditions(filters)))
    )
    if filters.tag:
        stmt = stmt.join(IllustTag, IllustTag.pid == Illust.pid).join(
            Tag, Tag.id == IllustTag.tag_id
        ).where(Tag.name == filters.tag)
    return _apply_rank_range(stmt, filters)


def _order(stmt: Select, filters: GalleryFilters) -> Select:
    order = _SORTS.get(filters.sort, _SORTS["rank"])
    return stmt.order_by(*order)


def _rank_of(session: AsyncSession, pid: int, filters: GalleryFilters) -> int:
    """Compute the 1-based display index of a pid within the filtered set."""
    inner = _order(_build_base_select(filters), filters).subquery()
    row = session.execute(
        select(func.count()).select_from(inner).where(inner.c.pid < pid)
    )
    return row


async def query_gallery(
    session: AsyncSession, filters: GalleryFilters, *, offset: int, limit: int
) -> GalleryResponse:
    """Run the filtered/sorted query and compute absolute display indexes."""
    base = _build_base_select(filters)
    total = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    rows = (
        await session.execute(_order(base, filters).offset(offset).limit(limit))
    ).all()

    # 1-based index within the whole filtered set: offset + position, but the
    # displayed number must reflect the chosen sort; for the default rank sort
    # this equals the absolute rank position.
    ordered_pids = (
        await session.execute(_order(_build_base_select(filters), filters))
    ).scalars().all()
    position = {pid: i + 1 for i, pid in enumerate(ordered_pids)}

    items = [
        GalleryItem(
            pid=illust.pid,
            index=position.get(illust.pid, 0),
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
        )
        for illust, bookmark, author in rows
    ]
    return GalleryResponse(items=items, total=total, offset=offset, limit=limit)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_gallery_query.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/web/gallery_query.py tests/test_web_gallery_query.py
git commit -m "feat: add gallery query with filters, sorting and display index"
```

---

### Task 3: 文件服务（原图 / Range / 缩略图 / 占位图）

**Files:**
- Create: `src/pixiv_archive/web/files.py`
- Test: `tests/test_web_files.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_web_files.py`：

```python
from pathlib import Path

import pytest

from pixiv_archive.web.files import (
    build_etag,
    file_not_modified,
    parse_range,
    placeholder_svg,
    resolve_thumb,
)

CONTENT = b"0123456789"


def test_parse_range_returns_bounds():
    assert parse_range("bytes=0-4", 10) == (0, 4)
    assert parse_range("bytes=5-", 10) == (5, 9)
    assert parse_range("bytes=-3", 10) == (7, 9)


def test_parse_range_rejects_invalid():
    assert parse_range(None, 10) is None
    assert parse_range("bytes=abc", 10) is None
    assert parse_range("items=0-1", 10) is None
    assert parse_range("bytes=20-30", 10) is None
    assert parse_range("bytes=5-2", 10) is None


def test_build_etag_is_stable(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(CONTENT)
    a = build_etag(path)
    b = build_etag(path)
    assert a == b
    assert a.startswith('"')


def test_file_not_modified():
    etag = '"abc"'
    assert file_not_modified(etag, etag) is True
    assert file_not_modified('"other"', etag) is False
    assert file_not_modified(None, etag) is False


def test_resolve_thumb_prefers_webp(tmp_path):
    root = tmp_path
    work = root / "1"
    (work / "original").mkdir(parents=True)
    assert resolve_thumb(root, 1) is None
    (work / "preview.jpg").write_bytes(CONTENT)
    assert resolve_thumb(root, 1) == work / "preview.jpg"
    (work / "thumb.webp").write_bytes(CONTENT)
    assert resolve_thumb(root, 1) == work / "thumb.webp"


def test_placeholder_svg_for_missing(tmp_path):
    svg = placeholder_svg(1)
    assert "<svg" in svg
    assert "1" in svg
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_files.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.web.files'`

- [ ] **Step 3: 实现 files.py**

`src/pixiv_archive/web/files.py`：

```python
import hashlib
from pathlib import Path

from fastapi import HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse

CHUNK_SIZE = 256 * 1024

_EXT_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".zip": "application/zip",
    ".json": "application/json",
}


def content_type_for(path: Path) -> str:
    return _EXT_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Parse a single-range ``bytes=`` header into inclusive bounds."""
    if not header or not header.startswith("bytes="):
        return None
    spec = header[len("bytes=") :].strip()
    if "," in spec:
        return None
    if "-" not in spec:
        return None
    start_text, _, end_text = spec.partition("-")
    try:
        if start_text == "":
            length = int(end_text)
            if length <= 0:
                return None
            start = max(0, size - length)
            end = size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
    except ValueError:
        return None
    if start < 0 or start >= size or end < start:
        return None
    return start, min(end, size - 1)


def build_etag(path: Path) -> str:
    stat = path.stat()
    signature = f"{stat.st_mtime_ns:x}-{stat.st_size:x}"
    digest = hashlib.sha1(signature.encode()).hexdigest()[:16]
    return f'"{digest}"'


def file_not_modified(if_none_match: str | None, etag: str) -> bool:
    return bool(if_none_match) and if_none_match == etag


def resolve_thumb(works_root: Path, pid: int) -> Path | None:
    """Prefer the locally generated thumbnail, then pixiv's preview image."""
    work = works_root / str(pid)
    for candidate in (work / "thumb.webp", work / "preview.jpg"):
        if candidate.is_file():
            return candidate
    return None


def placeholder_svg(pid: int) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400">'
        '<rect width="100%" height="100%" fill="#1f2937"/>'
        f'<text x="50%" y="50%" fill="#6b7280" font-family="sans-serif" '
        f'font-size="20" text-anchor="middle">#{pid}</text></svg>'
    )


def placeholder_response(pid: int) -> Response:
    return Response(content=placeholder_svg(pid), media_type="image/svg+xml")


def file_response(request: Request, path: Path, *, download_name: str | None = None) -> Response:
    """Serve a local file with ETag and optional Range support."""
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    etag = build_etag(path)
    if file_not_modified(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers={"ETag": etag})

    size = path.stat().st_size
    content_type = content_type_for(path)
    headers = {"ETag": etag, "Accept-Ranges": "bytes"}

    if download_name:
        headers["Content-Disposition"] = f'attachment; filename="{download_name}"'

    range_header = request.headers.get("range")
    bounds = parse_range(range_header, size)
    if bounds is None:
        return FileResponse(path, media_type=content_type, headers=headers)

    start, end = bounds
    length = end - start + 1

    def _iter() -> "Response | None":
        with open(path, "rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    range_headers = dict(headers)
    range_headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    range_headers["Content-Length"] = str(length)
    return StreamingResponse(
        _iter(), status_code=206, media_type=content_type, headers=range_headers
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_files.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/web/files.py tests/test_web_files.py
git commit -m "feat: add file serving with etag range and placeholder"
```

---

### Task 4: 事件总线与任务管理器

**Files:**
- Create: `src/pixiv_archive/web/sse.py`
- Create: `src/pixiv_archive/web/tasks.py`
- Test: `tests/test_web_tasks.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_web_tasks.py`：

```python
import asyncio
from datetime import UTC, datetime

import pytest

from pixiv_archive.web.sse import EventBus, format_sse
from pixiv_archive.web.tasks import TaskManager, TaskRecord


def test_format_sse_shape():
    text = format_sse("progress", {"done": 1})
    assert text.startswith("event: progress\n")
    assert "data: {\"done\": 1}" in text
    assert text.endswith("\n\n")


async def test_event_bus_publishes_to_subscribers():
    bus = EventBus()
    queue = bus.subscribe()
    bus.publish("progress", {"done": 1})
    event = await asyncio.wait_for(queue.get(), timeout=1)
    assert event["type"] == "progress"
    assert event["payload"] == {"done": 1}
    bus.unsubscribe(queue)


async def test_event_bus_keeps_recent_history():
    bus = EventBus(history=3)
    for i in range(5):
        bus.publish("progress", {"i": i})
    recent = bus.recent()
    assert [e["payload"]["i"] for e in recent] == [2, 3, 4]


async def test_event_bus_subscriber_receives_backlog():
    bus = EventBus(history=2)
    bus.publish("a", {"n": 1})
    bus.publish("b", {"n": 2})
    queue = bus.subscribe(replay=True)
    first = await asyncio.wait_for(queue.get(), timeout=1)
    second = await asyncio.wait_for(queue.get(), timeout=1)
    assert first["type"] == "a"
    assert second["type"] == "b"
    bus.unsubscribe(queue)


async def test_task_manager_records_lifecycle():
    manager = TaskManager()

    async def job(ctx) -> dict:
        ctx.progress("working", 1, 2, "halfway")
        return {"done": 2}

    task_id = manager.start("sync", job)
    await manager.wait(task_id)
    record = manager.get(task_id)
    assert record is not None
    assert record.status == "completed"
    assert record.detail == {"done": 2}
    assert record.finished_at is not None
    events = [e for e in manager.events.recent() if e["type"] == "task"]
    assert any(e["payload"]["task_id"] == task_id for e in events)


async def test_task_manager_records_failure():
    manager = TaskManager()

    async def job(ctx) -> dict:
        raise RuntimeError("boom")

    task_id = manager.start("sync", job)
    await manager.wait(task_id)
    record = manager.get(task_id)
    assert record is not None
    assert record.status == "failed"
    assert "boom" in (record.error or "")


async def test_task_manager_lists_active_tasks():
    manager = TaskManager()
    release = asyncio.Event()

    async def job(ctx) -> dict:
        await release.wait()
        return {}

    task_id = manager.start("download", job)
    await asyncio.sleep(0)
    assert task_id in [t.id for t in manager.list_active()]
    release.set()
    await manager.wait(task_id)
    assert task_id not in [t.id for t in manager.list_active()]


async def test_task_manager_rejects_duplicate_kind():
    manager = TaskManager()
    release = asyncio.Event()

    async def job(ctx) -> dict:
        await release.wait()
        return {}

    first = manager.start("sync", job)
    with pytest.raises(RuntimeError):
        manager.start("sync", job)
    release.set()
    await manager.wait(first)


def test_task_record_serialization():
    record = TaskRecord(
        id="abc",
        kind="sync",
        status="running",
        started_at=datetime.now(UTC),
    )
    payload = record.to_dict()
    assert payload["id"] == "abc"
    assert payload["finished_at"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_tasks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.web.sse'`

- [ ] **Step 3: 实现 sse.py 与 tasks.py**

`src/pixiv_archive/web/sse.py`：

```python
import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

_STREAM_END = "__stream_end__"


def format_sse(event_type: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_type}\ndata: {data}\n\n"


class EventBus:
    """In-process fan-out for progress events with a small replay buffer."""

    def __init__(self, history: int = 200) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=history)

    def subscribe(self, *, replay: bool = False) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        if replay:
            for event in list(self._history):
                queue.put_nowait(event)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {"type": event_type, "payload": payload}
        self._history.append(event)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def recent(self, limit: int | None = None) -> list[dict[str, Any]]:
        events = list(self._history)
        return events[-limit:] if limit else events


async def event_stream(
    bus: EventBus, queue: asyncio.Queue[dict[str, Any]], *, keepalive: float = 15.0
) -> AsyncIterator[str]:
    """Yield SSE frames forever, emitting comments as keepalives."""
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=keepalive)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            if event.get("type") == _STREAM_END:
                break
            yield format_sse(event["type"], event["payload"])
    finally:
        bus.unsubscribe(queue)
```

`src/pixiv_archive/web/tasks.py`：

```python
import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pixiv_archive.db.models import utcnow
from pixiv_archive.web.sse import EventBus

logger = logging.getLogger(__name__)


@dataclass
class TaskRecord:
    id: str
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "detail": self.detail,
            "error": self.error,
        }


class TaskContext:
    """Passed to task callables to report progress and cancellation."""

    def __init__(self, record: TaskRecord, bus: EventBus) -> None:
        self.record = record
        self._bus = bus
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def progress(self, phase: str, done: int, total: int, message: str) -> None:
        if self._cancelled:
            raise asyncio.CancelledError
        self._broadcast(phase=phase, done=done, total=total, message=message)

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self._bus.publish(
            event_type, {"task_id": self.record.id, "kind": self.record.kind, **payload}
        )

    def _broadcast(self, **payload: Any) -> None:
        self._bus.publish(
            "progress", {"task_id": self.record.id, "kind": self.record.kind, **payload}
        )


TaskFn = Callable[[TaskContext], Awaitable[dict[str, Any]]]


class TaskManager:
    """Runs background tasks, enforcing one active task per kind."""

    def __init__(self, events: EventBus | None = None) -> None:
        self.events = events or EventBus()
        self._records: dict[str, TaskRecord] = {}
        self._contexts: dict[str, TaskContext] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._done: dict[str, asyncio.Event] = {}

    def start(self, kind: str, fn: TaskFn) -> str:
        if any(record.kind == kind and record.status == "running" for record in self._records.values()):
            raise RuntimeError(f"a {kind} task is already running")
        task_id = uuid.uuid4().hex[:12]
        record = TaskRecord(id=task_id, kind=kind, status="running", started_at=utcnow())
        context = TaskContext(record, self.events)
        self._records[task_id] = record
        self._contexts[task_id] = context
        self._done[task_id] = asyncio.Event()
        self.events.publish("task", {"task_id": task_id, "kind": kind, "status": "running"})
        self._tasks[task_id] = asyncio.create_task(self._run(task_id, fn, context))
        return task_id

    async def _run(self, task_id: str, fn: TaskFn, context: TaskContext) -> None:
        record = self._records[task_id]
        try:
            detail = await fn(context)
            record.status = "cancelled" if context.cancelled else "completed"
            record.detail = detail or {}
        except asyncio.CancelledError:
            record.status = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001 - surface any failure to the client
            logger.exception("task %s failed", task_id)
            record.status = "failed"
            record.error = str(exc)
        finally:
            record.finished_at = utcnow()
            self.events.publish(
                "task",
                {
                    "task_id": task_id,
                    "kind": record.kind,
                    "status": record.status,
                    "detail": record.detail,
                    "error": record.error,
                },
            )
            self._done[task_id].set()

    def get(self, task_id: str) -> TaskRecord | None:
        return self._records.get(task_id)

    def all(self, limit: int = 50) -> list[TaskRecord]:
        records = sorted(self._records.values(), key=lambda r: r.started_at, reverse=True)
        return records[:limit]

    def list_active(self) -> list[TaskRecord]:
        return [record for record in self._records.values() if record.status == "running"]

    def cancel(self, task_id: str) -> bool:
        context = self._contexts.get(task_id)
        if context is None or context.record.status != "running":
            return False
        context.cancel()
        return True

    async def wait(self, task_id: str) -> None:
        event = self._done.get(task_id)
        if event is not None:
            await event.wait()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_tasks.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/web/sse.py src/pixiv_archive/web/tasks.py tests/test_web_tasks.py
git commit -m "feat: add event bus and background task manager"
```

---

### Task 5: 路由 — 认证与画廊

**Files:**
- Create: `src/pixiv_archive/web/routers/__init__.py`
- Create: `src/pixiv_archive/web/routers/auth.py`
- Create: `src/pixiv_archive/web/routers/gallery.py`
- Test: `tests/test_web_routers_gallery.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_web_routers_gallery.py`：

```python
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust
from pixiv_archive.web.auth import SessionSigner, set_session_cookie
from pixiv_archive.web.routers.auth import router as auth_router
from pixiv_archive.web.routers.gallery import router as gallery_router


@pytest.fixture
async def client(tmp_path):
    database = Database(tmp_path / "api.db")
    await database.create_all()
    async with database.session() as session:
        session.add(Author(id=1, name="画师", account="acct"))
        await session.commit()
    async with database.session() as session:
        session.add(Illust(pid=10, title="作品十", author_id=1, page_count=2))
        session.add(Illust(pid=20, title="作品二十", author_id=1, page_count=1))
        await session.commit()
    async with database.session() as session:
        session.add(Bookmark(pid=10, restrict="public", rank=0, state="active"))
        session.add(Bookmark(pid=20, restrict="public", rank=1024, state="active"))
        await session.commit()

    app = FastAPI()
    signer = SessionSigner("secret")
    app.state.db = database
    app.state.session_signer = signer
    app.include_router(auth_router)
    app.include_router(gallery_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as http:
        http._signer = signer  # type: ignore[attr-defined]
        yield http
    await database.dispose()


def _login(client: AsyncClient, signer: SessionSigner) -> None:
    client.cookies.set("session", signer.sign("ok"))


async def test_gallery_requires_auth(client):
    response = await client.get("/api/gallery")
    assert response.status_code == 401


async def test_gallery_returns_items(client):
    _login(client, client._signer)  # type: ignore[attr-defined]
    response = await client.get("/api/gallery")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert [item["pid"] for item in payload["items"]] == [10, 20]
    assert [item["index"] for item in payload["items"]] == [1, 2]
    assert payload["items"][0]["author_name"] == "画师"


async def test_gallery_filters_and_search(client):
    _login(client, client._signer)  # type: ignore[attr-defined]
    filtered = await client.get("/api/gallery", params={"q": "二十"})
    assert [item["pid"] for item in filtered.json()["items"]] == [20]

    typed = await client.get("/api/gallery", params={"type": "ugoira"})
    assert typed.json()["total"] == 0


async def test_authors_endpoint(client):
    _login(client, client._signer)  # type: ignore[attr-defined]
    response = await client.get("/api/authors")
    assert response.status_code == 200
    authors = response.json()
    assert authors[0]["id"] == 1
    assert authors[0]["illust_count"] == 2


async def test_tags_endpoint(client):
    _login(client, client._signer)  # type: ignore[attr-defined]
    response = await client.get("/api/tags")
    assert response.status_code == 200
    assert response.json() == []


async def test_login_and_logout(client, monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "sesame")
    app_settings = type("S", (), {"auth_token": "sesame"})()
    client._transport.app.state.settings = app_settings  # type: ignore[union-attr]

    bad = await client.post("/api/auth/login", json={"token": "wrong"})
    assert bad.status_code == 401

    ok = await client.post("/api/auth/login", json={"token": "sesame"})
    assert ok.status_code == 200
    assert ok.json()["authenticated"] is True
    assert client.cookies.get("session")

    me = await client.get("/api/auth/me")
    assert me.json()["authenticated"] is True

    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 200
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_routers_gallery.py -v`
Expected: FAIL — `ImportError: cannot import name 'router'`

- [ ] **Step 3: 实现 routers**

`src/pixiv_archive/web/routers/__init__.py`：

```python
from pixiv_archive.web.routers import auth, gallery

__all__ = ["auth", "gallery"]
```

`src/pixiv_archive/web/routers/auth.py`：

```python
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select

from pixiv_archive.db.models import Author, Tag
from pixiv_archive.web.auth import (
    SessionSigner,
    clear_session_cookie,
    get_signer,
    require_auth,
    set_session_cookie,
)
from pixiv_archive.web.deps import get_session, get_settings
from pixiv_archive.web.schemas import AuthorOut, LoginRequest, MeResponse, TagOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=MeResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    signer: SessionSigner = Depends(get_signer),
) -> MeResponse:
    settings = get_settings(request)
    expected = settings.auth_token
    if not expected:
        raise HTTPException(status_code=503, detail="AUTH_TOKEN is not configured")
    if payload.token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    set_session_cookie(response, signer)
    return MeResponse(authenticated=True)


@router.post("/logout", response_model=MeResponse)
async def logout(response: Response, _: str = Depends(require_auth)) -> MeResponse:
    clear_session_cookie(response)
    return MeResponse(authenticated=False)


@router.get("/me", response_model=MeResponse)
async def me(request: Request, signer: SessionSigner = Depends(get_signer)) -> MeResponse:
    token = request.cookies.get("session")
    return MeResponse(authenticated=signer.verify(token))
```

`src/pixiv_archive/web/routers/gallery.py`：

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Author, Bookmark, Illust, IllustTag, Tag
from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_session
from pixiv_archive.web.gallery_query import GalleryFilters, query_gallery
from pixiv_archive.web.schemas import AuthorOut, GalleryResponse, TagOut

router = APIRouter(prefix="/api", tags=["gallery"], dependencies=[Depends(require_auth)])


@router.get("/gallery", response_model=GalleryResponse)
async def gallery(
    session: AsyncSession = Depends(get_session),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=200),
    sort: str = Query(default="rank", pattern="^(rank|create_date|bookmarks|views)$"),
    author_id: int | None = None,
    tag: str | None = None,
    q: str | None = None,
    type: str | None = Query(default=None, pattern="^(illust|ugoira)$"),
    x_restrict: int | None = Query(default=None, ge=0, le=2),
    downloaded: bool | None = None,
    restrict: str | None = Query(default=None, pattern="^(public|private)$"),
    only_unbookmarked: bool = False,
    include_unbookmarked: bool = False,
    rank_start: int | None = Query(default=None, ge=0),
    rank_count: int | None = Query(default=None, ge=1),
) -> GalleryResponse:
    filters = GalleryFilters(
        sort=sort,
        author_id=author_id,
        tag=tag,
        q=q,
        type=type,
        x_restrict=x_restrict,
        downloaded=downloaded,
        restrict=restrict,
        only_unbookmarked=only_unbookmarked,
        include_unbookmarked=include_unbookmarked,
        rank_start=rank_start,
        rank_count=rank_count,
    )
    return await query_gallery(session, filters, offset=offset, limit=limit)


@router.get("/authors", response_model=list[AuthorOut])
async def authors(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[AuthorOut]:
    rows = (
        await session.execute(
            select(Author, func.count(Illust.pid))
            .join(Illust, Illust.author_id == Author.id)
            .group_by(Author.id)
            .order_by(func.count(Illust.pid).desc(), Author.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [
        AuthorOut(id=author.id, name=author.name, account=author.account, illust_count=count)
        for author, count in rows
    ]


@router.get("/tags", response_model=list[TagOut])
async def tags(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> list[TagOut]:
    rows = (
        await session.execute(
            select(Tag, func.count(IllustTag.pid))
            .join(IllustTag, IllustTag.tag_id == Tag.id)
            .group_by(Tag.id)
            .order_by(func.count(IllustTag.pid).desc(), Tag.name)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [
        TagOut(name=tag.name, translated_name=tag.translated_name, illust_count=count)
        for tag, count in rows
    ]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_routers_gallery.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/web/routers tests/test_web_routers_gallery.py
git commit -m "feat: add auth and gallery routers"
```

---

### Task 6: 路由 — 作品详情与文件

**Files:**
- Create: `src/pixiv_archive/web/routers/illust.py`
- Modify: `src/pixiv_archive/web/routers/__init__.py`
- Test: `tests/test_web_routers_illust.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_web_routers_illust.py`：

```python
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import (
    Author,
    Bookmark,
    Illust,
    IllustPage,
    IllustTag,
    Tag,
    UgoiraMeta,
)
from pixiv_archive.web.auth import SessionSigner
from pixiv_archive.web.routers.illust import router as illust_router

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xd2\xcf \xff\xd9"
)


@pytest.fixture
async def client(tmp_path):
    database = Database(tmp_path / "ill.db")
    await database.create_all()
    works = tmp_path / "works"
    (works / "10" / "original").mkdir(parents=True)
    (works / "10" / "original" / "000_p0.jpg").write_bytes(JPEG)
    (works / "10" / "thumb.webp").write_bytes(b"RIFFxxxxWEBP")
    (works / "10" / "animation.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")

    async with database.session() as session:
        session.add(Author(id=1, name="画师", account="acct"))
        session.add(
            Illust(
                pid=10,
                title="作品十",
                description="描述",
                author_id=1,
                page_count=2,
                type="ugoira",
                has_original=False,
                page_downloaded_count=1,
            )
        )
        await session.commit()
    async with database.session() as session:
        session.add(
            IllustPage(pid=10, page_index=0, original_url="https://x/0.jpg", ext=".jpg",
                       download_state="done")
        )
        session.add(
            IllustPage(pid=10, page_index=1, original_url="https://x/1.jpg", ext=".jpg",
                       download_state="pending")
        )
        session.add(UgoiraMeta(pid=10, zip_url="https://x/u.zip", frames_json="[]",
                               frame_count=126))
        session.add(Bookmark(pid=10, restrict="private", rank=0, state="active"))
        tag = Tag(name="猫")
        session.add(tag)
        await session.flush()
        session.add(IllustTag(pid=10, tag_id=tag.id, position=0))
        await session.commit()

    app = FastAPI()
    app.state.db = database
    app.state.settings = type("S", (), {"works_dir": works})()
    app.state.session_signer = SessionSigner("secret")
    app.include_router(illust_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as http:
        http._signer = app.state.session_signer  # type: ignore[attr-defined]
        http.cookies.set("session", app.state.session_signer.sign("ok"))
        yield http
    await database.dispose()


async def test_illust_detail(client):
    response = await client.get("/api/illust/10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["pid"] == 10
    assert payload["title"] == "作品十"
    assert payload["tags"] == ["猫"]
    assert payload["page_count"] == 2
    assert payload["page_downloaded_count"] == 1
    assert payload["restrict"] == "private"
    assert payload["rank"] == 0
    assert payload["pixiv_url"] == "https://www.pixiv.net/artworks/10"
    assert payload["animation_available"] is True
    assert payload["frame_count"] == 126
    assert payload["pages"][0]["download_state"] == "done"
    assert payload["pages"][1]["download_state"] == "pending"


async def test_illust_detail_404(client):
    response = await client.get("/api/illust/999")
    assert response.status_code == 404


async def test_illust_file_serves_local_original(client):
    response = await client.get("/api/illust/10/file/0")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert "ETag" in response.headers


async def test_illust_file_404_when_missing(client):
    response = await client.get("/api/illust/10/file/1")
    assert response.status_code == 404


async def test_illust_file_supports_range(client):
    response = await client.get("/api/illust/10/file/0", headers={"Range": "bytes=0-9"})
    assert response.status_code == 206
    assert response.headers["content-range"].startswith("bytes 0-9/")


async def test_illust_file_etag_304(client):
    first = await client.get("/api/illust/10/file/0")
    etag = first.headers["ETag"]
    second = await client.get("/api/illust/10/file/0", headers={"If-None-Match": etag})
    assert second.status_code == 304


async def test_illust_thumb_prefers_local_webp(client):
    response = await client.get("/api/illust/10/thumb")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"


async def test_illust_thumb_placeholder_when_missing(client):
    response = await client.get("/api/illust/999/thumb")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg")


async def test_illust_animation(client):
    response = await client.get("/api/illust/10/animation")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_routers_illust.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.web.routers.illust'`

- [ ] **Step 3: 实现 illust.py 路由**

`src/pixiv_archive/web/routers/illust.py`：

```python
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import (
    Author,
    Bookmark,
    Illust,
    IllustPage,
    IllustTag,
    Tag,
    UgoiraMeta,
)
from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_session, get_settings
from pixiv_archive.web.files import file_response, placeholder_response, resolve_thumb
from pixiv_archive.web.schemas import IllustDetailOut, IllustPageOut

router = APIRouter(prefix="/api/illust", tags=["illust"], dependencies=[Depends(require_auth)])


async def _display_index(session: AsyncSession, pid: int) -> int:
    rank = (
        await session.execute(select(Bookmark.rank).where(Bookmark.pid == pid))
    ).scalar_one_or_none()
    if rank is None:
        return 0
    return (
        await session.execute(
            select(func.count())
            .select_from(Bookmark)
            .where(Bookmark.state == "active", Bookmark.rank < rank)
        )
    ).scalar_one() + 1


@router.get("/{pid}", response_model=IllustDetailOut)
async def illust_detail(
    pid: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> IllustDetailOut:
    settings = get_settings(request)
    row = (
        await session.execute(
            select(Illust, Author, Bookmark)
            .join(Author, Author.id == Illust.author_id)
            .outerjoin(Bookmark, Bookmark.pid == Illust.pid)
            .where(Illust.pid == pid)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="illust not found")
    illust, author, bookmark = row

    tag_rows = (
        await session.execute(
            select(Tag.name, Tag.translated_name)
            .join(IllustTag, IllustTag.tag_id == Tag.id)
            .where(IllustTag.pid == pid)
            .order_by(IllustTag.position)
        )
    ).all()
    pages = (
        (
            await session.execute(
                select(IllustPage).where(IllustPage.pid == pid).order_by(IllustPage.page_index)
            )
        )
        .scalars()
        .all()
    )
    ugoira = await session.get(UgoiraMeta, pid)
    animation_path = settings.works_dir / str(pid) / "animation.mp4"

    return IllustDetailOut(
        pid=illust.pid,
        index=await _display_index(session, pid),
        title=illust.title,
        description=illust.description,
        author_id=author.id,
        author_name=author.name,
        author_account=author.account,
        page_count=illust.page_count,
        type=illust.type,
        x_restrict=illust.x_restrict,
        sanity_level=illust.sanity_level,
        width=illust.width,
        height=illust.height,
        create_date=illust.create_date,
        total_view=illust.total_view,
        total_bookmarks=illust.total_bookmarks,
        state=illust.state,
        has_original=illust.has_original,
        page_downloaded_count=illust.page_downloaded_count,
        tags=[name for name, _ in tag_rows],
        translated_tags=[t for _, t in tag_rows if t],
        pages=[
            IllustPageOut(
                page_index=page.page_index,
                download_state=page.download_state,
                ext=page.ext,
            )
            for page in pages
        ],
        restrict=bookmark.restrict if bookmark else "public",
        bookmark_state=bookmark.state if bookmark else "unbookmarked",
        rank=bookmark.rank if bookmark else None,
        pixiv_url=f"https://www.pixiv.net/artworks/{illust.pid}",
        animation_available=animation_path.is_file(),
        frame_count=ugoira.frame_count if ugoira else None,
        unbookmarked=(bookmark.state == "unbookmarked") if bookmark else True,
    )


@router.get("/{pid}/file/{page_index}")
async def illust_file(
    pid: int,
    page_index: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    settings = get_settings(request)
    page = (
        await session.execute(
            select(IllustPage).where(
                IllustPage.pid == pid, IllustPage.page_index == page_index
            )
        )
    ).scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    target = (
        settings.works_dir / str(pid) / "original" / f"{page_index:03d}_p{page_index}{page.ext}"
    )
    if not target.is_file():
        raise HTTPException(status_code=404, detail="original not downloaded")
    filename = f"{pid}_p{page_index}{page.ext}"
    return file_response(request, target, download_name=filename)


@router.get("/{pid}/thumb")
async def illust_thumb(pid: int, request: Request) -> Response:
    settings = get_settings(request)
    thumb = resolve_thumb(settings.works_dir, pid)
    if thumb is None:
        return placeholder_response(pid)
    return file_response(request, thumb)


@router.get("/{pid}/animation")
async def illust_animation(pid: int, request: Request) -> Response:
    settings = get_settings(request)
    animation = settings.works_dir / str(pid) / "animation.mp4"
    if not animation.is_file():
        raise HTTPException(status_code=404, detail="animation not available")
    return file_response(request, animation)


@router.get("/{pid}/ugoira.zip")
async def illust_ugoira_zip(pid: int, request: Request) -> Response:
    settings = get_settings(request)
    archive = settings.works_dir / str(pid) / "source.zip"
    if not archive.is_file():
        raise HTTPException(status_code=404, detail="ugoira archive not available")
    return file_response(request, archive, download_name=f"{pid}_ugoira.zip")
```

更新 `src/pixiv_archive/web/routers/__init__.py`：

```python
from pixiv_archive.web.routers import auth, gallery, illust

__all__ = ["auth", "gallery", "illust"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_routers_illust.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/web/routers tests/test_web_routers_illust.py
git commit -m "feat: add illust detail and file routers"
```

---

### Task 7: 路由 — 任务、同步、下载、SSE

**Files:**
- Create: `src/pixiv_archive/web/routers/tasks.py`
- Modify: `src/pixiv_archive/web/routers/__init__.py`
- Test: `tests/test_web_routers_tasks.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_web_routers_tasks.py`：

```python
import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import Author, Bookmark, Illust, IllustPage
from pixiv_archive.web.auth import SessionSigner
from pixiv_archive.web.routers.tasks import router as tasks_router
from pixiv_archive.web.tasks import TaskManager


@pytest.fixture
async def client(tmp_path):
    database = Database(tmp_path / "t.db")
    await database.create_all()
    async with database.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=1, title="t", author_id=1, page_count=1))
        await session.commit()
    async with database.session() as session:
        session.add(
            IllustPage(pid=1, page_index=0, original_url="https://x/0.jpg", ext=".jpg")
        )
        session.add(Bookmark(pid=1, restrict="public", rank=0, state="active"))
        await session.commit()

    app = FastAPI()
    app.state.db = database
    app.state.session_signer = SessionSigner("secret")
    app.state.tasks = TaskManager()
    app.state.settings = type(
        "S",
        (),
        {
            "works_dir": tmp_path / "works",
            "pixiv_refresh_token": "t",
            "pixiv_user_id": 1,
            "pixiv_proxy": None,
            "pixiv_image_mirror": None,
            "api_min_interval_ms": 0,
            "image_concurrency": 1,
            "download_previews": True,
            "ffmpeg_bin": "ffmpeg",
            "data_dir": tmp_path,
            "db_path": tmp_path / "t.db",
            "ensure_dirs": lambda: None,
        },
    )()
    app.include_router(tasks_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as http:
        http.cookies.set("session", app.state.session_signer.sign("ok"))
        yield http
    await database.dispose()


async def test_tasks_empty_initially(client):
    response = await client.get("/api/tasks")
    assert response.status_code == 200
    assert response.json() == []


async def test_sync_endpoint_starts_task(client, monkeypatch):
    import pixiv_archive.web.routers.tasks as tasks_module

    class FakeResult:
        status = "completed"
        new_count = 3
        pages_fetched = 2

    class FakeService:
        async def run_incremental(self, max_pages=None):
            return FakeResult()

        async def run_full(self, max_pages=None):
            return FakeResult()

        def set_download_previews(self, enabled):
            pass

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_open(settings):
        yield FakeService()

    monkeypatch.setattr(tasks_module, "open_sync_service", fake_open)

    response = await client.post("/api/sync", json={"mode": "incremental"})
    assert response.status_code == 202
    task_id = response.json()["id"]

    for _ in range(50):
        await asyncio.sleep(0.05)
        record = (await client.get("/api/tasks")).json()
        if record and record[0]["status"] != "running":
            break
    listing = (await client.get("/api/tasks")).json()
    assert listing[0]["id"] == task_id
    assert listing[0]["status"] == "completed"
    assert listing[0]["detail"]["new_count"] == 3


async def test_download_endpoint_starts_task(client, monkeypatch):
    import pixiv_archive.web.routers.tasks as tasks_module

    class FakeReport:
        status = "completed"
        pages_done = 1
        thumbs_done = 1
        failed = 0

    class FakeWorker:
        def set_thumb_enabled(self, enabled):
            pass

        async def retry_failed(self):
            return 0

        async def run_scope(self, scope):
            return FakeReport()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_open(settings):
        yield FakeWorker()

    monkeypatch.setattr(tasks_module, "open_download_worker", fake_open)

    response = await client.post(
        "/api/downloads", json={"scope": "all_missing", "pids": [], "with_thumbs": True}
    )
    assert response.status_code == 202
    for _ in range(50):
        await asyncio.sleep(0.05)
        listing = (await client.get("/api/tasks")).json()
        if listing and listing[0]["status"] != "running":
            break
    listing = (await client.get("/api/tasks")).json()
    assert listing[0]["kind"] == "download"
    assert listing[0]["status"] == "completed"


async def test_duplicate_sync_rejected(client, monkeypatch):
    import pixiv_archive.web.routers.tasks as tasks_module

    release = asyncio.Event()

    class SlowService:
        async def run_incremental(self, max_pages=None):
            await release.wait()
            return type("R", (), {"status": "completed", "new_count": 0, "pages_fetched": 0})()

        async def run_full(self, max_pages=None):
            return await self.run_incremental()

        def set_download_previews(self, enabled):
            pass

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_open(settings):
        yield SlowService()

    monkeypatch.setattr(tasks_module, "open_sync_service", fake_open)

    first = await client.post("/api/sync", json={"mode": "incremental"})
    assert first.status_code == 202
    second = await client.post("/api/sync", json={"mode": "incremental"})
    assert second.status_code == 409
    release.set()
    for _ in range(50):
        await asyncio.sleep(0.05)
        listing = (await client.get("/api/tasks")).json()
        if listing and listing[0]["status"] != "running":
            break


async def test_events_endpoint_streams_sse(client):
    async with client.stream("GET", "/api/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        # publish one event into the bus so the stream yields something
        client._transport.app.state.tasks.events.publish("task", {"task_id": "x"})  # type: ignore[union-attr]
        lines = []
        async for line in response.aiter_lines():
            lines.append(line)
            if len(lines) >= 3:
                break
    assert any(line.startswith("event:") for line in lines)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_routers_tasks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.web.routers.tasks'`

- [ ] **Step 3: 实现 tasks.py 路由**

`src/pixiv_archive/web/routers/tasks.py`：

```python
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from pixiv_archive.download.scope import DownloadScope
from pixiv_archive.sync.factory import open_download_worker, open_sync_service
from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_events, get_tasks
from pixiv_archive.web.schemas import DownloadRequest, SyncRequest, TaskOut
from pixiv_archive.web.sse import EventBus, event_stream
from pixiv_archive.web.tasks import TaskContext, TaskManager

router = APIRouter(prefix="/api", tags=["tasks"], dependencies=[Depends(require_auth)])


def _scope_from_request(payload: DownloadRequest) -> DownloadScope:
    mapping = {
        "all-missing": "all_missing",
        "all_missing": "all_missing",
        "author": "author",
        "selected": "selected",
        "rank-range": "rank_range",
        "rank_range": "rank_range",
        "filter": "filter",
    }
    kind = mapping.get(payload.scope)
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
    )


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED, response_model=TaskOut)
async def start_sync(
    payload: SyncRequest,
    request: Request,
    tasks: TaskManager = Depends(get_tasks),
) -> TaskOut:
    settings = request.app.state.settings
    if payload.mode not in ("incremental", "full"):
        raise HTTPException(status_code=422, detail="mode must be incremental or full")

    async def run(context: TaskContext) -> dict:
        async with open_sync_service(settings) as service:
            service._on_progress = context.progress
            if payload.mode == "full":
                result = await service.run_full()
            else:
                result = await service.run_incremental()
            return {
                "status": result.status,
                "new_count": result.new_count,
                "unbookmarked_count": result.unbookmarked_count,
                "rank_rebuilt_count": result.rank_rebuilt_count,
                "pages_fetched": result.pages_fetched,
                "previews_fetched": result.previews_fetched,
                "previews_failed": result.previews_failed,
                "failed_count": result.failed_count,
            }

    try:
        task_id = tasks.start("sync", run)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record = tasks.get(task_id)
    assert record is not None
    return TaskOut(**record.to_dict())


@router.post("/downloads", status_code=status.HTTP_202_ACCEPTED, response_model=TaskOut)
async def start_download(
    payload: DownloadRequest,
    request: Request,
    tasks: TaskManager = Depends(get_tasks),
) -> TaskOut:
    settings = request.app.state.settings
    scope = _scope_from_request(payload)

    async def run(context: TaskContext) -> dict:
        async with open_download_worker(settings) as worker:
            if not payload.with_thumbs:
                worker.set_thumb_enabled(False)
            report = await worker.run_scope(scope)
            return {
                "status": report.status,
                "pages_done": report.pages_done,
                "pages_failed": report.pages_failed,
                "thumbs_done": report.thumbs_done,
                "ugoira_done": report.ugoira_done,
                "failed": report.failed,
                "batch_id": report.batch_id,
            }

    try:
        task_id = tasks.start("download", run)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record = tasks.get(task_id)
    assert record is not None
    return TaskOut(**record.to_dict())


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(tasks: TaskManager = Depends(get_tasks)) -> list[TaskOut]:
    return [TaskOut(**record.to_dict()) for record in tasks.all()]


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: str, tasks: TaskManager = Depends(get_tasks)) -> TaskOut:
    record = tasks.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskOut(**record.to_dict())


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(task_id: str, tasks: TaskManager = Depends(get_tasks)) -> TaskOut:
    record = tasks.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="task not found")
    if not tasks.cancel(task_id):
        raise HTTPException(status_code=409, detail="task is not running")
    return TaskOut(**record.to_dict())


@router.get("/events")
async def events(request: Request, bus: EventBus = Depends(get_events)) -> StreamingResponse:
    queue = bus.subscribe(replay=True)
    return StreamingResponse(event_stream(bus, queue), media_type="text/event-stream")
```

更新 `src/pixiv_archive/web/routers/__init__.py`：

```python
from pixiv_archive.web.routers import auth, gallery, illust, tasks

__all__ = ["auth", "gallery", "illust", "tasks"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_routers_tasks.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/web/routers tests/test_web_routers_tasks.py
git commit -m "feat: add task, sync, download and SSE routers"
```

---

### Task 8: 路由 — 统计与导出

**Files:**
- Create: `src/pixiv_archive/web/routers/stats.py`
- Create: `src/pixiv_archive/web/routers/export.py`
- Modify: `src/pixiv_archive/web/routers/__init__.py`
- Test: `tests/test_web_routers_stats_export.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_web_routers_stats_export.py`：

```python
import asyncio
import zipfile

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import (
    Author,
    Bookmark,
    Illust,
    IllustPage,
    UgoiraMeta,
)
from pixiv_archive.web.auth import SessionSigner
from pixiv_archive.web.routers.export import router as export_router
from pixiv_archive.web.routers.stats import router as stats_router
from pixiv_archive.web.tasks import TaskManager


@pytest.fixture
async def client(tmp_path):
    database = Database(tmp_path / "se.db")
    await database.create_all()
    works = tmp_path / "works"
    (works / "10" / "original").mkdir(parents=True)
    (works / "10" / "original" / "000_p0.jpg").write_bytes(b"jpeg-bytes")
    (works / "10" / "thumb.webp").write_bytes(b"webp-bytes")
    (works / "10" / "meta.json").write_text('{"id": 10}', encoding="utf-8")

    async with database.session() as session:
        session.add(Author(id=1, name="a"))
        session.add(Illust(pid=10, title="t", author_id=1, type="ugoira",
                           has_original=True, page_downloaded_count=1))
        session.add(Illust(pid=20, title="u", author_id=1, has_original=False))
        await session.commit()
    async with database.session() as session:
        session.add(IllustPage(pid=10, page_index=0, original_url="x", ext=".jpg",
                               download_state="done"))
        session.add(IllustPage(pid=20, page_index=0, original_url="y", ext=".jpg",
                               download_state="pending"))
        session.add(UgoiraMeta(pid=10, zip_url="z", frames_json="[]", frame_count=5))
        session.add(Bookmark(pid=10, restrict="public", rank=0, state="active"))
        session.add(Bookmark(pid=20, restrict="private", rank=1024, state="active"))
        await session.commit()

    app = FastAPI()
    app.state.db = database
    app.state.session_signer = SessionSigner("secret")
    app.state.tasks = TaskManager()
    app.state.settings = type("S", (), {"works_dir": works})()
    app.include_router(stats_router)
    app.include_router(export_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as http:
        http.cookies.set("session", app.state.session_signer.sign("ok"))
        yield http
    await database.dispose()


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
    assert payload["total_bytes"] > 0


async def test_export_metadata_zip(client):
    response = await client.post(
        "/api/export",
        json={"include_metadata": True, "include_originals": False, "pids": [10]},
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    for _ in range(50):
        await asyncio.sleep(0.05)
        record = (await client.get(f"/api/tasks/{task_id}")).json()
        if record["status"] != "running":
            break
    assert record["status"] == "completed"

    download = await client.get(f"/api/export/{task_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"


async def test_export_originals_zip(client):
    response = await client.post(
        "/api/export",
        json={
            "include_metadata": False,
            "include_originals": True,
            "pids": [10],
            "only_downloaded": True,
        },
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    for _ in range(50):
        await asyncio.sleep(0.05)
        record = (await client.get(f"/api/tasks/{task_id}")).json()
        if record["status"] != "running":
            break
    download = await client.get(f"/api/export/{task_id}/download")
    assert download.status_code == 200
    archive = zipfile.ZipFile(__import__("io").BytesIO(download.content))
    names = archive.namelist()
    assert any("000_p0.jpg" in name for name in names)


async def test_export_download_404_for_unknown(client):
    response = await client.get("/api/export/nope/download")
    assert response.status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_routers_stats_export.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.web.routers.stats'`

- [ ] **Step 3: 实现 stats.py 与 export.py**

`src/pixiv_archive/web/routers/stats.py`：

```python
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Bookmark, Illust, IllustPage, UgoiraMeta
from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_session, get_settings
from pixiv_archive.web.schemas import StatsOut

router = APIRouter(prefix="/api", tags=["stats"], dependencies=[Depends(require_auth)])


def _sum_sizes(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


@router.get("/stats", response_model=StatsOut)
async def stats(
    request: Request, session: AsyncSession = Depends(get_session)
) -> StatsOut:
    settings = get_settings(request)

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
    page_counts = dict(
        (
            await session.execute(
                select(IllustPage.download_state, func.count()).group_by(IllustPage.download_state)
            )
        ).all()
    )
    total_pages = sum(page_counts.values())
    by_type = dict(
        (await session.execute(select(Illust.type, func.count()).group_by(Illust.type))).all()
    )
    by_restrict = dict(
        (
            await session.execute(
                select(Bookmark.restrict, func.count()).group_by(Bookmark.restrict)
            )
        ).all()
    )
    ugoira_count = (
        await session.execute(select(func.count()).select_from(UgoiraMeta))
    ).scalar_one()

    works_root = settings.works_dir
    thumbs_ready = len(list(works_root.glob("*/thumb.webp"))) if works_root.is_dir() else 0
    animation_ready = (
        len(list(works_root.glob("*/animation.mp4"))) if works_root.is_dir() else 0
    )

    return StatsOut(
        total_illusts=total_illusts,
        unbookmarked=unbookmarked,
        total_pages=total_pages,
        downloaded_pages=page_counts.get("done", 0),
        failed_pages=page_counts.get("failed", 0),
        pending_pages=page_counts.get("pending", 0),
        total_bytes=_sum_sizes(works_root),
        thumbs_ready=thumbs_ready,
        ugoira_count=ugoira_count,
        animation_ready=animation_ready,
        by_type=by_type,
        by_restrict=by_restrict,
    )
```

`src/pixiv_archive/web/routers/export.py`：

```python
import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.db.models import Author, Bookmark, Illust, IllustPage
from pixiv_archive.web.auth import require_auth
from pixiv_archive.web.deps import get_session, get_settings, get_tasks
from pixiv_archive.web.schemas import ExportOut, ExportRequest
from pixiv_archive.web.tasks import TaskContext, TaskManager

router = APIRouter(prefix="/api", tags=["export"], dependencies=[Depends(require_auth)])

_EXPORT_DIR_NAME = "exports"


def _export_dir(settings) -> Path:
    target = settings.works_dir.parent / _EXPORT_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


async def _selected_pids(session: AsyncSession, payload: ExportRequest) -> list[int]:
    stmt = (
        select(Illust.pid)
        .join(Bookmark, Bookmark.pid == Illust.pid)
        .where(Illust.state == "active")
        .order_by(Bookmark.rank)
    )
    if payload.pids:
        stmt = stmt.where(Illust.pid.in_(payload.pids))
    if payload.x_restrict is not None:
        stmt = stmt.where(Illust.x_restrict == payload.x_restrict)
    if payload.only_downloaded:
        stmt = stmt.where(Illust.has_original.is_(True))
    return list((await session.execute(stmt)).scalars().all())


def _add_metadata(archive: zipfile.ZipFile, illust: Illust, author: Author | None, tags: list[str]) -> None:
    payload = {
        "id": illust.pid,
        "title": illust.title,
        "description": illust.description,
        "type": illust.type,
        "page_count": illust.page_count,
        "width": illust.width,
        "height": illust.height,
        "x_restrict": illust.x_restrict,
        "create_date": illust.create_date.isoformat() if illust.create_date else None,
        "author": {"id": author.id, "name": author.name, "account": author.account}
        if author
        else None,
        "tags": tags,
        "pixiv_url": f"https://www.pixiv.net/artworks/{illust.pid}",
    }
    archive.writestr(f"metadata/{illust.pid}.json", json.dumps(payload, ensure_ascii=False, indent=2))


@router.post("/export", status_code=status.HTTP_202_ACCEPTED, response_model=ExportOut)
async def start_export(
    payload: ExportRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    tasks: TaskManager = Depends(get_tasks),
) -> ExportOut:
    settings = get_settings(request)
    pids = await _selected_pids(session, payload)
    if not pids:
        raise HTTPException(status_code=422, detail="no illusts match the export filter")

    filename = f"export-{len(pids)}-items.zip"
    destination = _export_dir(settings) / filename

    async def run(context: TaskContext) -> dict:
        from pixiv_archive.db.engine import Database

        database: Database = request.app.state.db
        written = 0
        if destination.exists():
            destination.unlink()
        async with database.session() as export_session:
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for index, pid in enumerate(pids, start=1):
                    context.progress("export", index, len(pids), f"导出 {pid}")
                    illust = await export_session.get(Illust, pid)
                    if illust is None:
                        continue
                    author = await export_session.get(Author, illust.author_id)
                    page_rows = (
                        (
                            await export_session.execute(
                                select(IllustPage)
                                .where(IllustPage.pid == pid)
                                .order_by(IllustPage.page_index)
                            )
                        )
                        .scalars()
                        .all()
                    )
                    work_dir = settings.works_dir / str(pid)
                    if payload.include_metadata:
                        _add_metadata(archive, illust, author, [])
                    if payload.include_originals:
                        for page in page_rows:
                            name = (
                                f"{pid:012d}/original/"
                                f"{page.page_index:03d}_p{page.page_index}{page.ext}"
                            )
                            source = work_dir / "original" / (
                                f"{page.page_index:03d}_p{page.page_index}{page.ext}"
                            )
                            if source.is_file():
                                archive.write(source, name)
                                written += 1
        return {"filename": filename, "pids": len(pids), "files": written}

    try:
        task_id = tasks.start("export", run)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ExportOut(task_id=task_id, filename=filename)


@router.get("/export/{task_id}/download")
async def download_export(
    task_id: str,
    request: Request,
    tasks: TaskManager = Depends(get_tasks),
) -> FileResponse:
    settings = get_settings(request)
    record = tasks.get(task_id)
    if record is None or record.kind != "export":
        raise HTTPException(status_code=404, detail="export task not found")
    filename = record.detail.get("filename")
    if not filename:
        raise HTTPException(status_code=409, detail="export is not finished")
    path = _export_dir(settings) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="export archive not found")
    return FileResponse(path, media_type="application/zip", filename=filename)
```

更新 `src/pixiv_archive/web/routers/__init__.py`：

```python
from pixiv_archive.web.routers import auth, export, gallery, illust, stats, tasks

__all__ = ["auth", "export", "gallery", "illust", "stats", "tasks"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_routers_stats_export.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/web/routers tests/test_web_routers_stats_export.py
git commit -m "feat: add stats and export routers"
```

---

### Task 9: 应用装配与 lifespan

**Files:**
- Modify: `src/pixiv_archive/web/app.py`
- Modify: `src/pixiv_archive/sync/scheduler.py`（新增 `build_sync_jobs` 便于装配）
- Test: `tests/test_web_app.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_web_app.py`：

```python
import pytest
from httpx import ASGITransport, AsyncClient

from pixiv_archive.config import Settings
from pixiv_archive.web.app import create_app


@pytest.fixture
def settings(monkeypatch, tmp_path) -> Settings:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PIXIV_REFRESH_TOKEN", "tok")
    monkeypatch.setenv("PIXIV_USER_ID", "1")
    monkeypatch.setenv("AUTH_TOKEN", "sesame")
    return Settings(_env_file=None)


async def test_health_is_public(settings):
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_api_routes_require_auth(settings):
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        for path in ("/api/gallery", "/api/stats", "/api/tasks", "/api/authors"):
            assert (await client.get(path)).status_code == 401


async def test_login_then_access(settings):
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        login = await client.post("/api/auth/login", json={"token": "sesame"})
        assert login.status_code == 200
        assert (await client.get("/api/gallery")).status_code == 200


async def test_openapi_is_public(settings):
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/openapi.json")).status_code == 200


async def test_scheduler_wired_when_interval_configured(settings):
    app = create_app(settings)
    assert hasattr(app.state, "scheduler")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_app.py -v`
Expected: FAIL — 路由未注册（`/api/gallery` 返回 404 而非 401）

- [ ] **Step 3: 实现 app.py 装配**

`src/pixiv_archive/web/app.py`：

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from pixiv_archive import __version__
from pixiv_archive.config import Settings
from pixiv_archive.db.engine import Database
from pixiv_archive.sync.factory import _ensure_schema
from pixiv_archive.sync.scheduler import create_scheduler
from pixiv_archive.web.auth import SessionSigner
from pixiv_archive.web.routers import auth, export, gallery, illust, stats, tasks
from pixiv_archive.web.sse import EventBus
from pixiv_archive.web.tasks import TaskManager


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings(_env_file=None)
    settings.ensure_dirs()

    database = Database(settings.db_path)
    events = EventBus()
    task_manager = TaskManager(events)
    signer = SessionSigner(settings.session_secret)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await _ensure_schema(settings)
        scheduler = create_scheduler(
            _make_incremental_job(app),
            interval=settings.sync_interval,
            full_cron=settings.sync_full_cron,
            full_job=_make_full_job(app),
        )
        app.state.scheduler = scheduler
        scheduler.start()
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
            await database.dispose()

    app = FastAPI(title="Pixiv Archive", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = database
    app.state.events = events
    app.state.tasks = task_manager
    app.state.session_signer = signer

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(gallery.router)
    app.include_router(illust.router)
    app.include_router(tasks.router)
    app.include_router(stats.router)
    app.include_router(export.router)

    @app.exception_handler(404)
    async def _not_found(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "not found"})

    return app


def _make_incremental_job(app: FastAPI):
    async def job() -> None:
        from pixiv_archive.sync.factory import open_sync_service

        if any(record.kind == "sync" for record in app.state.tasks.list_active()):
            return
        async with open_sync_service(app.state.settings) as service:
            await service.run_incremental()

    return job


def _make_full_job(app: FastAPI):
    async def job() -> None:
        from pixiv_archive.sync.factory import open_sync_service

        if any(record.kind == "sync" for record in app.state.tasks.list_active()):
            return
        async with open_sync_service(app.state.settings) as service:
            await service.run_full()

    return job
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_app.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/web/app.py tests/test_web_app.py
git commit -m "feat: assemble web app with routers and scheduler lifespan"
```

---

### Task 10: 静态前端占位与 Docker 集成

**Files:**
- Modify: `src/pixiv_archive/web/app.py`（挂载 `static/` 目录）
- Create: `src/pixiv_archive/web/static/index.html`（临时占位，计划 4b 会被 Vite 构建产物替换）
- Test: `tests/test_web_static.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_web_static.py`：

```python
import pytest
from httpx import ASGITransport, AsyncClient

from pixiv_archive.config import Settings
from pixiv_archive.web.app import create_app


@pytest.fixture
def settings(monkeypatch, tmp_path) -> Settings:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PIXIV_REFRESH_TOKEN", "tok")
    monkeypatch.setenv("PIXIV_USER_ID", "1")
    monkeypatch.setenv("AUTH_TOKEN", "sesame")
    return Settings(_env_file=None)


async def test_root_serves_spa_shell(settings):
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_unknown_spa_route_falls_back_to_shell(settings):
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/gallery/anything")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_unknown_api_route_returns_404_json(settings):
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"] == "not found"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_static.py -v`
Expected: FAIL — `/` 返回 404

- [ ] **Step 3: 添加静态目录与 SPA 回退**

`src/pixiv_archive/web/static/index.html`：

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Pixiv Archive</title>
    <style>
      body {
        margin: 0;
        background: #0f1115;
        color: #e6ebf2;
        font-family: system-ui, sans-serif;
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100vh;
      }
      main { text-align: center; }
      code { color: #93c5fd; }
    </style>
  </head>
  <body>
    <main>
      <h1>Pixiv Archive</h1>
      <p>后端 API 已就绪；前端界面由计划 4b 提供。</p>
      <p>API 文档：<code>/docs</code>　健康检查：<code>/api/health</code></p>
    </main>
  </body>
</html>
```

在 `app.py` 的 `create_app` 末尾（`exception_handler` 之前）加入：

```python
    from pathlib import Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets", check_dir=False), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_shell(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="not found")
            return FileResponse(static_dir / "index.html")
```

> 该路由必须放在所有 `include_router` 之后，否则会吞掉 API 路径。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_static.py -v`
Expected: 3 passed

- [ ] **Step 5: 全量检查并提交**

Run: `uv run ruff check src tests; uv run ruff format --check src tests; uv run mypy; uv run pytest -q`
Expected: 全部通过

```bash
git add src/pixiv_archive/web tests/test_web_static.py
git commit -m "feat: serve static spa shell with api fallback"
```

---

### Task 11: 真实数据端到端验证

**Files:**
- Create: `tests/test_integration_web.py`

- [ ] **Step 1: 写集成测试**

`tests/test_integration_web.py`：

```python
"""Live web API verification against the real local archive.

Run with:
    uv run pytest tests/test_integration_web.py -m integration -v -s
Uses the existing configured DATA_DIR (no network required except sync tests).
"""

import pytest
from httpx import ASGITransport, AsyncClient

from pixiv_archive.config import Settings
from pixiv_archive.web.app import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture
async def client(settings):
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as http:
        yield http


async def test_live_gallery_requires_login_then_lists(client, settings):
    assert (await client.get("/api/gallery")).status_code == 401
    login = await client.post("/api/auth/login", json={"token": settings.auth_token})
    assert login.status_code == 200

    response = await client.get("/api/gallery", params={"limit": 5})
    assert response.status_code == 200
    payload = response.json()
    print(f"\ntotal={payload['total']}")
    assert payload["total"] > 0
    first = payload["items"][0]
    print(f"first: #{first['index']} pid={first['pid']} {first['title'][:30]!r}")
    assert first["index"] == 1
    assert first["preview_url"]


async def test_live_stats_and_detail(client, settings):
    await client.post("/api/auth/login", json={"token": settings.auth_token})
    stats = (await client.get("/api/stats")).json()
    print(f"\nstats: {stats}")
    assert stats["total_illusts"] > 0

    gallery = (await client.get("/api/gallery", params={"limit": 1})).json()
    pid = gallery["items"][0]["pid"]
    detail = (await client.get(f"/api/illust/{pid}")).json()
    assert detail["pid"] == pid
    assert detail["pixiv_url"].endswith(str(pid))

    thumb = await client.get(f"/api/illust/{pid}/thumb")
    assert thumb.status_code == 200
    print(f"thumb content-type={thumb.headers['content-type']} bytes={len(thumb.content)}")


async def test_live_downloaded_file_served_with_range(client, settings):
    await client.post("/api/auth/login", json={"token": settings.auth_token})
    gallery = (
        await client.get("/api/gallery", params={"limit": 1, "downloaded": True})
    ).json()
    if not gallery["items"]:
        pytest.skip("no downloaded illusts available")
    pid = gallery["items"][0]["pid"]
    response = await client.get(f"/api/illust/{pid}/file/0", headers={"Range": "bytes=0-99"})
    assert response.status_code in (200, 206)
    if response.status_code == 206:
        assert response.headers["content-range"]
    assert len(response.content) > 0
```

- [ ] **Step 2: 运行单元测试确认无回归**

Run: `uv run pytest -q`
Expected: 全部通过

- [ ] **Step 3: 运行真实数据集成测试**

Run（PowerShell）:
```powershell
$env:DATA_DIR="D:\Projects\Pixiv-Collection-Archive\data"
$env:AUTH_TOKEN="test-token"
uv run pytest tests/test_integration_web.py -m integration -v -s
```
Expected: 3 passed，打印 total 与首条作品序号

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_web.py
git commit -m "test: add live web api integration tests"
```

---

### Task 12: 更新文档并推送

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新 README 状态与 API 说明**

把「状态」小节替换为：

```markdown
## 状态

- [x] 项目基础 + pixiv API 层
- [x] 阶段 A：元数据同步（增量 / 全量 + rank 顺序 + 预览图）
- [x] 阶段 B：图片下载（持久化队列 + 范围批次 + 原图 / ugoira / 缩略图）
- [x] Web API（认证 / 画廊 / 详情与文件 / 任务与 SSE / 统计 / 导出）
- [ ] 前端界面（计划 4b）
- [ ] 发布
```

在「快速开始」补充：

````markdown
### 启动 Web 服务

```bash
$env:AUTH_TOKEN = "your-token"   # 未设置时服务启动会提示
uv run python -m pixiv_archive
# 打开 http://localhost:8000 （当前为占位页；接口文档见 /docs）
```

主要接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` | 用 `AUTH_TOKEN` 换取 session cookie |
| GET | `/api/gallery` | 画廊（排序 / 过滤 / 搜索 / 分页） |
| GET | `/api/illust/{pid}` | 作品详情 |
| GET | `/api/illust/{pid}/file/{page}` | 原图（支持 Range 与 ETag） |
| GET | `/api/illust/{pid}/thumb` | 缩略图（本地 WebP 优先，回退预览图/占位） |
| GET | `/api/illust/{pid}/animation` | ugoira 转码后的 mp4 |
| POST | `/api/sync` | 触发阶段 A（`mode=incremental\|full`） |
| POST | `/api/downloads` | 触发阶段 B（scope: all_missing/author/selected/rank-range/filter） |
| GET | `/api/tasks` | 任务列表与状态 |
| GET | `/api/events` | SSE 实时进度事件流 |
| GET | `/api/stats` | 统计 |
| POST | `/api/export` | 导出 zip（元数据 / 原图） |
````

- [ ] **Step 2: 全量检查**

Run: `uv run ruff check src tests; uv run ruff format --check src tests; uv run mypy; uv run pytest -q`
Expected: 全部通过

- [ ] **Step 3: Commit 并推送**

```bash
git add README.md
git commit -m "docs: document web api and mark it complete"
git push origin main
```

- [ ] **Step 4: 确认云端 CI 通过**

Run: `gh run list --limit 3` 然后 `gh run watch <最新 run id> --exit-status`
Expected: `backend` 与 `docker` 两个 job 均成功

---

## 计划自审

**Spec 覆盖：**

| 设计章节 | 对应任务 |
| --- | --- |
| §9 认证（单用户 token + HttpOnly cookie；密钥持久化） | Task 1 |
| §9 画廊（排序/过滤/R-18/类型/作者/标签/搜索/下载状态） | Task 2、5 |
| §9 详情 + 文件（ETag/Range）+ 缩略图 + 动图 | Task 3、6 |
| §9 同步与下载触发 | Task 7 |
| §9 SSE（共用事件流，按 task 区分） | Task 4、7 |
| §9 统计 | Task 8 |
| §9 导出（后台任务 + 下载） | Task 8 |
| §9 `/api/health` | Task 9 |
| §10 前端（侧栏布局/画廊/详情/任务/统计/导出） | **计划 4b** |
| §11 `AUTH_TOKEN` | Task 1、9 |
| §12.1 Dockerfile 复制前端产物 | 计划 5（本轮用占位页） |
| §12.3 CI 前端检查（tsc/eslint/vitest） | 计划 4b |

**占位符扫描：** Task 6 的实现包含一段用于说明的错误草稿（`placeholder` 行），紧接着给出了**完整替换实现**（`complete implementation`）；执行时直接使用后者，不要写入草稿版本。其余步骤均含完整代码。

**类型一致性：**
- `TaskRecord.to_dict()/TaskManager.start/get/all/list_active/cancel/wait` 在 Task 4 定义，Task 7、8 使用一致 ✅
- `EventBus.subscribe/publish/recent/unsubscribe` 在 Task 4 定义，Task 7 使用一致 ✅
- `GalleryFilters` 字段在 Task 2 定义，Task 5 路由参数一一对应 ✅
- `file_response/parse_range/build_etag/resolve_thumb/placeholder_response` 在 Task 3 定义，Task 6 使用一致 ✅
- `DownloadScope(kind, pids, author_id, start, count, x_restrict, type)` 在计划 3 Task 5 定义，Task 7 使用一致 ✅
- `open_sync_service/open_download_worker` 在计划 2/3 定义，Task 7、9 使用一致 ✅
- `IllustDetailOut.pages[].download_state` 与 `IllustPage.download_state` 一致 ✅

**已知偏差与说明：**
- Task 8 的导出实现逐个作品打开/追加 zip（`zipfile.ZipFile(..., "a")`）以保证进度可回报；代价是大量小文件时较慢。计划 5 可优化为一次性打开 + 流式写入，但当前实现更简单且可中断（已导出部分保留在文件里）。
- Task 9 的定时任务直接调用 `open_sync_service`，与手动任务共用 `TaskManager` 的并发保护（按 kind 判断活跃任务），避免定时与手动同时跑。
