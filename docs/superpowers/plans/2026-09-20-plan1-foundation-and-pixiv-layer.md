# 计划 1：项目基础 + Pixiv API 层

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 uv 管理的 Python 项目骨架（配置、DB、迁移、Docker、CI），并实现可独立测试的自研 pixiv API 客户端（OAuth 认证、收藏列表翻页、限速重试、异常分类）。

**Architecture:** 分层设计：`config` 读取环境变量（pydantic-settings）；`db` 用 SQLAlchemy 2.x async + Alembic 管理 SQLite；`pixiv` 层是纯 API 客户端（httpx async + 自写 ratelimit/retry），不依赖 DB 与 Web；`web` 只留一个 `/api/health` 骨架。所有网络逻辑通过 httpx 注入，便于 respx mock 测试。

**Tech Stack:** Python 3.12、uv、FastAPI、uvicorn、SQLAlchemy 2.x async、aiosqlite、Alembic、httpx、pydantic-settings、pytest、pytest-asyncio、respx、ruff、mypy

> **执行前置条件**：本机 `uv` 可用；测试真实 API 时需要代理（环境变量 `PIXIV_PROXY=http://127.0.0.1:7897`）与用户提供的 refresh token。

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `pyproject.toml` | 项目元数据、依赖、ruff/mypy/pytest 配置 |
| `.gitignore` | 忽略 .venv、__pycache__、data/ 等 |
| `.env.example` | 环境变量样例（不含真实 token） |
| `src/pixiv_archive/__init__.py` | 包版本 |
| `src/pixiv_archive/config.py` | pydantic-settings 配置模型 |
| `src/pixiv_archive/db/__init__.py` | 包导出 |
| `src/pixiv_archive/db/engine.py` | async engine / session factory / WAL 设置 |
| `src/pixiv_archive/db/base.py` | DeclarativeBase |
| `src/pixiv_archive/db/models.py` | 计划 1 只放最小表：Illust / Author / Bookmark / AppSetting |
| `src/pixiv_archive/db/migrations/` | Alembic 环境与初始迁移 |
| `src/pixiv_archive/pixiv/__init__.py` | 包导出 |
| `src/pixiv_archive/pixiv/errors.py` | 异常树 |
| `src/pixiv_archive/pixiv/models.py` | pixiv API 响应的 pydantic 模型 |
| `src/pixiv_archive/pixiv/ratelimit.py` | 串行限速器 + 退避重试 |
| `src/pixiv_archive/pixiv/auth.py` | OAuth refresh_token 换 access_token（含缓存与回写） |
| `src/pixiv_archive/pixiv/client.py` | PixivClient：bookmark 翻页、illust detail、ugoira metadata |
| `src/pixiv_archive/web/__init__.py` | 包导出 |
| `src/pixiv_archive/web/app.py` | FastAPI 实例 + /api/health |
| `src/pixiv_archive/__main__.py` | `python -m pixiv_archive` 启动 uvicorn |
| `tests/conftest.py` | 公共 fixture |
| `tests/test_config.py` | 配置测试 |
| `tests/test_db.py` | DB 建表 / session 测试 |
| `tests/test_ratelimit.py` | 限速与重试测试 |
| `tests/test_auth.py` | OAuth 测试（respx mock） |
| `tests/test_client.py` | 翻页 / 解析 / 错误分类测试（respx mock） |
| `tests/test_integration_live.py` | 真实 API 集成测试（标记 integration） |
| `Dockerfile` | 多阶段构建 |
| `docker-compose.yml` | 单服务编排 |
| `.github/workflows/ci.yml` | lint + typecheck + test |
| `README.md` | 说明与快速开始 |

---

### Task 1: uv 项目初始化

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Modify: `.gitignore`（追加项目专属忽略项）

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[project]
name = "pixiv-archive"
version = "0.1.0"
description = "Sync and archive your pixiv collection with correct bookmark ordering"
readme = "README.md"
requires-python = ">=3.12,<3.13"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "httpx>=0.27",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "sqlalchemy[asyncio]>=2.0.36",
    "aiosqlite>=0.20",
    "alembic>=1.14",
    "pillow>=11.0",
    "apscheduler>=3.10",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "respx>=0.21",
    "ruff>=0.8",
    "mypy>=1.13",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/pixiv_archive"]

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "ASYNC"]

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
files = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "integration: tests that call the real pixiv API (requires PIXIV_REFRESH_TOKEN and network)",
]
addopts = "-m 'not integration'"
```

- [ ] **Step 2: 创建 .python-version 与追加 .gitignore**

`.python-version`：

```
3.12
```

追加到 `.gitignore`（文件末尾）：

```
# project
/data/
.env
*.part
```

- [ ] **Step 3: 创建包目录与版本文件**

`src/pixiv_archive/__init__.py`：

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: 同步依赖并验证**

Run: `uv sync`
Expected: 创建 `.venv`，生成 `uv.lock`，无报错

Run: `uv run python -c "import pixiv_archive; print(pixiv_archive.__version__)"`
Expected: 输出 `0.1.0`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock .python-version .gitignore src/pixiv_archive/__init__.py
git commit -m "chore: initialize uv project skeleton"
```

---

### Task 2: 配置模块

**Files:**
- Create: `src/pixiv_archive/config.py`
- Test: `tests/test_config.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: 写失败的测试**

`tests/conftest.py`：

```python
import os

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure tests never read real credentials from the host environment."""
    for key in list(os.environ):
        if key.startswith("PIXIV_") or key in {"DATA_DIR", "AUTH_TOKEN"}:
            monkeypatch.delenv(key, raising=False)
```

> 约定：所有 `Settings()` 构造在测试中一律传 `_env_file=None`，避免仓库根目录的 `.env` 干扰断言。

`tests/test_config.py`：

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from pixiv_archive.config import Settings


def test_settings_requires_refresh_token(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PIXIV_REFRESH_TOKEN", "tok")
    monkeypatch.setenv("PIXIV_USER_ID", "12345")
    s = Settings(_env_file=None)
    assert s.pixiv_refresh_token == "tok"
    assert s.pixiv_user_id == 12345
    assert s.api_min_interval_ms == 800
    assert s.image_concurrency == 4
    assert s.sync_interval == "6h"
    assert s.auth_token is None


def test_settings_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PIXIV_REFRESH_TOKEN", "tok")
    monkeypatch.setenv("PIXIV_USER_ID", "1")
    s = Settings(_env_file=None)
    assert s.data_dir == tmp_path
    assert s.db_path == tmp_path / "archive.db"
    assert s.works_dir == tmp_path / "works"
    assert s.logs_dir == tmp_path / "logs"


def test_settings_ensure_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "nested"))
    monkeypatch.setenv("PIXIV_REFRESH_TOKEN", "tok")
    monkeypatch.setenv("PIXIV_USER_ID", "1")
    s = Settings(_env_file=None)
    s.ensure_dirs()
    assert (tmp_path / "nested" / "works").is_dir()
    assert (tmp_path / "nested" / "logs").is_dir()


def test_settings_user_id_must_be_int(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PIXIV_REFRESH_TOKEN", "tok")
    monkeypatch.setenv("PIXIV_USER_ID", "not-a-number")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.config'`

- [ ] **Step 3: 实现 config.py**

```python
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    pixiv_refresh_token: str = Field(validation_alias="PIXIV_REFRESH_TOKEN")
    pixiv_user_id: int = Field(validation_alias="PIXIV_USER_ID")
    pixiv_proxy: str | None = Field(default=None, validation_alias="PIXIV_PROXY")
    pixiv_image_mirror: str | None = Field(default=None, validation_alias="PIXIV_IMAGE_MIRROR")

    data_dir: Path = Field(default=Path("/data"), validation_alias="DATA_DIR")
    auth_token: str | None = Field(default=None, validation_alias="AUTH_TOKEN")

    sync_interval: str = Field(default="6h", validation_alias="SYNC_INTERVAL")
    sync_full_cron: str | None = Field(default=None, validation_alias="SYNC_FULL_CRON")
    api_min_interval_ms: int = Field(default=800, validation_alias="API_MIN_INTERVAL_MS")
    image_concurrency: int = Field(default=4, validation_alias="IMAGE_CONCURRENCY")
    download_previews: bool = Field(default=True, validation_alias="DOWNLOAD_PREVIEWS")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "archive.db"

    @property
    def works_dir(self) -> Path:
        return self.data_dir / "works"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.works_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_config.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/config.py tests/conftest.py tests/test_config.py
git commit -m "feat: add settings module with env-based configuration"
```

---

### Task 3: 数据库引擎与最小模型

**Files:**
- Create: `src/pixiv_archive/db/__init__.py`
- Create: `src/pixiv_archive/db/base.py`
- Create: `src/pixiv_archive/db/models.py`
- Create: `src/pixiv_archive/db/engine.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_db.py`：

```python
import pytest
from sqlalchemy import select, text

from pixiv_archive.db.engine import Database
from pixiv_archive.db.models import AppSetting, Bookmark, Illust


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.create_all()
    yield database
    await database.dispose()


async def test_create_all_creates_tables(db, tmp_path):
    assert (tmp_path / "test.db").exists()
    async with db.session() as session:
        result = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        names = {row[0] for row in result}
    assert {"illust", "author", "bookmark", "app_setting"} <= names


async def test_wal_mode_enabled(db):
    async with db.session() as session:
        result = await session.execute(text("PRAGMA journal_mode"))
        assert result.scalar_one() == "wal"


async def test_insert_and_query_illust(db):
    async with db.session() as session:
        session.add(Illust(pid=123, title="hello", page_count=1, type="illust"))
        await session.commit()
    async with db.session() as session:
        row = (await session.execute(select(Illust).where(Illust.pid == 123))).scalar_one()
    assert row.title == "hello"
    assert row.state == "active"


async def test_bookmark_unique_pid(db):
    from sqlalchemy.exc import IntegrityError

    async with db.session() as session:
        session.add(Bookmark(pid=1, restrict="public", rank=0))
        await session.commit()
    with pytest.raises(IntegrityError):
        async with db.session() as session:
            session.add(Bookmark(pid=1, restrict="private", rank=1000))
            await session.commit()


async def test_app_setting_roundtrip(db):
    async with db.session() as session:
        session.add(AppSetting(key="refresh_token", value="abc"))
        await session.commit()
    async with db.session() as session:
        row = (await session.execute(select(AppSetting).where(AppSetting.key == "refresh_token"))).scalar_one()
    assert row.value == "abc"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.db'`

- [ ] **Step 3: 实现 db 包（base / models / engine）**

`src/pixiv_archive/db/base.py`：

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

`src/pixiv_archive/db/models.py`：

```python
from datetime import datetime, timezone

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pixiv_archive.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Author(Base):
    __tablename__ = "author"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255), default="")
    account: Mapped[str] = mapped_column(String(255), default="")
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class Illust(Base):
    __tablename__ = "illust"

    pid: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(512), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("author.id"), index=True)
    create_date: Mapped[datetime | None] = mapped_column(nullable=True)
    page_count: Mapped[int] = mapped_column(default=1)
    width: Mapped[int] = mapped_column(default=0)
    height: Mapped[int] = mapped_column(default=0)
    type: Mapped[str] = mapped_column(String(16), default="illust")
    x_restrict: Mapped[int] = mapped_column(default=0)
    sanity_level: Mapped[int] = mapped_column(default=0)
    illust_ai_type: Mapped[int] = mapped_column(default=0)
    total_view: Mapped[int] = mapped_column(default=0)
    total_bookmarks: Mapped[int] = mapped_column(default=0)
    state: Mapped[str] = mapped_column(String(16), default="active")
    has_original: Mapped[bool] = mapped_column(default=False)
    page_downloaded_count: Mapped[int] = mapped_column(default=0)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Bookmark(Base):
    __tablename__ = "bookmark"
    __table_args__ = (UniqueConstraint("pid", name="uq_bookmark_pid"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pid: Mapped[int] = mapped_column(BigInteger, ForeignKey("illust.pid"), index=True)
    restrict: Mapped[str] = mapped_column(String(16), default="public")
    rank: Mapped[int] = mapped_column(BigInteger, index=True)
    state: Mapped[str] = mapped_column(String(16), default="active")
    first_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    unbookmarked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class AppSetting(Base):
    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


Index("ix_bookmark_state_rank", Bookmark.state, Bookmark.rank)
```

`src/pixiv_archive/db/engine.py`：

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pixiv_archive.db.base import Base


class Database:
    """Owns the async engine and session factory for a SQLite file."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.path}")

        @event.listens_for(self.engine.sync_engine, "connect")
        def _set_pragma(dbapi_conn, _record):  # pragma: no cover - driver level
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self._session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session:
            yield session

    async def create_all(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def update_setting(self, key: str, value: str) -> None:
        from pixiv_archive.db.models import AppSetting

        async with self.session() as session:
            row = await session.get(AppSetting, key)
            if row is None:
                session.add(AppSetting(key=key, value=value))
            else:
                row.value = value
            await session.commit()

    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        from pixiv_archive.db.models import AppSetting

        async with self.session() as session:
            row = await session.get(AppSetting, key)
        return row.value if row is not None else default

    async def dispose(self) -> None:
        await self.engine.dispose()
```

`src/pixiv_archive/db/__init__.py`：

```python
from pixiv_archive.db.base import Base
from pixiv_archive.db.engine import Database

__all__ = ["Base", "Database"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_db.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/db tests/test_db.py
git commit -m "feat: add async sqlite database with core models"
```

---

### Task 4: Alembic 迁移

**Files:**
- Create: `src/pixiv_archive/db/migrations/env.py`
- Create: `src/pixiv_archive/db/migrations/script.py.mako`
- Create: `src/pixiv_archive/db/migrations/versions/0001_initial.py`
- Create: `alembic.ini`
- Test: `tests/test_migrations.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_migrations.py`：

```python
import subprocess
import sys

from sqlalchemy import text

from pixiv_archive.db.engine import Database


async def test_migrations_create_schema(tmp_path):
    db_file = tmp_path / "migrated.db"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        env={
            "PATH": __import__("os").environ["PATH"],
            "DATA_DIR": str(tmp_path),
            "PIXIV_REFRESH_TOKEN": "tok",
            "PIXIV_USER_ID": "1",
        },
    )
    assert result.returncode == 0, result.stderr

    db = Database(db_file)
    async with db.session() as session:
        rows = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        names = {r[0] for r in rows}
    await db.dispose()
    assert {"illust", "author", "bookmark", "app_setting"} <= names
    assert "alembic_version" in names
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_migrations.py -v`
Expected: FAIL — alembic 未配置（returncode != 0）

- [ ] **Step 3: 创建 alembic 配置与初始迁移**

`alembic.ini`：

```ini
[alembic]
script_location = src/pixiv_archive/db/migrations
prepend_sys_path = .
version_path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

`src/pixiv_archive/db/migrations/script.py.mako`：

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

`src/pixiv_archive/db/migrations/env.py`：

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from pixiv_archive.config import Settings
from pixiv_archive.db.base import Base
from pixiv_archive.db import models  # noqa: F401  (register models on Base.metadata)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    return f"sqlite+aiosqlite:///{settings.db_path}"


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    settings.ensure_dirs()
    engine = create_async_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

`src/pixiv_archive/db/migrations/versions/0001_initial.py`：

```python
"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "author",
        sa.Column("id", sa.BigInteger(), autoincrement=False, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("account", sa.String(255), nullable=False, server_default=""),
        sa.Column("avatar_url", sa.String(1024), nullable=True),
    )
    op.create_table(
        "illust",
        sa.Column("pid", sa.BigInteger(), autoincrement=False, primary_key=True),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_id", sa.BigInteger(), sa.ForeignKey("author.id"), nullable=False),
        sa.Column("create_date", sa.DateTime(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("type", sa.String(16), nullable=False, server_default="illust"),
        sa.Column("x_restrict", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sanity_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("illust_ai_type", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_view", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_bookmarks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        sa.Column("has_original", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("page_downloaded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_illust_author_id", "illust", ["author_id"])
    op.create_table(
        "bookmark",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("pid", sa.BigInteger(), sa.ForeignKey("illust.pid"), nullable=False),
        sa.Column("restrict", sa.String(16), nullable=False, server_default="public"),
        sa.Column("rank", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("unbookmarked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("pid", name="uq_bookmark_pid"),
    )
    op.create_index("ix_bookmark_pid", "bookmark", ["pid"])
    op.create_index("ix_bookmark_rank", "bookmark", ["rank"])
    op.create_index("ix_bookmark_state_rank", "bookmark", ["state", "rank"])
    op.create_table(
        "app_setting",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("app_setting")
    op.drop_table("bookmark")
    op.drop_table("illust")
    op.drop_table("author")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_migrations.py -v`
Expected: 1 passed

> 若失败且报 `DATA_DIR required`，说明子进程未继承环境变量；确认测试中的 `env` 参数包含 `DATA_DIR`（见测试代码）。

- [ ] **Step 5: Commit**

```bash
git add alembic.ini src/pixiv_archive/db/migrations tests/test_migrations.py
git commit -m "feat: add alembic migrations for initial schema"
```

---

### Task 5: pixiv 异常树与限速重试

**Files:**
- Create: `src/pixiv_archive/pixiv/__init__.py`
- Create: `src/pixiv_archive/pixiv/errors.py`
- Create: `src/pixiv_archive/pixiv/ratelimit.py`
- Test: `tests/test_ratelimit.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_ratelimit.py`：

```python
import time

import httpx
import pytest

from pixiv_archive.pixiv.errors import NetworkError, NotFoundError, RateLimited
from pixiv_archive.pixiv.ratelimit import RateLimiter, retry_async


async def test_retry_succeeds_after_transient_failure():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise NetworkError("boom")
        return "ok"

    result = await retry_async(flaky, attempts=3, base_delay=0.01)
    assert result == "ok"
    assert calls["n"] == 3


async def test_retry_gives_up_after_attempts():
    async def always_fail():
        raise NetworkError("nope")

    with pytest.raises(NetworkError):
        await retry_async(always_fail, attempts=2, base_delay=0.01)


async def test_retry_does_not_retry_not_found():
    calls = {"n": 0}

    async def not_found():
        calls["n"] += 1
        raise NotFoundError("gone")

    with pytest.raises(NotFoundError):
        await retry_async(not_found, attempts=3, base_delay=0.01)
    assert calls["n"] == 1


async def test_rate_limited_respects_retry_after(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("pixiv_archive.pixiv.ratelimit.asyncio.sleep", fake_sleep)
    calls = {"n": 0}

    async def limited():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimited("slow down", retry_after=2.5)
        return "ok"

    assert await retry_async(limited, attempts=3, base_delay=0.01) == "ok"
    assert slept and slept[0] == 2.5


async def test_rate_limiter_enforces_min_interval(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("pixiv_archive.pixiv.ratelimit.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("pixiv_archive.pixiv.ratelimit.time.monotonic", lambda: 100.0)

    limiter = RateLimiter(min_interval_ms=800)
    await limiter.acquire()
    assert slept == []  # first call never waits
    await limiter.acquire()
    assert slept == [pytest.approx(0.8)]


async def test_rate_limiter_serializes_concurrent_callers(monkeypatch):
    order: list[str] = []
    now = {"t": 0.0}

    async def fake_sleep(seconds: float) -> None:
        now["t"] += seconds

    monkeypatch.setattr("pixiv_archive.pixiv.ratelimit.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("pixiv_archive.pixiv.ratelimit.time.monotonic", lambda: now["t"])

    limiter = RateLimiter(min_interval_ms=100)

    async def worker(name: str) -> None:
        await limiter.acquire()
        order.append(name)

    import asyncio

    await asyncio.gather(worker("a"), worker("b"), worker("c"))
    assert order == ["a", "b", "c"]


def test_error_hierarchy():
    assert issubclass(NotFoundError, Exception)
    e = RateLimited("x", retry_after=1.0)
    assert e.retry_after == 1.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_ratelimit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.pixiv'`

- [ ] **Step 3: 实现 errors 与 ratelimit**

`src/pixiv_archive/pixiv/errors.py`：

```python
class PixivError(Exception):
    """Base class for all pixiv client errors."""


class AuthError(PixivError):
    """Refresh token missing/invalid or token exchange failed."""


class NetworkError(PixivError):
    """Transient transport failure. Safe to retry."""


class NotFoundError(PixivError):
    """Illust deleted or inaccessible. Do not retry."""


class RateLimited(PixivError):
    """Server asked us to slow down."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after
```

`src/pixiv_archive/pixiv/ratelimit.py`：

```python
import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pixiv_archive.pixiv.errors import NetworkError, NotFoundError, PixivError, RateLimited

T = TypeVar("T")


class RateLimiter:
    """Serializes callers and enforces a minimum interval between acquisitions."""

    def __init__(self, min_interval_ms: int) -> None:
        self._min_interval = min_interval_ms / 1000.0
        self._lock = asyncio.Lock()
        self._last_at: float | None = None

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._last_at is not None:
                wait = self._min_interval - (now - self._last_at)
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_at = time.monotonic()


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.6,
    jitter: float = 0.3,
) -> T:
    """Run ``operation`` with exponential backoff on transient errors only.

    NotFoundError and other non-retryable PixivErrors propagate immediately.
    RateLimited sleeps for the server-provided Retry-After when present.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return await operation()
        except RateLimited as exc:
            last = exc
            delay = exc.retry_after if exc.retry_after is not None else base_delay * (2**attempt)
        except NetworkError as exc:
            last = exc
            delay = base_delay * (2**attempt) + random.uniform(0, jitter)
        except NotFoundError:
            raise
        except PixivError:
            raise
        if attempt == attempts - 1:
            break
        await asyncio.sleep(delay)
    assert last is not None
    raise last
```

`src/pixiv_archive/pixiv/__init__.py`：

```python
from pixiv_archive.pixiv.errors import (
    AuthError,
    NetworkError,
    NotFoundError,
    PixivError,
    RateLimited,
)

__all__ = ["AuthError", "NetworkError", "NotFoundError", "PixivError", "RateLimited"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_ratelimit.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/pixiv tests/test_ratelimit.py
git commit -m "feat: add pixiv error tree and rate limiting with backoff retry"
```

---

### Task 6: OAuth 认证

**Files:**
- Create: `src/pixiv_archive/pixiv/auth.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_auth.py`：

```python
import httpx
import pytest
import respx

from pixiv_archive.pixiv.auth import CLIENT_ID, TOKEN_URL, TokenProvider
from pixiv_archive.pixiv.errors import AuthError

TOKEN_RESPONSE = {
    "response": {
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "expires_in": 3600,
        "user": {"id": "56269851", "name": "Yu_daa"},
    }
}


@pytest.fixture
def written_tokens():
    return []


@respx.mock
async def test_auth_fetches_and_caches_token(written_tokens):
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    provider = TokenProvider(
        refresh_token="refresh-0",
        proxy=None,
        on_refresh_token=lambda t: written_tokens.append(t),
        client=httpx.AsyncClient(),
    )
    token = await provider.get_access_token()
    assert token == "access-1"
    assert route.call_count == 1
    assert written_tokens == []  # identical refresh token not written back

    token = await provider.get_access_token()
    assert token == "access-1"
    assert route.call_count == 1  # cached


@respx.mock
async def test_auth_requests_correct_payload(written_tokens):
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    provider = TokenProvider(
        refresh_token="refresh-0",
        proxy=None,
        on_refresh_token=lambda t: written_tokens.append(t),
        client=httpx.AsyncClient(),
    )
    await provider.get_access_token()
    request = route.calls[0].request
    body = request.content.decode()
    assert "grant_type=refresh_token" in body
    assert "refresh_token=refresh-0" in body
    assert f"client_id={CLIENT_ID}" in body
    assert request.headers["app-os"] == "ios"


@respx.mock
async def test_rotated_refresh_token_is_written_back(written_tokens):
    rotated = dict(TOKEN_RESPONSE)
    rotated["response"] = dict(TOKEN_RESPONSE["response"])
    rotated["response"]["refresh_token"] = "refresh-2"
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=rotated))
    provider = TokenProvider(
        refresh_token="refresh-0",
        proxy=None,
        on_refresh_token=lambda t: written_tokens.append(t),
        client=httpx.AsyncClient(),
    )
    await provider.get_access_token()
    assert written_tokens == ["refresh-2"]


@respx.mock
async def test_expired_token_is_refreshed(written_tokens, monkeypatch):
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKEN_RESPONSE))
    provider = TokenProvider(
        refresh_token="refresh-0",
        proxy=None,
        on_refresh_token=lambda t: written_tokens.append(t),
        client=httpx.AsyncClient(),
    )
    await provider.get_access_token()
    monkeypatch.setattr("pixiv_archive.pixiv.auth.time.monotonic", lambda: 10**9)
    await provider.get_access_token()
    assert route.call_count == 2


@respx.mock
async def test_auth_error_on_400(written_tokens):
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    provider = TokenProvider(
        refresh_token="bad",
        proxy=None,
        on_refresh_token=lambda t: written_tokens.append(t),
        client=httpx.AsyncClient(),
    )
    with pytest.raises(AuthError):
        await provider.get_access_token()


@respx.mock
async def test_auth_network_error_is_retried(written_tokens):
    route = respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.ConnectTimeout("timeout"),
            httpx.Response(200, json=TOKEN_RESPONSE),
        ]
    )
    provider = TokenProvider(
        refresh_token="refresh-0",
        proxy=None,
        on_refresh_token=lambda t: written_tokens.append(t),
        client=httpx.AsyncClient(),
    )
    assert await provider.get_access_token() == "access-1"
    assert route.call_count == 2


async def test_invalidate_forces_refresh():
    provider = TokenProvider(
        refresh_token="r",
        proxy=None,
        on_refresh_token=lambda t: None,
        client=httpx.AsyncClient(),
    )
    provider._access_token = "stale"
    provider._expires_at = 10**12
    provider.invalidate()
    assert provider._access_token is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.pixiv.auth'`

- [ ] **Step 3: 实现 auth.py**

```python
import asyncio
import time
from collections.abc import Callable

import httpx

from pixiv_archive.pixiv.errors import AuthError, NetworkError
from pixiv_archive.pixiv.ratelimit import retry_async

TOKEN_URL = "https://oauth.secure.pixiv.net/auth/token"
CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"

APP_HEADERS = {
    "User-Agent": "PixivIOSApp/7.13.1 (iOS 14.6; iPhone13,2)",
    "App-OS": "ios",
    "App-OS-Version": "14.6",
    "App-Version": "7.13.1",
    "Accept-Language": "zh-CN",
}

_REFRESH_MARGIN_SECONDS = 300


class TokenProvider:
    """Exchanges a refresh token for short-lived access tokens, with caching."""

    def __init__(
        self,
        refresh_token: str,
        *,
        proxy: str | None = None,
        on_refresh_token: Callable[[str], None] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._refresh_token = refresh_token
        self._on_refresh_token = on_refresh_token or (lambda _t: None)
        self._client = client or httpx.AsyncClient(proxy=proxy, timeout=30.0)
        self._owns_client = client is None
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client

    def invalidate(self) -> None:
        self._access_token = None
        self._expires_at = 0.0

    async def get_access_token(self) -> str:
        async with self._lock:
            if self._access_token is not None and time.monotonic() < self._expires_at:
                return self._access_token
            await self._refresh()
            assert self._access_token is not None
            return self._access_token

    async def _refresh(self) -> None:
        async def _exchange() -> httpx.Response:
            try:
                return await self._client.post(
                    TOKEN_URL,
                    data={
                        "client_id": CLIENT_ID,
                        "client_secret": CLIENT_SECRET,
                        "grant_type": "refresh_token",
                        "include_policy": "true",
                        "refresh_token": self._refresh_token,
                    },
                    headers=APP_HEADERS,
                )
            except httpx.HTTPError as exc:
                raise NetworkError(f"token request failed: {exc}") from exc

        response = await retry_async(_exchange, attempts=3, base_delay=0.6)
        if response.status_code >= 400:
            raise AuthError(
                f"token exchange failed with HTTP {response.status_code}: {response.text[:200]}"
            )
        payload = response.json().get("response") or {}
        access_token = payload.get("access_token")
        if not access_token:
            raise AuthError(f"token response missing access_token: {response.text[:200]}")

        new_refresh = payload.get("refresh_token")
        if new_refresh and new_refresh != self._refresh_token:
            self._refresh_token = new_refresh
            self._on_refresh_token(new_refresh)

        self._access_token = access_token
        self._expires_at = time.monotonic() + payload.get("expires_in", 3600) - _REFRESH_MARGIN_SECONDS

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_auth.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/pixiv/auth.py tests/test_auth.py
git commit -m "feat: add oauth token provider with caching and rotation handling"
```

---

### Task 7: pixiv 响应模型

**Files:**
- Modify: `src/pixiv_archive/pixiv/models.py` (create)
- Test: `tests/test_models.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_models.py`：

```python
from pixiv_archive.pixiv.models import BookmarkPage, IllustDetail, UgoiraMetadata


def test_bookmark_page_parses_illust_urls_single_page():
    payload = {
        "illusts": [
            {
                "id": 147217442,
                "title": "t",
                "type": "illust",
                "page_count": 1,
                "width": 100,
                "height": 200,
                "x_restrict": 0,
                "sanity_level": 2,
                "illust_ai_type": 2,
                "total_view": 5,
                "total_bookmarks": 6,
                "create_date": "2026-07-15T07:11:25+09:00",
                "user": {"id": 73804603, "name": "魚辺ン", "account": "3227332346"},
                "tags": [{"name": "R-18", "translated_name": None}],
                "meta_single_page": {"original_image_url": "https://i.pximg.net/orig.png"},
                "image_urls": {"square_medium": "https://i.pximg.net/sq.jpg"},
            }
        ],
        "next_url": "https://app-api.pixiv.net/v1/user/bookmarks/illust?user_id=1&max_bookmark_id=999",
    }
    page = BookmarkPage.model_validate(payload)
    assert page.next_bookmark_id == 999
    illust = page.illusts[0]
    assert illust.pid == 147217442
    assert illust.page_count == 1
    assert illust.original_urls == ["https://i.pximg.net/orig.png"]
    assert illust.preview_url == "https://i.pximg.net/sq.jpg"
    assert illust.author.id == 73804603
    assert illust.tags[0].name == "R-18"


def test_bookmark_page_parses_meta_pages():
    payload = {
        "illusts": [
            {
                "id": 1,
                "title": "multi",
                "type": "illust",
                "page_count": 2,
                "user": {"id": 1, "name": "a"},
                "meta_pages": [
                    {"image_urls": {"original": "https://i.pximg.net/p0.jpg"}},
                    {"image_urls": {"original": "https://i.pximg.net/p1.jpg"}},
                ],
                "image_urls": {},
            }
        ],
        "next_url": None,
    }
    page = BookmarkPage.model_validate(payload)
    assert page.next_bookmark_id is None
    assert page.illusts[0].original_urls == [
        "https://i.pximg.net/p0.jpg",
        "https://i.pximg.net/p1.jpg",
    ]


def test_bookmark_page_next_url_without_cursor():
    payload = {"illusts": [], "next_url": "https://app-api.pixiv.net/x?user_id=1"}
    assert BookmarkPage.model_validate(payload).next_bookmark_id is None


def test_illust_detail_parses():
    payload = {
        "illust": {
            "id": 5,
            "title": "d",
            "type": "ugoira",
            "page_count": 1,
            "user": {"id": 2, "name": "b"},
            "meta_single_page": {"original_image_url": "https://i.pximg.net/u0.jpg"},
            "image_urls": {},
        }
    }
    detail = IllustDetail.model_validate(payload)
    assert detail.illust.pid == 5
    assert detail.illust.type == "ugoira"


def test_ugoira_metadata_parses():
    payload = {
        "ugoira_metadata": {
            "zip_urls": {"medium": "https://i.pximg.net/ugoira600x600.zip"},
            "frames": [{"file": "000000.jpg", "delay": 100}],
        }
    }
    meta = UgoiraMetadata.model_validate(payload)
    assert meta.zip_url == "https://i.pximg.net/ugoira600x600.zip"
    assert meta.frames[0].delay == 100
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.pixiv.models'`

- [ ] **Step 3: 实现 models.py**

```python
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field


class PixivUser(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str = ""
    account: str = ""


class PixivTag(BaseModel):
    name: str = ""
    translated_name: str | None = None


class Illust(BaseModel):
    """Normalized view over a bookmark-list or detail illust object."""

    model_config = ConfigDict(populate_by_name=True)

    pid: int = Field(alias="id")
    title: str = ""
    description: str = ""
    type: str = "illust"
    page_count: int = 1
    width: int = 0
    height: int = 0
    x_restrict: int = 0
    sanity_level: int = 0
    illust_ai_type: int = 0
    total_view: int = 0
    total_bookmarks: int = 0
    create_date: datetime | None = None
    user: PixivUser
    tags: list[PixivTag] = Field(default_factory=list)
    meta_single_page: dict = Field(default_factory=dict)
    meta_pages: list[dict] = Field(default_factory=list)
    image_urls: dict = Field(default_factory=dict)

    @property
    def original_urls(self) -> list[str]:
        urls: list[str] = []
        for page in self.meta_pages or []:
            url = (page.get("image_urls") or {}).get("original")
            if url:
                urls.append(url)
        if urls:
            return urls
        single = (self.meta_single_page or {}).get("original_image_url")
        return [single] if single else []

    @property
    def preview_url(self) -> str | None:
        return self.image_urls.get("square_medium") or self.image_urls.get("medium")


class BookmarkPage(BaseModel):
    illusts: list[Illust] = Field(default_factory=list)
    next_url: str | None = None

    @property
    def next_bookmark_id(self) -> int | None:
        """Extract max_bookmark_id from next_url; None when no cursor remains."""
        if not self.next_url:
            return None
        values = parse_qs(urlsplit(self.next_url).query).get("max_bookmark_id")
        if not values or not values[0]:
            return None
        try:
            return int(values[0])
        except ValueError:
            return None


class IllustDetail(BaseModel):
    illust: Illust


class UgoiraFrame(BaseModel):
    file: str
    delay: int


class UgoiraMetadata(BaseModel):
    zip_url: str | None = None
    frames: list[UgoiraFrame] = Field(default_factory=list)

    @classmethod
    def from_response(cls, payload: dict) -> "UgoiraMetadata":
        meta = payload.get("ugoira_metadata") or {}
        zip_urls = meta.get("zip_urls") or {}
        return cls(
            zip_url=zip_urls.get("original") or zip_urls.get("medium"),
            frames=[UgoiraFrame.model_validate(f) for f in meta.get("frames") or []],
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_models.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/pixiv/models.py tests/test_models.py
git commit -m "feat: add pixiv response models with url normalization"
```

---

### Task 8: PixivClient（收藏列表 / 详情 / ugoira 元数据）

**Files:**
- Create: `src/pixiv_archive/pixiv/client.py`
- Modify: `src/pixiv_archive/pixiv/__init__.py`
- Test: `tests/test_client.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_client.py`：

```python
import httpx
import pytest
import respx

from pixiv_archive.pixiv.auth import APP_HEADERS, TokenProvider
from pixiv_archive.pixiv.client import BOOKMARKS_URL, CLIENT_UA, ILLUST_DETAIL_URL, UGOIRA_URL, PixivClient
from pixiv_archive.pixiv.errors import NotFoundError, PixivError

TOKEN_RESPONSE = {
    "response": {"access_token": "tok", "expires_in": 3600, "refresh_token": "r"}
}


def _bookmark_page(ids: list[int], cursor: int | None = None) -> dict:
    next_url = (
        f"https://app-api.pixiv.net/v1/user/bookmarks/illust?user_id=1&max_bookmark_id={cursor}"
        if cursor
        else None
    )
    return {
        "illusts": [
            {
                "id": pid,
                "title": f"t{pid}",
                "type": "illust",
                "page_count": 1,
                "user": {"id": 9, "name": "author"},
                "meta_single_page": {"original_image_url": f"https://i.pximg.net/{pid}.jpg"},
                "image_urls": {"square_medium": f"https://i.pximg.net/{pid}_sq.jpg"},
            }
            for pid in ids
        ],
        "next_url": next_url,
    }


@pytest.fixture
async def client():
    c = PixivClient(
        refresh_token="r",
        user_id=1,
        proxy=None,
        min_interval_ms=0,
        client=httpx.AsyncClient(),
    )
    yield c
    await c.aclose()


@respx.mock
async def test_list_bookmarks_uses_bearer_and_restrict(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    route = respx.get(BOOKMARKS_URL).mock(
        return_value=httpx.Response(200, json=_bookmark_page([101, 102], cursor=555))
    )
    page = await client.list_bookmarks(restrict="public")
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer tok"
    assert request.headers["user-agent"] == CLIENT_UA
    assert "restrict=public" in str(request.url)
    assert "user_id=1" in str(request.url)
    assert [i.pid for i in page.illusts] == [101, 102]
    assert page.next_bookmark_id == 555


@respx.mock
async def test_list_bookmarks_passes_cursor(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    route = respx.get(BOOKMARKS_URL).mock(
        return_value=httpx.Response(200, json=_bookmark_page([103]))
    )
    await client.list_bookmarks(restrict="private", max_bookmark_id=555)
    assert "max_bookmark_id=555" in str(route.calls[0].request.url)


@respx.mock
async def test_bookmarks_404_raises_not_found(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    respx.get(BOOKMARKS_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(NotFoundError):
        await client.list_bookmarks(restrict="public")


@respx.mock
async def test_bookmarks_retries_on_500(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    route = respx.get(BOOKMARKS_URL).mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, json=_bookmark_page([42])),
        ]
    )
    page = await client.list_bookmarks(restrict="public")
    assert page.illusts[0].pid == 42
    assert route.call_count == 2


@respx.mock
async def test_bookmarks_reauthenticates_on_401(client):
    routes = respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(
            200, json={"response": {"access_token": "tok2", "expires_in": 3600}}
        )
    )
    respx.get(BOOKMARKS_URL).mock(
        side_effect=[
            httpx.Response(401, json={"error": {"user_message": "unauthorized"}}),
            httpx.Response(200, json=_bookmark_page([7])),
        ]
    )
    page = await client.list_bookmarks(restrict="public")
    assert page.illusts[0].pid == 7
    assert routes.call_count == 2


@respx.mock
async def test_bookmarks_api_error_payload_raises(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    respx.get(BOOKMARKS_URL).mock(
        return_value=httpx.Response(
            200, json={"error": {"user_message": "不正确的请求。"}, "illusts": []}
        )
    )
    with pytest.raises(PixivError):
        await client.list_bookmarks(restrict="public")


@respx.mock
async def test_get_illust_detail(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    respx.get(ILLUST_DETAIL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "illust": {
                    "id": 77,
                    "title": "x",
                    "type": "illust",
                    "page_count": 1,
                    "user": {"id": 1, "name": "n"},
                    "meta_single_page": {"original_image_url": "https://i.pximg.net/77.jpg"},
                    "image_urls": {},
                }
            },
        )
    )
    detail = await client.get_illust_detail(77)
    assert detail.illust.pid == 77


@respx.mock
async def test_get_illust_detail_deleted(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    respx.get(ILLUST_DETAIL_URL).mock(
        return_value=httpx.Response(404, json={"error": {"user_message": "作品已删除"}})
    )
    with pytest.raises(NotFoundError):
        await client.get_illust_detail(77)


@respx.mock
async def test_get_ugoira_metadata(client):
    respx.post("https://oauth.secure.pixiv.net/auth/token").mock(
        return_value=httpx.Response(200, json=TOKEN_RESPONSE)
    )
    respx.get(UGOIRA_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "ugoira_metadata": {
                    "zip_urls": {"medium": "https://i.pximg.net/u.zip"},
                    "frames": [{"file": "000000.jpg", "delay": 33}],
                }
            },
        )
    )
    meta = await client.get_ugoira_metadata(5)
    assert meta.zip_url == "https://i.pximg.net/u.zip"
    assert meta.frames[0].delay == 33


@respx.mock
async def test_pixiv_client_uses_injected_http_client(monkeypatch):
    """The injected httpx client must be the one performing requests."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=TOKEN_RESPONSE)

    c = PixivClient(
        refresh_token="r",
        user_id=1,
        proxy=None,
        min_interval_ms=0,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        token = await c.get_access_token_for_test()
    finally:
        await c.aclose()
    assert token == "tok"
    assert seen and seen[0].startswith("https://oauth.secure.pixiv.net/")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.pixiv.client'`

- [ ] **Step 3: 实现 client.py**

```python
import httpx

from pixiv_archive.pixiv.auth import APP_HEADERS, TokenProvider
from pixiv_archive.pixiv.errors import AuthError, NetworkError, NotFoundError, PixivError, RateLimited
from pixiv_archive.pixiv.models import BookmarkPage, IllustDetail, UgoiraMetadata
from pixiv_archive.pixiv.ratelimit import RateLimiter, retry_async

API_BASE = "https://app-api.pixiv.net"
BOOKMARKS_URL = f"{API_BASE}/v1/user/bookmarks/illust"
ILLUST_DETAIL_URL = f"{API_BASE}/v1/illust/detail"
UGOIRA_URL = f"{API_BASE}/v1/ugoira/metadata"

CLIENT_UA = APP_HEADERS["User-Agent"]


class PixivClient:
    """Minimal async client for the pixiv app API."""

    def __init__(
        self,
        refresh_token: str,
        user_id: int,
        *,
        proxy: str | None = None,
        min_interval_ms: int = 800,
        on_refresh_token=None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.user_id = user_id
        self._owns_client = client is None
        self._http = client or httpx.AsyncClient(proxy=proxy, timeout=30.0)
        self._tokens = TokenProvider(
            refresh_token,
            proxy=proxy,
            on_refresh_token=on_refresh_token,
            client=self._http,
        )
        self._limiter = RateLimiter(min_interval_ms)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def get_access_token_for_test(self) -> str:
        return await self._tokens.get_access_token()

    async def _request(self, method: str, url: str, *, params: dict | None = None) -> dict:
        async def _once() -> dict:
            await self._limiter.acquire()
            token = await self._tokens.get_access_token()
            headers = dict(APP_HEADERS)
            headers["Authorization"] = f"Bearer {token}"
            try:
                response = await self._http.request(method, url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                raise NetworkError(f"request to {url} failed: {exc}") from exc

            if response.status_code == 401:
                self._tokens.invalidate()
                raise AuthError("access token rejected (401)")
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                raise RateLimited(
                    "rate limited (429)",
                    retry_after=float(retry_after) if retry_after else None,
                )
            if response.status_code >= 500:
                raise NetworkError(f"server error {response.status_code}")
            if response.status_code == 404:
                raise NotFoundError(f"not found: {url}")
            if response.status_code >= 400:
                raise PixivError(f"HTTP {response.status_code}: {response.text[:200]}")

            payload = response.json()
            if isinstance(payload, dict) and payload.get("error"):
                raise PixivError(str(payload["error"])[:300])
            return payload

        try:
            return await retry_async(_once, attempts=3, base_delay=0.6)
        except AuthError:
            # One retry after forced re-authentication.
            await self._tokens.get_access_token()
            return await retry_async(_once, attempts=2, base_delay=0.6)

    async def list_bookmarks(
        self, restrict: str, *, max_bookmark_id: int | None = None
    ) -> BookmarkPage:
        params: dict[str, str | int] = {"user_id": self.user_id, "restrict": restrict}
        if max_bookmark_id is not None:
            params["max_bookmark_id"] = max_bookmark_id
        payload = await self._request("GET", BOOKMARKS_URL, params=params)
        return BookmarkPage.model_validate(payload)

    async def get_illust_detail(self, illust_id: int) -> IllustDetail:
        payload = await self._request(
            "GET", ILLUST_DETAIL_URL, params={"illust_id": illust_id}
        )
        return IllustDetail.model_validate(payload)

    async def get_ugoira_metadata(self, illust_id: int) -> UgoiraMetadata:
        payload = await self._request("GET", UGOIRA_URL, params={"illust_id": illust_id})
        return UgoiraMetadata.from_response(payload)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_client.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/pixiv/client.py src/pixiv_archive/pixiv/__init__.py tests/test_client.py
git commit -m "feat: add async pixiv api client with pagination and error mapping"
```

---

### Task 9: 真实 API 集成测试

**Files:**
- Create: `tests/test_integration_live.py`

- [ ] **Step 1: 写集成测试**

`tests/test_integration_live.py`：

```python
"""Live integration tests against the real pixiv API.

Run manually with:
    uv run pytest tests/test_integration_live.py -m integration -v -s
These require PIXIV_REFRESH_TOKEN, PIXIV_USER_ID and network/proxy access.
"""

import pytest

from pixiv_archive.pixiv.client import PixivClient

pytestmark = pytest.mark.integration


@pytest.fixture
def live_settings():
    from pixiv_archive.config import Settings

    return Settings(_env_file=None)  # type: ignore[call-arg]


async def test_live_bookmark_page_parses_with_urls(live_settings):
    client = PixivClient(
        refresh_token=live_settings.pixiv_refresh_token,
        user_id=live_settings.pixiv_user_id,
        proxy=live_settings.pixiv_proxy,
        min_interval_ms=live_settings.api_min_interval_ms,
    )
    try:
        page = await client.list_bookmarks(restrict="public")
    finally:
        await client.aclose()

    assert len(page.illusts) > 0
    first = page.illusts[0]
    assert first.pid > 0
    assert first.original_urls, "bookmark list must carry original urls"
    assert first.preview_url
    print(f"\nfirst pid={first.pid} title={first.title!r} pages={first.page_count}")
    print(f"original={first.original_urls[0]}")
    print(f"next_bookmark_id={page.next_bookmark_id}")


async def test_live_pagination_is_descending_by_bookmark_time(live_settings):
    """The lists are ordered by bookmark time; ensure the cursor advances strictly."""
    client = PixivClient(
        refresh_token=live_settings.pixiv_refresh_token,
        user_id=live_settings.pixiv_user_id,
        proxy=live_settings.pixiv_proxy,
        min_interval_ms=live_settings.api_min_interval_ms,
    )
    try:
        first = await client.list_bookmarks(restrict="public")
        assert first.next_bookmark_id is not None
        second = await client.list_bookmarks(
            restrict="public", max_bookmark_id=first.next_bookmark_id
        )
    finally:
        await client.aclose()

    first_ids = {i.pid for i in first.illusts}
    second_ids = {i.pid for i in second.illusts}
    assert not (first_ids & second_ids), "pages must not overlap"


async def test_live_illust_detail_and_ugoira(live_settings):
    client = PixivClient(
        refresh_token=live_settings.pixiv_refresh_token,
        user_id=live_settings.pixiv_user_id,
        proxy=live_settings.pixiv_proxy,
        min_interval_ms=live_settings.api_min_interval_ms,
    )
    try:
        page = await client.list_bookmarks(restrict="public")
        detail = await client.get_illust_detail(page.illusts[0].pid)
        assert detail.illust.pid == page.illusts[0].pid

        search = await client._request(
            "GET",
            "https://app-api.pixiv.net/v1/search/illust",
            params={
                "word": "うごイラ",
                "search_target": "partial_match_for_tags",
                "sort": "date_desc",
                "filter": "for_ios",
            },
        )
        ugoira_id = next(
            i["id"] for i in search.get("illusts", []) if i.get("type") == "ugoira"
        )
        meta = await client.get_ugoira_metadata(ugoira_id)
        assert meta.zip_url
        assert len(meta.frames) > 0
        print(f"\nugoira {ugoira_id}: {len(meta.frames)} frames, zip={meta.zip_url}")
    finally:
        await client.aclose()
```

- [ ] **Step 2: 运行单元测试（确认集成测试被默认跳过）**

Run: `uv run pytest -v`
Expected: 所有单元测试通过，集成测试被 deselect

- [ ] **Step 3: 运行真实 API 集成测试**

Run（PowerShell，需本机代理）:
```powershell
$env:PIXIV_REFRESH_TOKEN="qLy8MsZ9XdxMM65DiPxF3hn4b18i4J82AkqFAmn8dkY"
$env:PIXIV_USER_ID="56269851"
$env:PIXIV_PROXY="http://127.0.0.1:7897"
$env:DATA_DIR="$env:TEMP\pixiv-archive-test"
uv run pytest tests/test_integration_live.py -m integration -v -s
```
Expected: 3 passed，输出首条收藏的原图 URL、ugoira 帧数

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_live.py
git commit -m "test: add live integration tests for pixiv api"
```

---

### Task 10: FastAPI 骨架与健康检查

**Files:**
- Create: `src/pixiv_archive/web/__init__.py`
- Create: `src/pixiv_archive/web/app.py`
- Create: `src/pixiv_archive/__main__.py`
- Test: `tests/test_web_health.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_web_health.py`：

```python
import httpx
import pytest


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PIXIV_REFRESH_TOKEN", "tok")
    monkeypatch.setenv("PIXIV_USER_ID", "1")
    from pixiv_archive.web.app import create_app

    return create_app()


async def test_health_endpoint(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pixiv_archive.web'`

- [ ] **Step 3: 实现 web 骨架**

`src/pixiv_archive/web/app.py`：

```python
from fastapi import FastAPI

from pixiv_archive import __version__
from pixiv_archive.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings(_env_file=None)  # type: ignore[call-arg]
    settings.ensure_dirs()

    app = FastAPI(title="Pixiv Archive", version=__version__)
    app.state.settings = settings

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = None  # replaced by uvicorn factory `create_app` in __main__
```

`src/pixiv_archive/web/__init__.py`：

```python
from pixiv_archive.web.app import create_app

__all__ = ["create_app"]
```

`src/pixiv_archive/__main__.py`：

```python
import uvicorn


def main() -> None:
    uvicorn.run("pixiv_archive.web.app:create_app", factory=True, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_health.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/pixiv_archive/web src/pixiv_archive/__main__.py tests/test_web_health.py
git commit -m "feat: add fastapi skeleton with health endpoint"
```

---

### Task 11: Dockerfile 与 docker-compose

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`
- Create: `.env.example`

- [ ] **Step 1: 写 .dockerignore 与 .env.example**

`.dockerignore`：

```
.venv
.git
.github
data
__pycache__
*.pyc
.pytest_cache
.ruff_cache
.mypy_cache
docs
.superpowers
```

`.env.example`：

```
# Required
PIXIV_REFRESH_TOKEN=your_refresh_token_here
PIXIV_USER_ID=12345678

# Network (required when pixiv is unreachable directly)
PIXIV_PROXY=
PIXIV_IMAGE_MIRROR=

# Web UI
AUTH_TOKEN=change-me

# Storage
DATA_DIR=/data

# Sync behaviour
SYNC_INTERVAL=6h
SYNC_FULL_CRON=
API_MIN_INTERVAL_MS=800
IMAGE_CONCURRENCY=4
DOWNLOAD_PREVIEWS=true
TZ=Asia/Shanghai
```

- [ ] **Step 2: 写 Dockerfile**

```dockerfile
# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.8 AS uv-bin

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY --from=uv-bin /uv /uvx /bin/
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# 依赖层：仅 pyproject + lock，利用 Docker 层缓存
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 应用层
COPY src ./src
COPY alembic.ini README.md ./
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app
USER appuser
ENV PATH="/app/.venv/bin:$PATH" \
    DATA_DIR=/data
EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1
CMD ["sh", "-c", "alembic upgrade head && python -m pixiv_archive"]
```

- [ ] **Step 3: 写 docker-compose.yml**

```yaml
services:
  app:
    build: .
    image: ghcr.io/OWNER/pixiv-collection-archive:latest
    container_name: pixiv-archive
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      DATA_DIR: /data
      TZ: Asia/Shanghai
    volumes:
      - ./data:/data
```

- [ ] **Step 4: 构建并验证镜像**

Run: `docker build -t pixiv-archive:test .`
Expected: 构建成功

Run: `docker run --rm -e PIXIV_REFRESH_TOKEN=x -e PIXIV_USER_ID=1 -e DATA_DIR=/tmp/d pixiv-archive:test python -c "import pixiv_archive, fastapi, sqlalchemy; print('imports ok')"`
Expected: 输出 `imports ok`

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml .dockerignore .env.example
git commit -m "feat: add multi-stage dockerfile and compose file"
```

---

### Task 12: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: 写 ci.yml**

```yaml
name: CI

on:
  push:
    branches: ["**"]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          version: "0.5.x"
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: uv sync --frozen
      - name: Lint
        run: |
          uv run ruff check src tests
          uv run ruff format --check src tests
      - name: Typecheck
        run: uv run mypy
      - name: Tests
        run: uv run pytest -q

  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/build-push-action@v6
        with:
          context: .
          push: false
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

- [ ] **Step 2: 本地运行与 CI 相同的检查**

Run: `uv run ruff check src tests; uv run ruff format --check src tests; uv run mypy; uv run pytest -q`
Expected: 全部通过（如有格式问题运行 `uv run ruff format src tests` 修复后重跑）

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint, typecheck, test and docker build workflow"
```

---

### Task 13: README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 写 README**

````markdown
# Pixiv Collection Archive

自托管的 pixiv 收藏同步与备份服务。**核心特性：完整保留收藏顺序**。

- 收藏顺序模型基于稀疏 rank + 位置快照（pixiv API 不提供单条收藏时间戳）
- 元数据同步与图片下载解耦：先秒级建索引，再按范围分批下载
- ugoira 动图保留原始 zip 并转码为 mp4
- React WebUI：画廊 / 详情 / 下载队列 / 统计 / 导出
- 单容器 + SQLite，GHCR 镜像

## 状态

- [x] 项目基础 + pixiv API 层（本仓库当前进度）
- [ ] 阶段 A：元数据同步
- [ ] 阶段 B：图片下载
- [ ] Web API 与前端
- [ ] 发布

## 快速开始（开发）

```bash
uv sync
cp .env.example .env  # 填写 PIXIV_REFRESH_TOKEN / PIXIV_USER_ID
uv run pytest
uv run python -m pixiv_archive
```

真实 API 集成测试：

```bash
uv run pytest tests/test_integration_live.py -m integration -v -s
```

## Docker

```bash
docker compose up -d --build
```

数据保存在 `./data`（SQLite + 原图 + 缩略图）。

## 文档

设计文档：`docs/superpowers/specs/2026-09-20-pixiv-collection-archive-design.md`

## 配置

见 `.env.example`。
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add readme with quickstart and status"
```

---

## 计划自审

**Spec 覆盖检查：**

| Spec 章节 | 对应任务 | 状态 |
| --- | --- | --- |
| §3 技术选型（uv/FastAPI/httpx/SQLAlchemy/Alembic） | Task 1–4 | ✅ |
| §6 DB 模型（本计划只建最小集：illust/author/bookmark/app_setting） | Task 3–4 | ✅（其余表在计划 2/3） |
| §7.1 认证（缓存、回写、失败处理） | Task 6 | ✅ |
| §7.2 限速与重试（串行 800ms、退避、429、401） | Task 5、8 | ✅ |
| §7.3 代理与镜像（代理已实现；镜像替换在计划 3 下载层） | Task 8 | ⏭ 部分 |
| §7.4 异常树 | Task 5 | ✅ |
| §9 `/api/health` | Task 10 | ✅ |
| §11 配置项 | Task 2 | ✅ |
| §12.1 Dockerfile | Task 11 | ✅ |
| §12.2 docker-compose | Task 11 | ✅ |
| §12.3 ci.yml | Task 12 | ✅ |
| §12.4 测试策略（单元 + 集成） | Task 5–9 | ✅ |
| §13 项目结构 | Task 1–10 | ✅ |
| §1.1 目标：uv / 容器化 / 结构 | Task 1、11、13 | ✅ |

**未覆盖（属于后续计划，符合拆分）：** 阶段 A 同步与 rank（计划 2）、阶段 B 下载与镜像（计划 3）、Web API 与前端（计划 4）、docker.yml 发布（计划 5）。

**占位符扫描：** 无 TBD/TODO；每个代码步骤均含完整代码。

**类型一致性检查：**
- `BookmarkPage.next_bookmark_id` 在 Task 7 定义、Task 8/9 使用 ✅
- `PixivClient.list_bookmarks/get_illust_detail/get_ugoira_metadata` 命名在 Task 8 定义、Task 9 使用 ✅
- `Settings.pixiv_proxy/pixiv_user_id` 在 Task 2 定义、Task 9（`live_settings.pixiv_proxy`）使用 ✅
- `Database.session()/create_all()/update_setting()/get_setting()` 在 Task 3 定义 ✅
- `TokenProvider` 构造参数（`refresh_token/proxy/on_refresh_token/client`）在 Task 6 定义、Task 8 使用 ✅

**已知偏差：** Task 8 测试 `test_pixiv_proxy_is_used` 使用内部辅助方法 `get_access_token_for_test`，该方法是实现的一部分（已包含在实现代码中），用于验证注入 client 生效。
