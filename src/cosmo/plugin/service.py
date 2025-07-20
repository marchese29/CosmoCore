import asyncio as aio
import uuid
from collections.abc import Callable
from types import NoneType
from typing import cast

from cosmo.engine.core import ConditionEngine
from cosmo.plugin import CosmoPlugin


class PluginService:
    """Service supporting plugins"""

    def __init__(self, engine: ConditionEngine):
        self._engine = engine

        # State Tracking
        self._plugins: dict[str, CosmoPlugin] = {}
        self._utils: dict[type, object] = {}
        self._tasks: dict[str, aio.Task[None]] = {}

    def register_plugin(self, plugin: CosmoPlugin) -> str:
        """Registers the provided plugin and runs it."""
        plugin_id = str(uuid.uuid4())
        self._plugins[plugin_id] = plugin

        util = plugin.get_rule_utility()
        if util is not None:
            self._utils[type(util)] = util

        self._tasks[plugin_id] = aio.create_task(self._run_plugin(plugin))
        self._tasks[plugin_id].add_done_callback(
            self._on_plugin_complete(plugin_id, type(util))
        )
        return plugin_id

    def util_for_type[T: object](self, util_type: type[T]) -> T | None:
        """Returns the rule-building utility for the given type."""
        if util_type in self._utils:
            return cast(T, self._utils[util_type])
        return None

    async def _run_plugin(self, plugin: CosmoPlugin):
        event_generator = await plugin.run()
        async for impacted_conditions in event_generator:
            self._engine.report_condition_event(impacted_conditions)

    def _on_plugin_complete(
        self, source_id: str, util_type: type
    ) -> Callable[[aio.Task[None]], None]:
        def inner(_: aio.Task[None]):
            del self._plugins[source_id]
            if util_type is not NoneType:
                del self._utils[util_type]
            del self._tasks[source_id]

        return inner
