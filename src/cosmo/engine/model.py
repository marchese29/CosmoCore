import time
from abc import ABC, abstractmethod
from datetime import timedelta


class EngineCondition(ABC):
    """A condition tracked by the rules engine."""

    def __init__(self):
        # Create unique instance ID using timestamp + object ID
        # This avoids any threading/async safety concerns
        self._instance_id = int(time.time_ns()) + id(self)

    @property
    def instance_id(self) -> int:
        """Unique instance identifier for this condition."""
        return self._instance_id

    @property
    @abstractmethod
    def identifier(self) -> str:
        """Human-readable identifier for the condition."""

    @property
    def timeout(self) -> timedelta | None:
        """Timeout for this condition."""
        return None

    @property
    def duration(self) -> timedelta | None:
        """Amount of time this condition must remain on to be considered 'true'"""
        return None

    @property
    def subconditions(self) -> list["EngineCondition"]:
        """Sub-conditions of this condition"""
        return []

    def initialize(self, states: list[tuple["EngineCondition", bool]]):
        """Called to initialize the condition by giving it all subcondition states."""
        return

    def on_condition_event(self, condition: "EngineCondition", state: bool):
        """Invoked when a subcondition changes.  Your logic must be order invariant"""
        return

    @abstractmethod
    def evaluate(self) -> bool:
        """Evaluates if this condition is currently met"""
