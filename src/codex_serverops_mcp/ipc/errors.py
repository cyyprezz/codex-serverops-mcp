from __future__ import annotations

from codex_serverops_mcp.errors import ServerOpsError


class IpcError(ServerOpsError):
    code = "ipc_error"


class IpcClosed(IpcError):
    code = "ipc_closed"


class IpcTimeout(IpcError):
    code = "ipc_timeout"


class IpcMessageError(IpcError):
    code = "ipc_message_invalid"


class ProtocolVersionError(IpcMessageError):
    code = "ipc_protocol_version_mismatch"


class IpcAuthenticationError(IpcError):
    code = "ipc_authentication_failed"


class PipeSecurityError(IpcError):
    code = "ipc_pipe_security_invalid"
