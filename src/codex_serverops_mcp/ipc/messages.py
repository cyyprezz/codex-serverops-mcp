from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from codex_serverops_mcp import BROKER_PROTOCOL_VERSION

from .constants import MAX_IPC_MESSAGE_BYTES
from .errors import IpcMessageError, ProtocolVersionError

MESSAGE_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
MESSAGE_TYPE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
ENVELOPE_FIELDS = {"protocol_version", "message_id", "message_type", "payload"}


@dataclass(frozen=True, slots=True)
class Envelope:
    protocol_version: int
    message_id: str
    message_type: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if isinstance(self.protocol_version, bool) or not isinstance(self.protocol_version, int):
            raise IpcMessageError("protocol_version must be an integer")
        if not MESSAGE_ID.fullmatch(self.message_id):
            raise IpcMessageError("message_id has an invalid format")
        if not MESSAGE_TYPE.fullmatch(self.message_type):
            raise IpcMessageError("message_type has an invalid format")
        if not isinstance(self.payload, Mapping):
            raise IpcMessageError("payload must be an object")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    @classmethod
    def create(
        cls,
        message_type: str,
        payload: dict[str, object] | None = None,
        *,
        message_id: str | None = None,
    ) -> Envelope:
        return cls(
            protocol_version=BROKER_PROTOCOL_VERSION,
            message_id=message_id or f"msg_{uuid.uuid4().hex}",
            message_type=message_type,
            payload=payload or {},
        )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IpcMessageError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def encode_envelope(envelope: Envelope, *, max_bytes: int = MAX_IPC_MESSAGE_BYTES) -> bytes:
    try:
        encoded = json.dumps(
            {
                "protocol_version": envelope.protocol_version,
                "message_id": envelope.message_id,
                "message_type": envelope.message_type,
                "payload": dict(envelope.payload),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise IpcMessageError("message payload is not valid JSON") from error
    if not encoded or len(encoded) > max_bytes:
        raise IpcMessageError(f"message exceeds the {max_bytes}-byte limit")
    return encoded


def decode_envelope(data: bytes, *, max_bytes: int = MAX_IPC_MESSAGE_BYTES) -> Envelope:
    if not data or len(data) > max_bytes:
        raise IpcMessageError(f"message exceeds the {max_bytes}-byte limit")
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IpcMessageError("message is not valid UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise IpcMessageError("message envelope must be an object")
    if set(document) != ENVELOPE_FIELDS:
        raise IpcMessageError("message envelope fields do not match the protocol")
    envelope = Envelope(
        protocol_version=document["protocol_version"],
        message_id=document["message_id"],
        message_type=document["message_type"],
        payload=document["payload"],
    )
    if envelope.protocol_version != BROKER_PROTOCOL_VERSION:
        raise ProtocolVersionError(
            f"broker protocol mismatch: expected {BROKER_PROTOCOL_VERSION}, "
            f"got {envelope.protocol_version}"
        )
    return envelope
