from __future__ import annotations

import argparse
import os
import secrets
import threading
import time
from collections.abc import Mapping
from pathlib import Path

import pywintypes
import win32api
import win32con
import win32process

from codex_serverops_mcp import BROKER_PROTOCOL_VERSION
from codex_serverops_mcp.config.model import validate_profile_name
from codex_serverops_mcp.errors import ServerOpsError
from codex_serverops_mcp.identifiers import validate_session_id
from codex_serverops_mcp.ipc.connection import PipeConnection
from codex_serverops_mcp.ipc.constants import (
    IPC_FRAME_TIMEOUT_SECONDS,
    IPC_HANDSHAKE_TIMEOUT_SECONDS,
)
from codex_serverops_mcp.ipc.errors import IpcError
from codex_serverops_mcp.ipc.handshake import server_handshake
from codex_serverops_mcp.ipc.messages import Envelope
from codex_serverops_mcp.ipc.named_pipe import NamedPipeListener, connect_named_pipe
from codex_serverops_mcp.ipc.security import pipe_name_for_current_user
from codex_serverops_mcp.runtime import RuntimeDirectory

from .errors import BrokerAlreadyRunning, BrokerRequestError
from .model import SessionRecord
from .supervisor import WorkerSupervisor


def _process_is_alive(pid: int) -> bool:
    try:
        process = win32api.OpenProcess(
            win32con.PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )
    except pywintypes.error as error:
        # ERROR_INVALID_PARAMETER means that no process with this PID exists.
        # Access-denied and other errors are treated conservatively as alive.
        return error.winerror != 87
    try:
        return win32process.GetExitCodeProcess(process) == win32con.STILL_ACTIVE
    finally:
        process.Close()


class BrokerServer:
    def __init__(self, runtime_path: Path | None = None) -> None:
        self.runtime = RuntimeDirectory(runtime_path)
        self.runtime.prepare()
        self.pipe = pipe_name_for_current_user("broker")
        try:
            self.listener = NamedPipeListener(self.pipe)
        except pywintypes.error as error:
            raise BrokerAlreadyRunning("a broker already owns the per-user pipe") from error
        self.stale_cleanup = self.runtime.clean_stale_statuses(
            process_is_alive=_process_is_alive,
        )
        self.ipc_security_report = self.listener.security_report
        self.instance_token = secrets.token_urlsafe(32)
        self.supervisor = WorkerSupervisor(self.runtime)
        self._stop = threading.Event()
        self._client_threads: set[threading.Thread] = set()
        self._thread_lock = threading.Lock()

    def serve_forever(self) -> None:
        self.runtime.write_json(
            self.runtime.broker_status_path,
            {
                "pid": os.getpid(),
                "pipe": self.pipe,
                "protocol_version": BROKER_PROTOCOL_VERSION,
                "instance_token": self.instance_token,
                "started_at": time.time(),
            },
        )
        try:
            while not self._stop.is_set():
                try:
                    connection = self.listener.accept()
                except BaseException:
                    if self._stop.is_set():
                        break
                    raise
                if self._stop.is_set():
                    connection.close()
                    break
                thread = threading.Thread(
                    target=self._serve_client,
                    args=(connection,),
                    name="serverops-broker-client",
                    daemon=True,
                )
                with self._thread_lock:
                    self._client_threads.add(thread)
                thread.start()
        finally:
            self._stop.set()
            self.listener.close()
            self._join_clients()
            self.supervisor.close_all()
            self._remove_own_status()

    def stop(self) -> None:
        self._stop.set()
        try:
            connect_named_pipe(self.pipe, timeout=1).close()
        except (IpcError, pywintypes.error):
            self.listener.close()

    def _serve_client(self, connection: PipeConnection) -> None:
        try:
            with connection:
                server_handshake(
                    connection,
                    self.instance_token,
                    timeout=IPC_HANDSHAKE_TIMEOUT_SECONDS,
                )
                while not self._stop.is_set():
                    request = connection.receive(
                        frame_timeout=IPC_FRAME_TIMEOUT_SECONDS
                    )
                    response = self._dispatch(request)
                    connection.send(response)
        except IpcError:
            pass
        finally:
            with self._thread_lock:
                self._client_threads.discard(threading.current_thread())

    def _dispatch(self, request: Envelope) -> Envelope:
        try:
            payload = self._handle_request(request.message_type, request.payload)
            response_type = f"{request.message_type}.result"
        except (ServerOpsError, ValueError) as error:
            payload = {
                "code": getattr(error, "code", "invalid_request"),
                "message": str(error),
            }
            response_type = "error"
        except Exception:
            payload = {
                "code": "broker_internal_error",
                "message": "broker request failed safely",
            }
            response_type = "error"
        return Envelope.create(response_type, payload, message_id=request.message_id)

    def _handle_request(
        self,
        message_type: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        payload = dict(payload)
        if message_type == "broker.ping":
            self._require_fields(payload, set())
            return {
                "pid": os.getpid(),
                "protocol_version": BROKER_PROTOCOL_VERSION,
                "ipc_current_user_only": self.ipc_security_report.current_user_only,
            }
        if message_type == "session.create":
            self._require_fields(payload, {"profile_name"})
            return self.supervisor.start(self._profile_name(payload)).public_dict()
        if message_type == "session.open":
            self._require_fields(payload, {"profile_name"})
            return self.supervisor.start(
                self._profile_name(payload),
                open_session=True,
            ).public_dict()
        if message_type == "session.list":
            self._require_fields(payload, set())
            return {"sessions": [record.public_dict() for record in self.supervisor.list()]}
        if message_type == "session.status":
            self._require_fields(payload, {"session_id"})
            return self._request_session(
                self._session_id_value(payload),
                "worker.status",
                timeout=5,
            )
        if message_type == "session.reconnect":
            self._require_fields(payload, {"session_id"})
            result = self._request_session(
                self._session_id_value(payload),
                "worker.status",
                timeout=5,
            )
            return {**result, "reconnected": True, "command_retried": False}
        if message_type == "session.exec":
            self._require_fields(payload, {"session_id", "command"}, optional={"timeout"})
            session_id = self._session_id_value(payload)
            command = payload["command"]
            timeout = payload.get("timeout")
            if not isinstance(command, str):
                raise ValueError("command must be a string")
            worker_payload: dict[str, object] = {"command": command}
            if timeout is not None:
                if isinstance(timeout, bool) or not isinstance(timeout, int | float):
                    raise ValueError("timeout must be a number")
                worker_payload["timeout"] = timeout
            return self._request_session(
                session_id,
                "worker.exec",
                worker_payload,
                timeout=3_730,
            )
        if message_type == "session.terminal":
            if "session_id" not in payload:
                raise ValueError("session_id is required")
            session_id = self._session_id_value(payload)
            worker_payload = dict(payload)
            del worker_payload["session_id"]
            return self._request_session(
                session_id,
                "worker.terminal",
                worker_payload,
                timeout=70,
            )
        if message_type in {"session.files", "session.file_edit"}:
            if "session_id" not in payload:
                raise ValueError("session_id is required")
            session_id = self._session_id_value(payload)
            worker_payload = dict(payload)
            del worker_payload["session_id"]
            worker_type = (
                "worker.files" if message_type == "session.files" else "worker.file_edit"
            )
            return self._request_session(
                session_id,
                worker_type,
                worker_payload,
                timeout=3_730,
            )
        if message_type == "session.elevation":
            return self._handle_elevation(payload)
        if message_type == "session.close":
            self._require_fields(payload, {"session_id"})
            session_id = self._session_id_value(payload)
            record = self.supervisor.shutdown(session_id)
            return self._session_metadata(record, {"status": "closed"})
        if message_type == "broker.shutdown":
            self._require_fields(payload, set())
            self.stop()
            return {"status": "closing"}
        raise BrokerRequestError(f"unknown broker message type: {message_type}")

    def _handle_elevation(self, payload: dict[str, object]) -> dict[str, object]:
        action = payload.get("action")
        if not isinstance(action, str):
            raise ValueError("elevation action must be a string")
        required, optional = self._elevation_fields(action)
        self._require_fields(payload, required | {"action", "session_id"}, optional=optional)
        session_id = self._session_id_value(payload)
        record = self.supervisor.get(session_id)
        if action == "open_root_session":
            if record.root_session:
                raise BrokerRequestError("a root session cannot open another root session")
            opened = self.supervisor.start(
                record.profile_name,
                open_session=True,
                root_session=True,
                parent_session_id=session_id,
            )
            return {**opened.public_dict(), "status": "opened"}
        if action == "close_root_session":
            if not record.root_session:
                raise BrokerRequestError("close_root_session requires a root session ID")
            closed = self.supervisor.shutdown(session_id)
            return self._session_metadata(closed, {
                "status": "closed",
                "root_session": True,
                "elevated": True,
            })
        if record.root_session:
            raise BrokerRequestError("sudo cache actions require a normal session ID")
        worker_payload = dict(payload)
        del worker_payload["session_id"]
        return self._request_session(
            session_id,
            "worker.elevation",
            worker_payload,
            timeout=3_730,
        )

    def _request_session(
        self,
        session_id: str,
        message_type: str,
        payload: dict[str, object] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, object]:
        record = self.supervisor.get(session_id)
        result = self.supervisor.request(
            session_id,
            message_type,
            payload,
            timeout=timeout,
        )
        return self._session_metadata(record, result)

    @staticmethod
    def _session_metadata(
        record: SessionRecord,
        result: dict[str, object],
    ) -> dict[str, object]:
        public = record.public_dict()
        metadata = {
            "session_id": public["session_id"],
            "profile_name": public["profile_name"],
            "ssh_user": public["ssh_user"],
            "effective_user": public["effective_user"],
            "elevated": public["elevated"],
            "root_session": public["root_session"],
        }
        return {**metadata, **result}

    @staticmethod
    def _require_fields(
        payload: dict[str, object],
        required: set[str],
        *,
        optional: set[str] = frozenset(),
    ) -> None:
        fields = set(payload)
        if not required.issubset(fields) or not fields.issubset(required | set(optional)):
            raise ValueError("request payload fields do not match the operation")

    @staticmethod
    def _elevation_fields(action: str) -> tuple[set[str], set[str]]:
        operations = {
            "acquire": (set(), set()),
            "status": (set(), set()),
            "release": (set(), set()),
            "exec": ({"command"}, {"timeout"}),
            "open_root_session": (set(), set()),
            "close_root_session": (set(), set()),
        }
        try:
            return operations[action]
        except KeyError as error:
            raise ValueError(f"unsupported elevation action: {action}") from error

    @staticmethod
    def _profile_name(payload: dict[str, object]) -> str:
        profile_name = payload["profile_name"]
        if not isinstance(profile_name, str):
            raise ValueError("profile_name must be a string")
        validate_profile_name(profile_name)
        return profile_name

    @staticmethod
    def _session_id_value(payload: dict[str, object]) -> str:
        session_id = payload["session_id"]
        if not isinstance(session_id, str):
            raise ValueError("session_id must be a string")
        validate_session_id(session_id)
        return session_id

    def _join_clients(self) -> None:
        with self._thread_lock:
            threads = tuple(self._client_threads)
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(timeout=2)

    def _remove_own_status(self) -> None:
        try:
            status = self.runtime.read_json(self.runtime.broker_status_path)
        except (FileNotFoundError, ValueError):
            return
        if status.get("instance_token") == self.instance_token:
            self.runtime.broker_status_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path)
    args = parser.parse_args()
    server = BrokerServer(args.runtime.resolve() if args.runtime else None)
    server.serve_forever()

if __name__ == "__main__":
    main()
