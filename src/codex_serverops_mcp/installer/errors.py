from __future__ import annotations

from codex_serverops_mcp.errors import ServerOpsError


class InstallerError(ServerOpsError):
    code = "installer_error"
