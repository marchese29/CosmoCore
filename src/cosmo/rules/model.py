from collections.abc import Awaitable, Callable
from datetime import datetime

from cosmo.plugin.model import AbstractCondition

RuleTriggerProvider = Callable[..., AbstractCondition]
RuleTimeProvider = Callable[[], datetime | None]
RuleRoutine = Callable[..., Awaitable[None]]


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
        routine: RuleRoutine,
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
