from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from multiprocessing.connection import Client, Connection, Listener
from pathlib import Path
from typing import Any

from codex_serverops_mcp import BROKER_PROTOCOL_VERSION, WORKER_PROTOCOL_VERSION

from .ipc import receive_message, send_message


@dataclass(slots=True)
class WorkerProxy:
    process: subprocess.Popen[bytes]
    connection: Connection

    def request(self, message: dict[str, Any]) -> dict[str, Any]:
        send_message(self.connection, message)
        return receive_message(self.connection)

    def close(self) -> None:
        with suppress(EOFError, OSError):
            self.request({"type": "close"})
        self.connection.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()


def _connect_worker(pipe: str, authkey: bytes, timeout: float = 10) -> Connection:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return Client(pipe, family="AF_PIPE", authkey=authkey)
        except (FileNotFoundError, OSError):
            time.sleep(0.05)
    raise TimeoutError("worker pipe did not become available")


def _start_worker(request: dict[str, Any]) -> WorkerProxy:
    pipe = rf"\\.\pipe\codex-serverops-worker-{uuid.uuid4().hex}"
    authkey = os.urandom(32)
    environment = dict(os.environ)
    environment["SERVEROPS_SPIKE_WORKER_AUTHKEY"] = base64.urlsafe_b64encode(
        authkey
    ).decode("ascii")
    process = subprocess.Popen(
        [sys.executable, "-m", "codex_serverops_mcp.spike.worker_process", "--pipe", pipe],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    connection = _connect_worker(pipe, authkey)
    send_message(
        connection, {"type": "hello", "protocol_version": WORKER_PROTOCOL_VERSION}
    )
    hello = receive_message(connection)
    if hello.get("status") != "ready":
        raise RuntimeError(f"worker handshake failed: {hello}")
    proxy = WorkerProxy(process, connection)
    started = proxy.request(
        {
            "type": "start",
            "ssh_arguments": request["ssh_arguments"],
            "password_file": request["password_file"],
            "passphrase_file": request["passphrase_file"],
        }
    )
    if started.get("status") != "ready":
        proxy.close()
        raise RuntimeError(f"worker start failed: {started}")
    return proxy


def _serve(runtime: Path) -> None:
    pipe = rf"\\.\pipe\codex-serverops-broker-{uuid.uuid4().hex}"
    authkey = os.urandom(32)
    listener = Listener(pipe, family="AF_PIPE", authkey=authkey)
    status_path = runtime / "broker.json"
    temporary = status_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "pipe": pipe,
                "authkey": base64.urlsafe_b64encode(authkey).decode("ascii"),
                "protocol_version": BROKER_PROTOCOL_VERSION,
                "broker_pid": os.getpid(),
            }
        ),
        encoding="utf-8",
    )
    os.replace(temporary, status_path)
    workers: dict[str, WorkerProxy] = {}
    running = True
    try:
        while running:
            client = listener.accept()
            try:
                hello = receive_message(client)
                if hello != {"type": "hello", "protocol_version": BROKER_PROTOCOL_VERSION}:
                    send_message(
                        client,
                        {
                            "status": "protocol_mismatch",
                            "protocol_version": BROKER_PROTOCOL_VERSION,
                        },
                    )
                    continue
                send_message(
                    client,
                    {
                        "status": "ready",
                        "protocol_version": BROKER_PROTOCOL_VERSION,
                        "broker_pid": os.getpid(),
                    },
                )
                while True:
                    request = receive_message(client)
                    request_type = request.get("type")
                    if request_type == "open":
                        session_id = str(request["session_id"])
                        if session_id in workers:
                            send_message(client, {"status": "error", "message": "duplicate"})
                            continue
                        proxy = _start_worker(request)
                        workers[session_id] = proxy
                        send_message(
                            client,
                            {
                                "status": "ready",
                                "session_id": session_id,
                                "worker_pid": proxy.process.pid,
                            },
                        )
                    elif request_type == "exec":
                        response = workers[str(request["session_id"])].request(
                            {"type": "exec", "command": request["command"]}
                        )
                        send_message(client, response)
                    elif request_type == "list":
                        send_message(
                            client,
                            {"status": "ok", "sessions": sorted(workers)},
                        )
                    elif request_type == "close":
                        worker = workers.pop(str(request["session_id"]))
                        worker.close()
                        send_message(client, {"status": "closed"})
                    elif request_type == "disconnect":
                        send_message(client, {"status": "disconnected"})
                        break
                    elif request_type == "shutdown":
                        send_message(client, {"status": "closed"})
                        running = False
                        break
                    else:
                        send_message(client, {"status": "error", "message": "unknown request"})
            except EOFError:
                pass
            finally:
                client.close()
    finally:
        for worker in workers.values():
            worker.close()
        listener.close()
        status_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args()
    _serve(args.runtime.resolve())


if __name__ == "__main__":
    main()
