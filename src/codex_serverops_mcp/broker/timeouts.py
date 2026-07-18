from __future__ import annotations

from collections.abc import Mapping

DEFAULT_BROKER_RESPONSE_TIMEOUT_SECONDS = 15.0
SESSION_START_RESPONSE_TIMEOUT_SECONDS = 210.0
TERMINAL_RESPONSE_TIMEOUT_SECONDS = 80.0
WORKER_LONG_OPERATION_TIMEOUT_SECONDS = 3_726.0
LONG_OPERATION_RESPONSE_TIMEOUT_SECONDS = 3_728.0


def broker_response_timeout(
    message_type: str,
    payload: Mapping[str, object] | None = None,
) -> float:
    body = payload or {}
    if message_type in {"session.exec", "session.files", "session.file_edit"}:
        return LONG_OPERATION_RESPONSE_TIMEOUT_SECONDS
    if message_type == "session.terminal":
        return TERMINAL_RESPONSE_TIMEOUT_SECONDS
    if message_type in {"session.create", "session.open"}:
        return SESSION_START_RESPONSE_TIMEOUT_SECONDS
    if message_type == "session.elevation":
        action = body.get("action")
        if action == "exec":
            return LONG_OPERATION_RESPONSE_TIMEOUT_SECONDS
        if action == "acquire":
            return LONG_OPERATION_RESPONSE_TIMEOUT_SECONDS
        if action == "open_root_session":
            return SESSION_START_RESPONSE_TIMEOUT_SECONDS
    return DEFAULT_BROKER_RESPONSE_TIMEOUT_SECONDS
