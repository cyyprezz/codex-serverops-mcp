from __future__ import annotations

from codex_serverops_mcp.errors import ServerOpsError


class BrokerError(ServerOpsError):
    code = "broker_error"


class BrokerAlreadyRunning(BrokerError):
    code = "broker_already_running"


class BrokerUnavailable(BrokerError):
    code = "broker_unavailable"


class BrokerRequestError(BrokerError):
    code = "broker_request_failed"


class BrokerRemoteError(BrokerRequestError):
    def __init__(self, remote_code: str, message: str) -> None:
        super().__init__(message)
        self.code = remote_code


class BrokerOutcomeUnknown(BrokerRequestError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class WorkerOperationError(BrokerRequestError):
    def __init__(self, remote_code: str, message: str, state: str | None = None) -> None:
        super().__init__(message)
        self.code = remote_code
        self.state = state


class SessionNotFound(BrokerRequestError):
    code = "session_not_found"
