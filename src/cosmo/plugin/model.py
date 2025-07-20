from datetime import timedelta
from typing import override

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
