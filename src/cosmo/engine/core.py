import asyncio as aio
from collections import deque
from collections.abc import Callable, Sequence
from enum import Enum

from cosmo.engine.model import EngineCondition


class ConditionState(Enum):
    TIMEOUT = -1
    OFF = 0
    PENDING = 1
    ON = 2

    def is_on(self) -> bool:
        return self.value == 2


class ConditionNotifier:
    """Notifier for conditions."""

    def __init__(
        self,
        condition: EngineCondition,
        event: aio.Event | None = None,
        to_event: aio.Event | None = None,
    ):
        self._condition = condition
        self._event = event
        self._to_event = to_event

    @property
    def condition(self) -> EngineCondition:
        """Condition that triggered the event."""
        return self._condition

    def notify(self):
        """Notifies the condition."""
        if self._event is not None:
            self._event.set()

    def notify_timeout(self):
        """Notifies the condition of a timeout."""
        if self._to_event is not None:
            self._to_event.set()


class ConditionEngine:
    def __init__(self):
        self._conditions: dict[int, tuple[ConditionNotifier, ConditionState]] = {}
        self._dependencies: dict[int, set[int]] = {}
        self._duration_timers: dict[int, aio.Task[None]] = {}
        self._timeout_timers: dict[int, aio.Task[None]] = {}

    def add_condition(
        self,
        condition: EngineCondition,
        condition_event: aio.Event | None = None,
        timeout_event: aio.Event | None = None,
    ):
        # Initialize subconditions
        for subcondition in condition.subconditions:
            self.add_condition(subcondition)
            if subcondition.instance_id not in self._dependencies:
                self._dependencies[subcondition.instance_id] = set()
            self._dependencies[subcondition.instance_id].add(condition.instance_id)

        # Initialize our new condition
        states = [
            (c, self._conditions[c.instance_id][1].is_on())
            for c in condition.subconditions
        ]
        condition.initialize(states)

        # Record the current state of this condition
        notifier = ConditionNotifier(condition, condition_event, timeout_event)
        state = condition.evaluate()

        # If the condition starts out "off", or it starts out as "true" but has a duration
        # requirement, then we need to check for timeouts
        if (
            state is False or (state is True and condition.duration is not None)
        ) and condition.timeout is not None:
            timeout_task = aio.create_task(aio.sleep(condition.timeout.total_seconds()))
            self._timeout_timers[condition.instance_id] = timeout_task
            timeout_task.add_done_callback(self._on_condition_timeout(notifier))

        if state is True:
            if condition.duration is not None:
                self._conditions[condition.instance_id] = (
                    notifier,
                    ConditionState.PENDING,
                )
                duration_task = aio.create_task(
                    aio.sleep(condition.duration.total_seconds())
                )
                self._duration_timers[condition.instance_id] = duration_task
                duration_task.add_done_callback(self._on_duration_timer(notifier))
            else:
                # Condition starts as true, we don't fire notification here per policy
                self._conditions[condition.instance_id] = (notifier, ConditionState.ON)
        else:
            # Evaluating to false means we're off regardless of anything
            self._conditions[condition.instance_id] = (notifier, ConditionState.OFF)

    def remove_condition(self, condition: EngineCondition):
        if condition.instance_id in self._conditions:
            del self._conditions[condition.instance_id]
        if condition.instance_id in self._dependencies:
            del self._dependencies[condition.instance_id]

        # Cancel timeout timer if it exists
        if condition.instance_id in self._timeout_timers:
            task = self._timeout_timers[condition.instance_id]
            task.cancel()
            del self._timeout_timers[condition.instance_id]
        if condition.instance_id in self._duration_timers:
            task = self._duration_timers[condition.instance_id]
            task.cancel()
            del self._duration_timers[condition.instance_id]

        # Let the condition know it was removed
        condition.removed()

        # Remove any sub-conditions
        for subcondition in condition.subconditions:
            self.remove_condition(subcondition)

    def report_condition_event(self, conditions: Sequence[EngineCondition]):
        """Reports an event involving the provided conditions"""
        # Get a snapshot of the previous state so we can compare for updates
        previous_state = {
            cond.instance_id: self._conditions[cond.instance_id][1] for cond in conditions
        }

        notifiers = [self._conditions[cond.instance_id][0] for cond in conditions]

        # Traverse with BFS to find all dependencies.  No visited set since all edges need
        # to be traversed for a complete and correct state picture
        work = deque(notifiers)
        touched_conditions: set[int] = set()
        while len(work) > 0:
            current = work.popleft()
            curr_cond = current.condition
            current_instance_id = curr_cond.instance_id
            touched_conditions.add(current_instance_id)

            current_state = self._conditions[current_instance_id][1]
            state = curr_cond.evaluate()
            new_state = ConditionState.OFF

            # If current state is off and becomes true but needs a duration:
            if (
                current_state == ConditionState.OFF
                and state is True
                and curr_cond.duration is not None
            ):
                new_state = ConditionState.PENDING
                self._conditions[current_instance_id] = (current, new_state)

                duration_task = aio.create_task(
                    aio.sleep(curr_cond.duration.total_seconds())
                )
                self._duration_timers[current_instance_id] = duration_task
                duration_task.add_done_callback(self._on_duration_timer(current))

            # If state is off and becomes true with no duration:
            elif current_state == ConditionState.OFF and state is True:
                new_state = ConditionState.ON
                self._conditions[current_instance_id] = (current, new_state)

            for parent_id in self._dependencies.get(current_instance_id, []):
                if parent_id in self._conditions:
                    parent_cond = self._conditions[parent_id][0].condition
                    parent_cond.on_condition_event(current.condition, new_state.is_on())
                    work.append(self._conditions[parent_id][0])

        # Handle any state changes
        for notifier in [self._conditions[cid][0] for cid in touched_conditions]:
            if notifier.condition.instance_id not in self._conditions:
                continue
            curr = self._conditions[notifier.condition.instance_id][1]
            prev = previous_state[notifier.condition.instance_id]

            if prev == ConditionState.OFF and curr == ConditionState.ON:
                # Remove the timeout timer if there is one
                if notifier.condition.instance_id in self._timeout_timers:
                    task = self._timeout_timers[notifier.condition.instance_id]
                    task.cancel()
                    del self._timeout_timers[notifier.condition.instance_id]

                # Notify of completion
                notifier.notify()
            if prev == ConditionState.PENDING and curr == ConditionState.OFF:
                # Cancel the duration timer since we're off again
                if notifier.condition.instance_id in self._duration_timers:
                    task = self._duration_timers[notifier.condition.instance_id]
                    task.cancel()
                    del self._duration_timers[notifier.condition.instance_id]

    def _on_condition_timeout(
        self, notifier: ConditionNotifier
    ) -> Callable[[aio.Task[None]], None]:
        """Handles a condition timeout"""

        def inner(_: aio.Task[None]):
            # Remove the task from the timeout timers
            del self._timeout_timers[notifier.condition.instance_id]
            # Cancel any duration timers if present
            if notifier.condition.instance_id in self._duration_timers:
                duration_task = self._duration_timers[notifier.condition.instance_id]
                duration_task.cancel()
                del self._duration_timers[notifier.condition.instance_id]

            # We timed out, so stop waiting for the condition to become true
            self._conditions[notifier.condition.instance_id] = (
                notifier,
                ConditionState.TIMEOUT,
            )
            notifier.notify_timeout()

        return inner

    def _on_duration_timer(
        self, notifier: ConditionNotifier
    ) -> Callable[[aio.Task[None]], None]:
        """Handles a duration timer getting fired."""

        def inner(_: aio.Task[None]):
            # Remove the task from the duration timers
            del self._duration_timers[notifier.condition.instance_id]
            # Cancel any timeout timers if present
            if notifier.condition.instance_id in self._timeout_timers:
                timeout_task = self._timeout_timers[notifier.condition.instance_id]
                timeout_task.cancel()
                del self._timeout_timers[notifier.condition.instance_id]

            # Set state and notify
            self._conditions[notifier.condition.instance_id] = (
                notifier,
                ConditionState.ON,
            )
            notifier.notify()

            # Kick off an update for the parent conditions
            parent_conditions = []
            for parent_id in self._dependencies.get(notifier.condition.instance_id, []):
                if parent_id in self._conditions:
                    parent_cond = self._conditions[parent_id][0].condition
                    parent_conditions.append(parent_cond)
                    parent_cond.on_condition_event(notifier.condition, True)
            if len(parent_conditions) > 0:
                self.report_condition_event(parent_conditions)

        return inner
