from __future__ import annotations

import os
import sys

from codex_serverops_mcp.ipc.constants import MAX_AUTH_MESSAGE_BYTES
from codex_serverops_mcp.ipc.handshake import client_handshake
from codex_serverops_mcp.ipc.messages import Envelope
from codex_serverops_mcp.ipc.named_pipe import connect_named_pipe

from .wire import MAX_AUTH_RESPONSE_BYTES

ASKPASS_MODE_ENVIRONMENT = "SERVEROPS_ASKPASS_MODE"
ASKPASS_PIPE_ENVIRONMENT = "SERVEROPS_ASKPASS_PIPE"
ASKPASS_TOKEN_ENVIRONMENT = "SERVEROPS_ASKPASS_TOKEN"
ASKPASS_RESPONSE = 1
ASKPASS_REJECTED = 2
ASKPASS_CANCELLED = 3
ASKPASS_TIMED_OUT = 4
ASKPASS_FAILED = 5


def is_askpass_invocation() -> bool:
    return os.environ.get(ASKPASS_MODE_ENVIRONMENT) == "1"


def run_askpass(arguments: list[str]) -> int:
    pipe = os.environ.pop(ASKPASS_PIPE_ENVIRONMENT, "")
    token = os.environ.pop(ASKPASS_TOKEN_ENVIRONMENT, "")
    os.environ.pop(ASKPASS_MODE_ENVIRONMENT, None)
    if len(arguments) != 1 or not pipe or not token:
        return 3
    prompt = arguments[0]
    if not prompt or "\0" in prompt or len(prompt) > 2_048:
        return 3
    connection = None
    response: bytearray | None = None
    secret: bytearray | None = None
    try:
        connection = connect_named_pipe(pipe, timeout=5)
        client_handshake(connection, token, role="askpass", timeout=5)
        connection.send(
            Envelope.create("askpass.prompt", {"prompt": prompt}),
            max_bytes=MAX_AUTH_MESSAGE_BYTES,
        )
        response = bytearray(
            connection.receive_bytes(
                max_bytes=MAX_AUTH_RESPONSE_BYTES + 1,
                timeout=125,
            )
        )
        if not response or response[0] != ASKPASS_RESPONSE:
            return 2
        secret = response[1:]
        if (
            not secret
            or len(secret) > MAX_AUTH_RESPONSE_BYTES
            or b"\r" in secret
            or b"\n" in secret
        ):
            return 3
        sys.stdout.buffer.write(secret)
        sys.stdout.buffer.write(b"\n")
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        return 3
    finally:
        if secret is not None:
            secret[:] = b"\0" * len(secret)
            secret.clear()
        if response is not None:
            response[:] = b"\0" * len(response)
            response.clear()
        if connection is not None:
            connection.close()
        token = ""
