from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from pixiv_archive.config import Settings
from pixiv_archive.db.engine import Database
from pixiv_archive.web.sse import EventBus
from pixiv_archive.web.tasks import TaskManager


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_database(request: Request) -> Database:
    database: Database = request.app.state.db
    return database


def get_tasks(request: Request) -> TaskManager:
    tasks: TaskManager = request.app.state.tasks
    return tasks


def get_events(request: Request) -> EventBus:
    events: EventBus = request.app.state.events
    return events


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.db
    async with database.session() as session:
        yield session
