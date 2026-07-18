from __future__ import annotations

from codex_serverops_mcp.errors import ServerOpsError


class SessionError(ServerOpsError):
    code = "session_error"


class InvalidSessionState(SessionError):
    code = "invalid_session_state"


class AuthenticationUnavailable(SessionError):
    code = "authentication_unavailable"


class SessionLost(SessionError):
    code = "session_lost"


class CommandTimedOut(SessionError):
    code = "command_timed_out"


class OutcomeUnknown(SessionError):
    code = "outcome_unknown"
