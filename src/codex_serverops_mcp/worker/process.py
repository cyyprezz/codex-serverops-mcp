from __future__ import annotations

import argparse
import os
from contextlib import suppress
from pathlib import Path

from codex_serverops_mcp import WORKER_PROTOCOL_VERSION
from codex_serverops_mcp.config.model import validate_profile_name
from codex_serverops_mcp.errors import ServerOpsError
from codex_serverops_mcp.identifiers import validate_session_id
from codex_serverops_mcp.ipc.constants import (
    IPC_FRAME_TIMEOUT_SECONDS,
    IPC_HANDSHAKE_TIMEOUT_SECONDS,
)
from codex_serverops_mcp.ipc.errors import IpcClosed, IpcError
from codex_serverops_mcp.ipc.handshake import server_handshake
from codex_serverops_mcp.ipc.messages import Envelope
from codex_serverops_mcp.ipc.named_pipe import NamedPipeListener
from codex_serverops_mcp.ipc.security import pipe_name_for_current_user
from codex_serverops_mcp.runtime import RuntimeDirectory

from .protocol import WorkerProtocolHandler


def _worker_pipe(session_id: str) -> str:
    suffix = session_id.removeprefix("sess-")
    return pipe_name_for_current_user(f"worker-{suffix}")


def run_worker(
    session_id: str,
    profile_name: str,
    runtime_path: Path,
    *,
    root_session: bool = False,
) -> int:
    validate_session_id(session_id)
    validate_profile_name(profile_name)
    token = os.environ.pop("SERVEROPS_WORKER_TOKEN", "")
    if not token:
        return 2
    runtime = RuntimeDirectory(runtime_path)
    runtime.prepare()
    status_path = runtime.worker_status_path(session_id)
    pipe = _worker_pipe(session_id)
    handler = WorkerProtocolHandler(
        session_id,
        profile_name,
        root_session=root_session,
    )
    stop = False
    with NamedPipeListener(pipe) as listener:
        runtime.write_json(
            status_path,
            {
                "session_id": session_id,
                "profile_name": profile_name,
                "pid": os.getpid(),
                "pipe": pipe,
                "protocol_version": WORKER_PROTOCOL_VERSION,
                "state": "created",
                "root_session": root_session,
            },
        )
        try:
            while not stop:
                try:
                    connection = listener.accept()
                except IpcClosed:
                    break
                with connection:
                    authenticated = False
                    try:
                        server_handshake(
                            connection,
                            token,
                            expected_role="broker",
                            timeout=IPC_HANDSHAKE_TIMEOUT_SECONDS,
                        )
                        authenticated = True
                        while not stop:
                            request = connection.receive(
                                frame_timeout=IPC_FRAME_TIMEOUT_SECONDS
                            )
                            try:
                                reply = handler.handle(request.message_type, request.payload)
                                response_type = f"{request.message_type}.result"
                                payload = reply.payload
                                stop = reply.stop
                            except (ServerOpsError, ValueError) as error:
                                response_type = "error"
                                payload = handler.error_payload(error)
                            except Exception:
                                with suppress(Exception):
                                    handler.service.close()
                                response_type = "error"
                                payload = {
                                    "code": "worker_internal_error",
                                    "message": "worker operation failed safely",
                                    "state": handler.service.status()["state"],
                                }
                                stop = True
                            connection.send(
                                Envelope.create(
                                    response_type,
                                    payload,
                                    message_id=request.message_id,
                                )
                            )
                            if not stop:
                                status = handler.service.status()
                                runtime.write_json(
                                    status_path,
                                    {
                                        "session_id": session_id,
                                        "profile_name": profile_name,
                                        "pid": os.getpid(),
                                        "pipe": pipe,
                                        "protocol_version": WORKER_PROTOCOL_VERSION,
                                        "state": status["state"],
                                        "root_session": root_session,
                                    },
                                )
                    except IpcError:
                        if authenticated:
                            break
                        continue
        finally:
            status_path.unlink(missing_ok=True)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--root-session", action="store_true")
    args = parser.parse_args()
    raise SystemExit(
        run_worker(
            args.session_id,
            args.profile,
            args.runtime.resolve(),
            root_session=args.root_session,
        )
    )


if __name__ == "__main__":
    main()
