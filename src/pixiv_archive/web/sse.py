import asyncio
import contextlib
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
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

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
