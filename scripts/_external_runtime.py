from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from codex_serverops_mcp.application import ApplicationServices
from codex_serverops_mcp.broker.manager import BrokerManager
from codex_serverops_mcp.config import TomlProfileRepository
from codex_serverops_mcp.security import AuditLogger


@contextmanager
def isolated_external_services() -> Iterator[ApplicationServices]:
    """Run an external check on the current interpreter, never the installed broker task."""
    with TemporaryDirectory(prefix="codex-serverops-external-") as temporary:
        manager = BrokerManager(Path(temporary) / "runtime")
        services = ApplicationServices(
            TomlProfileRepository(),
            manager,
            setup=None,
            audit=AuditLogger(),
        )
        try:
            yield services
        finally:
            manager.shutdown_launched_broker()
