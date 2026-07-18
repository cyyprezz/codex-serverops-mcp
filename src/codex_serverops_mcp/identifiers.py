from __future__ import annotations

import re
import secrets

SESSION_ID = re.compile(r"^sess-[0-9a-f]{16}$")


def new_session_id() -> str:
    return f"sess-{secrets.token_hex(8)}"


def validate_session_id(value: str) -> None:
    if not SESSION_ID.fullmatch(value):
        raise ValueError("session_id has an invalid format")
