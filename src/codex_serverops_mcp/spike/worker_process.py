from __future__ import annotations

import argparse
import base64
import os
from multiprocessing.connection import Listener
from pathlib import Path

from codex_serverops_mcp import WORKER_PROTOCOL_VERSION

from .ipc import receive_message, send_message
from .session import SshSpikeSession


def _serve(pipe: str, authkey: bytes) -> None:
    listener = Listener(pipe, family="AF_PIPE", authkey=authkey)
    connection = listener.accept()
    session: SshSpikeSession | None = None
    try:
        hello = receive_message(connection)
        if hello != {"type": "hello", "protocol_version": WORKER_PROTOCOL_VERSION}:
            send_message(
                connection,
                {"status": "protocol_mismatch", "protocol_version": WORKER_PROTOCOL_VERSION},
            )
            return
        send_message(
            connection, {"status": "ready", "protocol_version": WORKER_PROTOCOL_VERSION}
        )
        while True:
            request = receive_message(connection)
            request_type = request.get("type")
            if request_type == "start":
                if session is not None:
                    send_message(connection, {"status": "error", "message": "already started"})
                    continue
                password_file = Path(str(request["password_file"]))
                passphrase_file = Path(str(request["passphrase_file"]))

                def provider(
                    kind: str,
                    prompt: str,
                    password_file: Path = password_file,
                    passphrase_file: Path = passphrase_file,
                ) -> str:
                    del prompt
                    if kind == "host_key":
                        return "yes"
                    if kind in {"password", "sudo_password"}:
                        return password_file.read_text(encoding="utf-8")
                    if kind == "key_passphrase":
                        return passphrase_file.read_text(encoding="utf-8")
                    raise RuntimeError(f"unexpected prompt kind: {kind}")

                session = SshSpikeSession()
                session.open(list(request["ssh_arguments"]), provider, timeout=20)
                session._spike_provider = provider  # type: ignore[attr-defined]
                send_message(connection, {"status": "ready", "worker_pid": os.getpid()})
            elif request_type == "exec" and session is not None:
                provider = session._spike_provider  # type: ignore[attr-defined]
                result = session.execute(str(request["command"]), provider, timeout=20)
                send_message(
                    connection,
                    {
                        "status": "completed",
                        "output": result.output,
                        "exit_code": result.exit_code,
                        "cwd": result.cwd,
                    },
                )
            elif request_type == "status" and session is not None:
                send_message(connection, {"status": "ready" if session.running else "lost"})
            elif request_type == "close":
                if session is not None:
                    session.close()
                send_message(connection, {"status": "closed"})
                return
            else:
                send_message(connection, {"status": "error", "message": "unknown request"})
    finally:
        if session is not None:
            session.close()
        connection.close()
        listener.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipe", required=True)
    args = parser.parse_args()
    encoded = os.environ.pop("SERVEROPS_SPIKE_WORKER_AUTHKEY", "")
    if not encoded:
        raise SystemExit(2)
    _serve(args.pipe, base64.urlsafe_b64decode(encoded.encode("ascii")))


if __name__ == "__main__":
    main()
