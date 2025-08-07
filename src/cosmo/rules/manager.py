import asyncio as aio
import inspect
import logging
import uuid
from collections.abc import Callable
from datetime import datetime
from inspect import Parameter, isclass
from typing import get_type_hints

from cosmo.engine.core import ConditionEngine
from cosmo.plugin.builtin import RuleUtils
from cosmo.plugin.model import AbstractCondition
from cosmo.plugin.service import PluginService
from cosmo.rules.model import (
    RuleRoutine,
    RuleTimeProvider,
    RuleTriggerProvider,
    TimerRule,
    TriggerRule,
)

logger = logging.getLogger(__name__)


class RuleManager:
    """Manager for the running rules in Cosmo's core."""

    def __init__(self, engine: ConditionEngine, plugin_service: PluginService):
        self._engine = engine
        self._plugins = plugin_service

        self._tasks: dict[str, aio.Task[None]] = {}
        self._suspended_rules: set[str] = set()

    def install_trigger_rule(
        self, rule: TriggerRule, task_id: str | None = None
    ) -> aio.Task[None]:
        task = aio.create_task(
            self._run_triggered_rule(rule.trigger_provider, rule.routine)
        )
        if task_id is None:
            task_id = str(uuid.uuid4())
        task.set_name(task_id)
        self._tasks[task_id] = task
        task.add_done_callback(self._on_task_complete())
        return task

    def install_timed_rule(
        self, rule: TimerRule, task_id: str | None = None
    ) -> aio.Task[None]:
        task = aio.create_task(self._run_timed_rule(rule.time_provider, rule.routine))
        if task_id is None:
            task_id = str(uuid.uuid4())
        task.set_name(task_id)
        self._tasks[task_id] = task
        task.add_done_callback(self._on_task_complete())
        return task

    def uninstall_rule(self, rule_id: str) -> bool:
        if rule_id not in self._tasks:
            # No rule to remove
            return False

        task = self._tasks[rule_id]
        if not task.done():
            # Technically not possible to get here since done triggers removal
            # but we'll handle it anyways just in case
            task.cancel()

        # Rule was removed
        return True

    def get_all_rules(self) -> list[str]:
        """Get a list of all currently installed and running rule IDs.

        Returns:
            A list of rule IDs for all currently active rules
        """
        return list(self._tasks.keys())

    def suspend_rule(self, rule_id: str) -> bool:
        """Suspend a rule from executing its actions.

        Args:
            rule_id: The ID of the rule to suspend

        Returns:
            True if the rule was suspended, False if the rule doesn't exist
        """
        if rule_id not in self._tasks:
            return False

        self._suspended_rules.add(rule_id)
        return True

    def resume_rule(self, rule_id: str) -> bool:
        """Resume a suspended rule.

        Args:
            rule_id: The ID of the rule to resume

        Returns:
            True if the rule was resumed, False if the rule doesn't exist or
            wasn't suspended
        """
        if rule_id not in self._tasks:
            return False

        was_suspended = rule_id in self._suspended_rules
        self._suspended_rules.discard(rule_id)
        return was_suspended

    def is_rule_suspended(self, rule_id: str) -> bool:
        """Check if a rule is currently suspended.

        Args:
            rule_id: The ID of the rule to check

        Returns:
            True if the rule exists and is suspended, False otherwise
        """
        return rule_id in self._suspended_rules

    async def run_action_once(self, action: RuleRoutine) -> None:
        """Execute a rule action once immediately without creating a persistent task.

        Args:
            action: The rule routine to execute

        Raises:
            ValueError: If the action has invalid parameters or utility dependencies
        """
        # Resolve utilities for the action
        action_args = self._resolve_utilities(action)

        # Execute the action immediately
        await action(*action_args)

    def _on_task_complete(self) -> Callable[[aio.Task[None]], None]:
        def inner(task: aio.Task[None]):
            # TODO: Handle task exception exits
            task_name = task.get_name()
            del self._tasks[task_name]
            # Clean up suspended rules set
            self._suspended_rules.discard(task_name)

        return inner

    def _resolve_utilities(self, f: Callable) -> list[object]:
        result = []
        signature = inspect.signature(f)
        type_hints = get_type_hints(f)
        seen_types: set[type] = set()
        for param_name, param in signature.parameters.items():
            # Arguments must be positional with type hints and no defaults
            if param.kind in (Parameter.KEYWORD_ONLY, Parameter.VAR_KEYWORD):
                raise ValueError(f"Keyword-only parameter {param_name} is not allowed")
            if param.default != inspect._empty:
                raise ValueError(f"Default value for {param_name} is not allowed")
            if param.annotation == inspect._empty:
                raise ValueError(f"Type hint for {param_name} is missing")

            # Get the type hint
            type_hint = type_hints.get(param_name)
            if type_hint is None:
                raise ValueError(f"Type hint for {param_name} is missing")
            if not isclass(type_hint):
                raise ValueError(f"Type hint for {param_name} is not a class")

            # A utility may only be declared once
            if type_hint in seen_types:
                raise ValueError(f"Utility type {type_hint.__name__} is already declared")
            seen_types.add(type_hint)

            # Resolve the utility from the plugin (or the builtin CosmoUtils)
            if type_hint == RuleUtils:
                result.append(RuleUtils(self._engine))
            else:
                utility = self._plugins.util_for_type(type_hint)
                if utility is None:
                    raise ValueError(
                        f"No utility registered for type {type_hint.__name__}"
                    )
                result.append(utility)
        return result

    async def _run_triggered_rule(
        self, trigger_provider: RuleTriggerProvider, action: RuleRoutine
    ):
        while True:
            # Build the trigger
            trigger_args = self._resolve_utilities(trigger_provider)
            trigger = trigger_provider(*trigger_args)
            if not isinstance(trigger, AbstractCondition):
                raise ValueError("Rule trigger didn't return an AbstractCondition")

            if trigger.timeout is not None:
                raise ValueError("Rule triggers cannot incorporate a timeout")

            # Register the condition with the engine
            event = aio.Event()
            self._engine.add_condition(trigger, event)

            # Wait for the rule to fire
            await event.wait()

            # Remove the trigger while running the action
            self._engine.remove_condition(trigger)

            # Get the current task name (rule ID)
            current_task = aio.current_task()
            rule_id = current_task.get_name() if current_task else "unknown"

            # Check if rule is suspended before executing action
            if rule_id in self._suspended_rules:
                logger.info(
                    f"Rule {rule_id} triggered but is suspended, "
                    "skipping action execution"
                )
                continue

            # Run the rule's action
            action_args = self._resolve_utilities(action)
            await action(*action_args)

    async def _run_timed_rule(self, time_provider: RuleTimeProvider, action: RuleRoutine):
        while (next_trigger := time_provider()) is not None:
            if not isinstance(next_trigger, datetime):
                raise ValueError("Time trigger must be a datetime instance")

            # You get a few tries to give me a valid trigger
            i = 0
            while next_trigger is not None and next_trigger <= datetime.now() and i < 2:
                i += 1
                next_trigger = time_provider()
                if not isinstance(next_trigger, datetime):
                    raise ValueError("Time trigger must be a datetime instance")

            if next_trigger is None or next_trigger <= datetime.now():
                # If still no valid trigger, it's time to exit
                return

            # Wait for trigger to fire
            await aio.sleep((next_trigger - datetime.now()).total_seconds())

            # Get the current task name (rule ID)
            current_task = aio.current_task()
            rule_id = current_task.get_name() if current_task else "unknown"

            # Check if rule is suspended before executing action
            if rule_id in self._suspended_rules:
                logger.info(
                    f"Timed rule {rule_id} triggered but is suspended, "
                    "skipping action execution"
                )
                continue

            # Run the action
            action_args = self._resolve_utilities(action)
            await action(*action_args)
