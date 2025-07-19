import asyncio as aio
from datetime import datetime, time, timedelta
from typing import override

from cosmo.engine.core import ConditionEngine
from cosmo.engine.model import EngineCondition


class AbstractCondition(EngineCondition):
    def __init__(self):
        super().__init__()

    def __bool__(self) -> bool:
        raise NotImplementedError("Use utils.check(<condition>) to evaluate conditions")

    @property
    @override
    def timeout(self) -> timedelta | None:
        return getattr(self, "_timeout", None)

    @timeout.setter
    def timeout(self, value: timedelta):
        self._timeout = value

    @property
    @override
    def duration(self) -> timedelta | None:
        return getattr(self, "_duration", None)

    @duration.setter
    def duration(self, value: timedelta):
        self._duration = value


class BooleanCondition(AbstractCondition):
    """Represents a boolean condition with "and", "or", or "not"."""

    def __init__(self, *conditions: AbstractCondition, operator: str):
        super().__init__()
        self._conditions: dict[int, tuple[AbstractCondition, bool]] = {}
        for condition in conditions:
            self._conditions[condition.instance_id] = (condition, False)
        if operator == "not" and len(self._conditions) != 1:
            raise ValueError("Boolean operator 'not' requires exactly one subcondition")
        self._operator = operator

    @property
    @override
    def identifier(self) -> str:
        inner = f" {self._operator} ".join(
            [v[0].identifier for v in self._conditions.values()]
        )
        return f"({inner})"

    @property
    @override
    def subconditions(self) -> list[EngineCondition]:
        return [c for (c, _) in self._conditions.values()]

    @override
    def on_condition_event(self, condition: EngineCondition, state: bool):
        self._conditions[condition.instance_id] = (
            self._conditions[condition.instance_id][0],
            state,
        )

    @override
    def initialize(self, states: list[tuple[EngineCondition, bool]]):
        for subcondition, state in states:
            self._conditions[subcondition.instance_id] = (
                self._conditions[subcondition.instance_id][0],
                state,
            )

    @override
    def evaluate(self) -> bool:
        match self._operator:
            case "and":
                return all(state for (_, state) in self._conditions.values())
            case "or":
                return any(state for (_, state) in self._conditions.values())
            case "not":
                return not [state for (_, state) in self._conditions.values()][0]
            case _:
                raise ValueError(f"Unknown operator: {self._operator}")


class AlwaysFalseCondition(AbstractCondition):
    """A condition that is always false. Used for error cases."""

    def __init__(self, reason: str | None):
        super().__init__()
        self._reason = reason or "always_false"

    @property
    @override
    def identifier(self) -> str:
        return f"always_false({self._reason})"

    @override
    def evaluate(self) -> bool:
        return False


class AlwaysTrueCondition(AbstractCondition):
    """A condition that is always false. Used for error cases."""

    def __init__(self, reason: str | None):
        super().__init__()
        self._reason = reason or "always_true"

    @property
    @override
    def identifier(self) -> str:
        return f"always_true({self._reason})"

    @override
    def evaluate(self) -> bool:
        return True


class RuleUtilities:
    """Utilities for work with rules."""

    def __init__(self, engine: ConditionEngine):
        self._engine = engine

    def all_of(self, *conditions: AbstractCondition) -> AbstractCondition:
        """Condition that checks if all subconditions are true."""
        return BooleanCondition(*conditions, operator="and")

    def any_of(self, *conditions: AbstractCondition) -> AbstractCondition:
        """Condition that checks if any subcondition is true."""
        return BooleanCondition(*conditions, operator="or")

    def is_not(self, condition: AbstractCondition) -> AbstractCondition:
        """Condition that checks if a subcondition is false."""
        return BooleanCondition(condition, operator="not")

    def false(self, reason: str | None = None) -> AbstractCondition:
        """Condition that is always false."""
        return AlwaysFalseCondition(reason)

    def true(self, reason: str | None = None) -> AbstractCondition:
        """Condition that is always true."""
        return AlwaysTrueCondition(reason)

    async def wait(self, for_time: timedelta):
        """Wait for a period of time.

        Args:
            for_time: The amount of time to wait for
        """
        await aio.sleep(for_time.total_seconds())

    async def wait_until(self, t: time):
        """Wait until a given time.

        Args:
            t: The time to wait until.
        """
        now = datetime.now()
        target_time = datetime.combine(now.date(), t)
        if target_time < now:
            target_time = datetime.combine(now.date().replace(day=now.day + 1), t)
        wait_time = target_time - now
        await aio.sleep(wait_time.total_seconds())

    async def wait_for(
        self,
        condition: AbstractCondition,
        timeout: timedelta | None = None,
        for_duration: timedelta | None = None,
    ) -> bool:
        """Wait for a condition to be true.

        Args:
            condition: The condition to wait for.
            timeout: The timeout for the condition to be true.
            for_duration: How long the condition must be true for (default is immediate)
        Returns:
            True if the condition is true after waiting, False if otherwise
        """
        if timeout is not None and for_duration is not None and timeout <= for_duration:
            raise ValueError("Timeout must be longer than duration")

        if for_duration is not None:
            condition.duration = for_duration

        return await self._wait_for_condition(condition, timeout)

    async def _wait_for_condition(
        self,
        condition: AbstractCondition,
        timeout: timedelta | None = None,
    ) -> bool:
        """Internal helper to wait for a condition with optional timeout.

        Args:
            condition: The condition to wait for
            timeout: Optional timeout for the condition

        Returns:
            True if the condition was met, False if timed out
        """
        event = aio.Event()
        timeout_event = None
        if timeout is not None:
            timeout_event = aio.Event()
            condition.timeout = timeout

        self._engine.add_condition(
            condition, condition_event=event, timeout_event=timeout_event
        )

        # Wait for the condition to become true or for timeout
        if timeout_event is not None:
            tasks = [
                aio.create_task(event.wait(), name="condition"),
                aio.create_task(timeout_event.wait(), name="timeout"),
            ]
            done, pending = await aio.wait(tasks, return_when=aio.FIRST_COMPLETED)
            # Cancel any pending tasks
            for task in pending:
                task.cancel()

            # Remove the condition from tracking
            self._engine.remove_condition(condition)

            # Check which task completed
            completed_task = done.pop()
            return completed_task.get_name() != "timeout"
        else:
            await event.wait()
            # Remove the condition from tracking
            self._engine.remove_condition(condition)
            return True
