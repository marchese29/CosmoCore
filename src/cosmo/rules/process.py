import asyncio as aio
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from cosmo.engine.builtin import AbstractCondition, RuleUtilities
from cosmo.engine.core import ConditionEngine

RuleTriggerProvider = Callable[[RuleUtilities], AbstractCondition]
RuleTimeProvider = Callable[[], datetime | None]
RuleRoutine = Callable[[RuleUtilities], Awaitable[None]]


class Rule:
    """Base class for rules."""

    def __init__(self, routine: RuleRoutine):
        self._routine = routine

    @property
    def routine(self) -> RuleRoutine:
        return self._routine


class TimerRule(Rule):
    """A rule whose action is invoked at scheduled times."""

    def __init__(
        self,
        routine: Callable[[RuleUtilities], Awaitable[None]],
        time_provider: RuleTimeProvider,
    ):
        super().__init__(routine)
        self._time_provider = time_provider

    @property
    def time_provider(self) -> RuleTimeProvider:
        return self._time_provider


class TriggerRule(Rule):
    """A rule whose action is invoked via a conditional trigger."""

    def __init__(self, routine: RuleRoutine, trigger_provider: RuleTriggerProvider):
        super().__init__(routine)
        self._trigger_provider = trigger_provider

    @property
    def trigger_provider(self) -> RuleTriggerProvider:
        return self._trigger_provider


class RuleManager:
    """Manager for the running rules in Cosmo's core."""

    def __init__(self, engine: ConditionEngine):
        self._engine = engine

        self._tasks: dict[str, aio.Task[None]]

    def install_trigger_rule(self, rule: TriggerRule) -> aio.Task[None]:
        task = aio.create_task(
            self._run_triggered_rule(rule.trigger_provider, rule.routine)
        )
        task_id = str(uuid.uuid4())
        task.set_name(task_id)
        self._tasks[task_id] = task
        task.add_done_callback(self._on_task_complete())
        return task

    def install_timed_rule(self, rule: TimerRule) -> aio.Task[None]:
        task = aio.create_task(self._run_timed_rule(rule.time_provider, rule.routine))
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

    def _on_task_complete(self) -> Callable[[aio.Task[None]], None]:
        def inner(task: aio.Task[None]):
            # TODO: Handle task exception exits
            del self._tasks[task.get_name()]

        return inner

    async def _run_triggered_rule(
        self, trigger_provider: RuleTriggerProvider, action: RuleRoutine
    ):
        while True:
            # Build the trigger
            trigger = trigger_provider(RuleUtilities(self._engine))

            if trigger.timeout is not None:
                raise ValueError("Rule triggers cannot incorporate a timeout")

            # Register the condition with the engine
            event = aio.Event()
            self._engine.add_condition(trigger, event)

            # Wait for the rule to fire
            await event.wait()

            # Remove the trigger while running the action
            self._engine.remove_condition(trigger)

            # Run the rule's action
            await action(RuleUtilities(self._engine))

    async def _run_timed_rule(self, time_provider: RuleTimeProvider, action: RuleRoutine):
        while (next_trigger := time_provider()) is not None:
            # You get a few tries to give me a valid trigger
            i = 0
            while next_trigger is not None and next_trigger <= datetime.now() and i < 2:
                i += 1
                next_trigger = time_provider()

            if next_trigger is None or next_trigger <= datetime.now():
                # If still no valid trigger, it's time to exit
                return

            # Wait for trigger to fire
            await aio.sleep((next_trigger - datetime.now()).total_seconds())

            # Run the action
            await action(RuleUtilities(self._engine))
