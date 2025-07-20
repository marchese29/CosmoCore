from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from cosmo.plugin.model import AbstractCondition


class CosmoPlugin(ABC):
    """Plugin class for registering functionality with Cosmo."""

    @abstractmethod
    async def run(self) -> AsyncGenerator[list[AbstractCondition], None]:
        """The main loop of the plugin - yields events by reporting impacted conditions"""
        ...

    def get_rule_utility(self) -> object | None:
        """Returns the rule utility for this plugin.  Default is to not have a utility"""
        return None
