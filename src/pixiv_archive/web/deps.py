from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.config import Settings
from pixiv_archive.db.engine import Database


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_database(request: Request) -> Database:
    return request.app.state.db  # type: ignore[no-any-return]


def get_tasks(request: Request) -> Any:
    return request.app.state.tasks


def get_events(request: Request) -> Any:
    return request.app.state.events


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.db
    async with database.session() as session:
        yield session
