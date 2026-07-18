from __future__ import annotations

import hmac
import re
import secrets

from codex_serverops_mcp import BROKER_PROTOCOL_VERSION

from .connection import PipeConnection
from .errors import IpcAuthenticationError, IpcMessageError
from .messages import Envelope

IPC_ROLES = {"mcp", "broker", "auth"}
NONCE = re.compile(r"^[0-9a-f]{64}$")
PROOF = re.compile(r"^[0-9a-f]{64}$")


def _proof(
    instance_token: str,
    label: str,
    role: str,
    client_nonce: str,
    server_nonce: str,
) -> str:
    message = "\0".join(
        (
            label,
            str(BROKER_PROTOCOL_VERSION),
            role,
            client_nonce,
            server_nonce,
        )
    )
    return hmac.digest(instance_token.encode("utf-8"), message.encode("utf-8"), "sha256").hex()


def _text_field(payload: dict[str, object], name: str, pattern: re.Pattern[str]) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise IpcAuthenticationError(f"broker handshake {name} is invalid")
    return value


def client_handshake(
    connection: PipeConnection,
    instance_token: str,
    *,
    role: str = "mcp",
    timeout: float | None = None,
) -> None:
    if role not in IPC_ROLES:
        raise ValueError("IPC handshake role is invalid")
    client_nonce = secrets.token_hex(32)
    challenge = Envelope.create(
        "hello.challenge",
        {"role": role, "client_nonce": client_nonce},
    )
    connection.send(challenge)
    response = connection.receive(timeout=timeout)
    if (
        response.message_id != challenge.message_id
        or response.message_type != "hello.challenge.ack"
        or set(response.payload) != {"protocol_version", "server_nonce", "server_proof"}
        or response.payload.get("protocol_version") != BROKER_PROTOCOL_VERSION
    ):
        raise IpcAuthenticationError("broker handshake challenge response is invalid")
    server_nonce = _text_field(response.payload, "server_nonce", NONCE)
    server_proof = _text_field(response.payload, "server_proof", PROOF)
    expected_server_proof = _proof(
        instance_token,
        "server",
        role,
        client_nonce,
        server_nonce,
    )
    if not hmac.compare_digest(server_proof, expected_server_proof):
        raise IpcAuthenticationError("broker server proof was rejected")
    hello = Envelope.create(
        "hello",
        {
            "role": role,
            "client_nonce": client_nonce,
            "server_nonce": server_nonce,
            "client_proof": _proof(
                instance_token,
                "client",
                role,
                client_nonce,
                server_nonce,
            ),
        },
    )
    connection.send(hello)
    acknowledgement = connection.receive(timeout=timeout)
    if (
        acknowledgement.message_id != hello.message_id
        or acknowledgement.message_type != "hello.ack"
        or acknowledgement.payload != {"protocol_version": BROKER_PROTOCOL_VERSION}
    ):
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
    challenge = connection.receive(timeout=timeout)
    role = challenge.payload.get("role")
    if (
        challenge.message_type != "hello.challenge"
        or set(challenge.payload) != {"role", "client_nonce"}
        or role != expected_role
    ):
        raise IpcAuthenticationError("broker handshake challenge is invalid")
    client_nonce = _text_field(challenge.payload, "client_nonce", NONCE)
    server_nonce = secrets.token_hex(32)
    connection.send(
        Envelope.create(
            "hello.challenge.ack",
            {
                "protocol_version": BROKER_PROTOCOL_VERSION,
                "server_nonce": server_nonce,
                "server_proof": _proof(
                    expected_token,
                    "server",
                    expected_role,
                    client_nonce,
                    server_nonce,
                ),
            },
            message_id=challenge.message_id,
        )
    )
    hello = connection.receive(timeout=timeout)
    if (
        hello.message_type != "hello"
        or set(hello.payload)
        != {"role", "client_nonce", "server_nonce", "client_proof"}
        or hello.payload.get("role") != expected_role
        or hello.payload.get("client_nonce") != client_nonce
        or hello.payload.get("server_nonce") != server_nonce
    ):
        raise IpcAuthenticationError("broker handshake request is invalid")
    client_proof = _text_field(hello.payload, "client_proof", PROOF)
    expected_client_proof = _proof(
        expected_token,
        "client",
        expected_role,
        client_nonce,
        server_nonce,
    )
    if not hmac.compare_digest(client_proof, expected_client_proof):
        raise IpcAuthenticationError("broker client proof was rejected")
    connection.send(
        Envelope.create(
            "hello.ack",
            {"protocol_version": BROKER_PROTOCOL_VERSION},
            message_id=hello.message_id,
        )
    )
