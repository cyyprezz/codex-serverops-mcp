from __future__ import annotations

from codex_serverops_mcp.errors import ServerOpsError


class AuthenticationError(ServerOpsError):
    code = "authentication_failed"


class AuthenticationCancelled(AuthenticationError):
    code = "authentication_cancelled"


class AuthenticationRejected(AuthenticationError):
    code = "authentication_rejected"


class AuthenticationTimedOut(AuthenticationError):
    code = "authentication_timeout"


class AuthenticationProtocolError(AuthenticationError):
    code = "authentication_protocol_invalid"


class AuthenticationReplayError(AuthenticationError):
    code = "authentication_request_reused"


class AuthenticationLaunchError(AuthenticationError):
    code = "authentication_window_failed"
