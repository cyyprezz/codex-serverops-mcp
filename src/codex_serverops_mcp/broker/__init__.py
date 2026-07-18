from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import BrokerClient
    from .server import BrokerServer

__all__ = ["BrokerClient", "BrokerServer"]


def __getattr__(name: str) -> object:
    if name == "BrokerClient":
        from .client import BrokerClient

        return BrokerClient
    if name == "BrokerServer":
        from .server import BrokerServer

        return BrokerServer
    raise AttributeError(name)
