import asyncio
from datetime import UTC, datetime

import pytest

from pixiv_archive.web.sse import EventBus, format_sse
from pixiv_archive.web.tasks import TaskManager, TaskRecord


def test_format_sse_shape():
    text = format_sse("progress", {"done": 1})
    assert text.startswith("event: progress\n")
    assert 'data: {"done": 1}' in text
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


async def test_event_stream_formats_and_keepalives():
    bus = EventBus()
    queue = bus.subscribe()
    bus.publish("progress", {"n": 1})
    frames: list[str] = []

    async def consume():
        from pixiv_archive.web.sse import event_stream

        async for frame in event_stream(bus, queue, keepalive=0.05):
            frames.append(frame)
            if len(frames) >= 2:
                break

    await asyncio.wait_for(consume(), timeout=2)
    assert "event: progress" in frames[0]
    assert ": keepalive" in frames[1]


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


async def test_task_manager_cancel_marks_record():
    manager = TaskManager()

    async def job(ctx) -> dict:
        for index in range(10):
            ctx.progress("working", index, 10, "tick")
            await asyncio.sleep(0.05)
        return {}

    task_id = manager.start("download", job)
    await asyncio.sleep(0.06)
    assert manager.cancel(task_id) is True
    await manager.wait(task_id)
    record = manager.get(task_id)
    assert record is not None
    assert record.status == "cancelled"


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
