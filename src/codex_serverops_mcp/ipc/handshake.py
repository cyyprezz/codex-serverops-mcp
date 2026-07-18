from __future__ import annotations

import hmac

from codex_serverops_mcp import BROKER_PROTOCOL_VERSION

from .connection import PipeConnection
from .errors import IpcAuthenticationError, IpcMessageError
from .messages import Envelope

IPC_ROLES = {"mcp", "broker", "auth"}


def client_handshake(
    connection: PipeConnection,
    instance_token: str,
    *,
    role: str = "mcp",
    timeout: float | None = None,
) -> None:
    if role not in IPC_ROLES:
        raise ValueError("IPC handshake role is invalid")
    hello = Envelope.create(
        "hello",
        {"role": role, "instance_token": instance_token},
    )
    connection.send(hello)
    response = connection.receive(timeout=timeout)
    if response.message_id != hello.message_id or response.message_type != "hello.ack":
        raise IpcMessageError("broker handshake response is invalid")
    if response.payload.get("protocol_version") != BROKER_PROTOCOL_VERSION:
        raise IpcMessageError("broker handshake acknowledgement is invalid")


def server_handshake(
    connection: PipeConnection,
    expected_token: str,
    *,
    expected_role: str = "mcp",
    timeout: float | None = None,
) -> None:
    if expected_role not in IPC_ROLES:
        raise ValueError("IPC handshake role is invalid")
    hello = connection.receive(timeout=timeout)
    role = hello.payload.get("role")
    token = hello.payload.get("instance_token")
    if hello.message_type != "hello" or role != expected_role or not isinstance(token, str):
        raise IpcAuthenticationError("broker handshake request is invalid")
    if not hmac.compare_digest(token, expected_token):
        raise IpcAuthenticationError("broker instance token was rejected")
    connection.send(
        Envelope.create(
            "hello.ack",
            {"protocol_version": BROKER_PROTOCOL_VERSION},
            message_id=hello.message_id,
        )
    )
