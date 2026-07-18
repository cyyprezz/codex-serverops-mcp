from __future__ import annotations

import base64
import json
from multiprocessing.connection import Client, Connection
from pathlib import Path
from typing import Any

from codex_serverops_mcp import BROKER_PROTOCOL_VERSION

from .ipc import receive_message, send_message


class SpikeBrokerClient:
    def __init__(self, runtime: Path) -> None:
        status = json.loads((runtime / "broker.json").read_text(encoding="utf-8"))
        authkey = base64.urlsafe_b64decode(status["authkey"].encode("ascii"))
        self.connection: Connection = Client(
            status["pipe"], family="AF_PIPE", authkey=authkey
        )
        self.broker_pid = int(status["broker_pid"])
        self.request({"type": "hello", "protocol_version": BROKER_PROTOCOL_VERSION})

    def request(self, message: dict[str, Any]) -> dict[str, Any]:
        send_message(self.connection, message)
        return receive_message(self.connection)

    def disconnect(self) -> None:
        try:
            self.request({"type": "disconnect"})
        finally:
            self.connection.close()

