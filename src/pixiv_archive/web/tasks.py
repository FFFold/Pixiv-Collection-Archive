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
    """Passed to task callables to report progress and observe cancellation."""

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
        if any(
            record.kind == kind and record.status == "running" for record in self._records.values()
        ):
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
