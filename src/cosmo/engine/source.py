import asyncio as aio
import uuid
from collections.abc import Awaitable, Callable

from cosmo.engine.builtin import AbstractCondition
from cosmo.engine.core import ConditionEngine

EventSource = Callable[[], Awaitable[list[AbstractCondition]]]


class EventSourceService:
    """Service supporting the origination of events"""

    def __init__(self, engine: ConditionEngine):
        self._engine = engine

        # State Tracking
        self._sources: dict[str, EventSource] = {}
        self._tasks: dict[str, aio.Task[None]] = {}

    def register_source(self, event_source: EventSource) -> str:
        source_id = str(uuid.uuid4())
        self._sources[source_id] = event_source
        self._tasks[source_id] = aio.create_task(self._run_source(event_source))
        self._tasks[source_id].add_done_callback(self._on_source_complete(source_id))
        return source_id

    async def _run_source(self, event_source: EventSource):
        while True:
            impacted = await event_source()
            if len(impacted) > 0:
                self._engine.report_condition_event(impacted)

    def _on_source_complete(self, source_id: str) -> Callable[[aio.Task[None]], None]:
        def inner(_: aio.Task[None]):
            del self._sources[source_id]
            del self._tasks[source_id]

        return inner
