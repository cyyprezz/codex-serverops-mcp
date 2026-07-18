from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from codex_serverops_mcp.config.model import validate_profile_name

SETUP_REQUEST_ID = re.compile(r"^setup-[0-9a-f]{24}$")
SETUP_REQUEST_LIFETIME_SECONDS = 30 * 60
SECRET_RESULT_FIELDS = {
    "password",
    "sudo_password",
    "key_passphrase",
    "passphrase",
    "private_key_content",
}


class SetupAction(StrEnum):
    ADD = "add"
    EDIT = "edit"
    REMOVE = "remove"
    TEST = "test"


class SetupStatus(StrEnum):
    PENDING = "user_interaction_required"
    RUNNING = "running"
    CREATED = "created"
    UPDATED = "updated"
    REMOVED = "removed"
    TESTED = "tested"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"

    @property
    def terminal(self) -> bool:
        return self not in {SetupStatus.PENDING, SetupStatus.RUNNING}


def new_setup_request_id() -> str:
    return f"setup-{secrets.token_hex(12)}"


def validate_setup_request_id(value: str) -> None:
    if not SETUP_REQUEST_ID.fullmatch(value):
        raise ValueError("request_id has an invalid format")


def _optional_suggestion(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not value or value != value.strip() or len(value) > 255 or "\0" in value:
        raise ValueError(f"{field_name} must be trimmed text with at most 255 characters")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{field_name} contains a control character")
    return value


@dataclass(frozen=True, slots=True)
class SetupRequest:
    request_id: str
    action: SetupAction
    created_at: float
    expires_at: float
    profile_name: str | None = None
    suggested_host: str | None = None
    suggested_user: str | None = None

    def __post_init__(self) -> None:
        validate_setup_request_id(self.request_id)
        if not isinstance(self.action, SetupAction):
            raise ValueError("setup action is invalid")
        if self.expires_at <= self.created_at:
            raise ValueError("setup request expiry must follow creation")
        if self.profile_name is not None:
            validate_profile_name(self.profile_name)
        object.__setattr__(
            self,
            "suggested_host",
            _optional_suggestion(self.suggested_host, "suggested_host"),
        )
        object.__setattr__(
            self,
            "suggested_user",
            _optional_suggestion(self.suggested_user, "suggested_user"),
        )
        if self.action is not SetupAction.ADD and self.profile_name is None:
            raise ValueError(f"profile_name is required for {self.action.value}")
        if self.action is not SetupAction.ADD and (
            self.suggested_host is not None or self.suggested_user is not None
        ):
            raise ValueError("suggestions are valid only when adding a profile")

    @classmethod
    def create(
        cls,
        action: SetupAction,
        *,
        profile_name: str | None = None,
        suggested_host: str | None = None,
        suggested_user: str | None = None,
        now: float | None = None,
    ) -> SetupRequest:
        created_at = time.time() if now is None else now
        return cls(
            request_id=new_setup_request_id(),
            action=action,
            created_at=created_at,
            expires_at=created_at + SETUP_REQUEST_LIFETIME_SECONDS,
            profile_name=profile_name,
            suggested_host=suggested_host,
            suggested_user=suggested_user,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "action": self.action.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "profile_name": self.profile_name,
            "suggested_host": self.suggested_host,
            "suggested_user": self.suggested_user,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> SetupRequest:
        expected = {
            "request_id",
            "action",
            "created_at",
            "expires_at",
            "profile_name",
            "suggested_host",
            "suggested_user",
        }
        if set(raw) != expected:
            raise ValueError("setup request fields are invalid")
        request_id = raw["request_id"]
        action = raw["action"]
        created_at = raw["created_at"]
        expires_at = raw["expires_at"]
        optional = (raw["profile_name"], raw["suggested_host"], raw["suggested_user"])
        if not isinstance(request_id, str) or not isinstance(action, str):
            raise ValueError("setup request identifiers are invalid")
        if not isinstance(created_at, int | float) or not isinstance(expires_at, int | float):
            raise ValueError("setup request timestamps are invalid")
        if any(value is not None and not isinstance(value, str) for value in optional):
            raise ValueError("setup request suggestions are invalid")
        return cls(
            request_id=request_id,
            action=SetupAction(action),
            created_at=float(created_at),
            expires_at=float(expires_at),
            profile_name=optional[0],
            suggested_host=optional[1],
            suggested_user=optional[2],
        )


def ensure_non_secret_result(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("setup result keys must be strings")
            if key.lower() in SECRET_RESULT_FIELDS:
                raise ValueError(f"setup result contains forbidden field: {key}")
            ensure_non_secret_result(item)
    elif isinstance(value, list | tuple):
        for item in value:
            ensure_non_secret_result(item)
    elif value is not None and not isinstance(value, str | int | float | bool):
        raise ValueError("setup result contains an unsupported value")


@dataclass(frozen=True, slots=True)
class SetupRecord:
    request: SetupRequest
    status: SetupStatus
    updated_at: float
    result: dict[str, object] | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, SetupStatus):
            raise ValueError("setup status is invalid")
        if self.updated_at < self.request.created_at:
            raise ValueError("setup status predates its request")
        if self.result is not None:
            ensure_non_secret_result(self.result)
        if self.message is not None:
            _optional_suggestion(self.message, "message")

    def to_dict(self) -> dict[str, object]:
        return {
            "request": self.request.to_dict(),
            "status": self.status.value,
            "updated_at": self.updated_at,
            "result": self.result,
            "message": self.message,
        }

    def public_result(self) -> dict[str, object]:
        document: dict[str, object] = {
            "status": self.status.value,
            "request_id": self.request.request_id,
            "action": self.request.action.value,
        }
        if self.request.profile_name is not None:
            document["profile_name"] = self.request.profile_name
        if self.result is not None:
            document.update(self.result)
        if self.message is not None:
            document["message"] = self.message
        return document

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SetupRecord:
        if set(raw) != {"request", "status", "updated_at", "result", "message"}:
            raise ValueError("setup record fields are invalid")
        request = raw["request"]
        status = raw["status"]
        updated_at = raw["updated_at"]
        result = raw["result"]
        message = raw["message"]
        if not isinstance(request, dict) or not isinstance(status, str):
            raise ValueError("setup record request or status is invalid")
        if not isinstance(updated_at, int | float):
            raise ValueError("setup record timestamp is invalid")
        if result is not None and not isinstance(result, dict):
            raise ValueError("setup result must be an object")
        if message is not None and not isinstance(message, str):
            raise ValueError("setup message must be text")
        return cls(
            request=SetupRequest.from_dict(request),
            status=SetupStatus(status),
            updated_at=float(updated_at),
            result=result,
            message=message,
        )
