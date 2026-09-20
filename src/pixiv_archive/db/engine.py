from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pixiv_archive.db.base import Base


class Database:
    """Owns the async engine and session factory for a SQLite file."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.path}")

        @event.listens_for(self.engine.sync_engine, "connect")
        def _set_pragma(dbapi_conn: Any, _record: Any) -> None:  # pragma: no cover - driver level
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
