from __future__ import annotations

import json
from multiprocessing.connection import Connection
from typing import Any

MAX_MESSAGE_BYTES = 262_144


def send_message(connection: Connection, message: dict[str, Any]) -> None:
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("IPC message exceeds the spike size limit")
    connection.send_bytes(payload)


def receive_message(connection: Connection) -> dict[str, Any]:
    payload = connection.recv_bytes(MAX_MESSAGE_BYTES)
    message = json.loads(payload.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("IPC message must be an object")
    return message
