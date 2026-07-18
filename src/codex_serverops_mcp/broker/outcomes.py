from __future__ import annotations

from collections.abc import Mapping

_TERMINAL_MUTATIONS = {"start", "write", "interrupt", "resize", "close"}
_ELEVATION_MUTATIONS = {
    "acquire",
    "release",
    "exec",
    "open_root_session",
    "close_root_session",
}


def uncertain_outcome_code(
    message_type: str,
    payload: Mapping[str, object] | None = None,
) -> str | None:
    """Classify requests whose effects cannot be inferred after IPC delivery."""
    body = payload or {}
    if message_type in {"session.exec", "worker.exec"}:
        return "outcome_unknown"
    if message_type in {"session.file_edit", "worker.file_edit"}:
        return "file_outcome_unknown"
    if message_type in {"session.elevation", "worker.elevation"}:
        return (
            "elevation_outcome_unknown"
            if body.get("action") in _ELEVATION_MUTATIONS
            else None
        )
    if message_type in {"session.terminal", "worker.terminal"}:
        return "outcome_unknown" if body.get("action") in _TERMINAL_MUTATIONS else None
    if message_type in {
        "session.create",
        "session.open",
        "session.close",
        "broker.shutdown",
        "worker.open",
        "worker.shutdown",
    }:
        return "outcome_unknown"
    return None
