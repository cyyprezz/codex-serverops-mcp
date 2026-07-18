from __future__ import annotations

from codex_serverops_mcp.errors import ServerOpsError


class ElevationError(ServerOpsError):
    code = "elevation_error"

    def __init__(self, elevation_code: str, message: str) -> None:
        super().__init__(message)
        self.code = elevation_code
