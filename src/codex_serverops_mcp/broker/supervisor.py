from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from codex_serverops_mcp import WORKER_PROTOCOL_VERSION
from codex_serverops_mcp.config.model import validate_profile_name
from codex_serverops_mcp.identifiers import new_session_id, validate_session_id
from codex_serverops_mcp.ipc.connection import PipeConnection
from codex_serverops_mcp.ipc.errors import IpcError
from codex_serverops_mcp.ipc.handshake import client_handshake
from codex_serverops_mcp.ipc.messages import Envelope
from codex_serverops_mcp.ipc.named_pipe import connect_named_pipe
from codex_serverops_mcp.runtime import RuntimeDirectory

from .errors import BrokerRequestError, SessionNotFound, WorkerOperationError
from .model import SessionRecord
from .registry import SessionRegistry


@dataclass(slots=True)
class WorkerHandle:
    record: SessionRecord
    process: subprocess.Popen[bytes]
    connection: PipeConnection
    token: str
    request_lock: threading.Lock

    def request(
        self,
        message_type: str,
        payload: dict[str, object] | None = None,
        *,
        timeout: float | None = None,
    ) -> Envelope:
        request = Envelope.create(message_type, payload)
        with self.request_lock:
            self.connection.send(request)
            response = self.connection.receive(timeout=timeout)
        if response.message_id != request.message_id:
            raise BrokerRequestError("worker response correlation ID does not match")
        if response.message_type == "error":
            code = response.payload.get("code", "worker_error")
            message = response.payload.get("message", "worker operation failed")
            state = response.payload.get("state")
            if not isinstance(code, str) or not isinstance(message, str):
                raise BrokerRequestError("worker error response is invalid")
            if state is not None and not isinstance(state, str):
                raise BrokerRequestError("worker error state is invalid")
            raise WorkerOperationError(code, message, state)
        if response.message_type != f"{message_type}.result":
            raise BrokerRequestError("worker response type does not match the request")
        return response


class WorkerSupervisor:
    def __init__(self, runtime: RuntimeDirectory) -> None:
        self.runtime = runtime
        self.registry = SessionRegistry()
        self._handles: dict[str, WorkerHandle] = {}
        self._lock = threading.RLock()

    def start(
        self,
        profile_name: str,
        *,
        timeout: float = 10,
        open_session: bool = False,
        root_session: bool = False,
        parent_session_id: str | None = None,
    ) -> SessionRecord:
        validate_profile_name(profile_name)
        if root_session:
            if not open_session or parent_session_id is None:
                raise ValueError("a root worker requires an open parent session")
            validate_session_id(parent_session_id)
        elif parent_session_id is not None:
            raise ValueError("a normal worker cannot have a parent session")
        session_id = new_session_id()
        token = secrets.token_urlsafe(32)
        status_path = self.runtime.worker_status_path(session_id)
        status_path.unlink(missing_ok=True)
        environment = dict(os.environ)
        environment["SERVEROPS_WORKER_TOKEN"] = token
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        worker_arguments = [
            sys.executable,
            "-m",
            "codex_serverops_mcp.worker.process",
            "--session-id",
            session_id,
            "--profile",
            profile_name,
            "--runtime",
            str(self.runtime.path),
        ]
        if root_session:
            worker_arguments.append("--root-session")
        process = subprocess.Popen(
            worker_arguments,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        connection: PipeConnection | None = None
        handle: WorkerHandle | None = None
        try:
            status = self._wait_for_status(status_path, process, timeout)
            self._validate_status(status, session_id, profile_name, root_session=root_session)
            pipe = str(status["pipe"])
            connection = connect_named_pipe(pipe, timeout=timeout)
            client_handshake(connection, token, role="broker")
            now = time.time()
            worker_pid = int(status["pid"])
            record = SessionRecord(
                session_id=session_id,
                profile_name=profile_name,
                worker_pid=worker_pid,
                worker_pipe=pipe,
                state=str(status["state"]),
                created_at=now,
                last_activity=now,
                root_session=root_session,
                parent_session_id=parent_session_id,
            )
            handle = WorkerHandle(record, process, connection, token, threading.Lock())
            response = handle.request("worker.ping")
            if response.payload.get("pid") != worker_pid:
                raise BrokerRequestError("worker PID verification failed")
            if open_session:
                opened = handle.request("worker.open", timeout=190)
                if opened.payload.get("state") != "ready":
                    raise BrokerRequestError("worker did not reach the ready state")
                effective_user = opened.payload.get("effective_user")
                ssh_user = opened.payload.get("ssh_user")
                if not isinstance(effective_user, str) or not effective_user:
                    raise BrokerRequestError("worker returned no effective user")
                if not isinstance(ssh_user, str) or not ssh_user:
                    raise BrokerRequestError("worker returned no SSH user")
                record = record.with_open_status(
                    ssh_user=ssh_user,
                    effective_user=effective_user,
                    at=time.time(),
                )
                handle.record = record
            with self._lock:
                self._handles[session_id] = handle
                self.registry.add(record)
            return record
        except BaseException:
            if handle is not None:
                with suppress(BrokerRequestError, IpcError):
                    handle.request("worker.shutdown", timeout=5)
            if connection is not None:
                connection.close()
            self._terminate_process(process)
            status_path.unlink(missing_ok=True)
            raise

    def list(self) -> tuple[SessionRecord, ...]:
        self._refresh_dead_workers()
        return self.registry.list()

    def get(self, session_id: str) -> SessionRecord:
        self._refresh_dead_workers()
        return self.registry.get(session_id)

    def request(
        self,
        session_id: str,
        message_type: str,
        payload: dict[str, object] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, object]:
        with self._lock:
            try:
                handle = self._handles[session_id]
            except KeyError as error:
                raise SessionNotFound(f"session does not exist: {session_id}") from error
        try:
            response = handle.request(message_type, payload, timeout=timeout)
        except WorkerOperationError as error:
            if error.state is not None:
                self._update_record_state(session_id, handle, error.state)
            raise
        result = dict(response.payload)
        state = result.get("state")
        if isinstance(state, str) and state != handle.record.state:
            self._update_record_state(session_id, handle, state)
        return result

    def _update_record_state(
        self,
        session_id: str,
        handle: WorkerHandle,
        state: str,
    ) -> None:
        updated = handle.record.with_state(state, at=time.time())
        with self._lock:
            if self._handles.get(session_id) is handle:
                handle.record = updated
                self.registry.replace(updated)

    def shutdown(self, session_id: str) -> SessionRecord:
        with self._lock:
            try:
                handle = self._handles.pop(session_id)
            except KeyError as error:
                raise SessionNotFound(f"session does not exist: {session_id}") from error
        try:
            if handle.process.poll() is None:
                handle.request("worker.shutdown")
        except (BrokerRequestError, IpcError):
            pass
        finally:
            handle.connection.close()
            try:
                handle.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._terminate_process(handle.process)
            self.runtime.worker_status_path(session_id).unlink(missing_ok=True)
        return self.registry.remove(session_id)

    def close_all(self) -> None:
        with self._lock:
            session_ids = tuple(self._handles)
        for session_id in session_ids:
            with suppress(SessionNotFound):
                self.shutdown(session_id)

    def _refresh_dead_workers(self) -> None:
        with self._lock:
            for handle in self._handles.values():
                if handle.process.poll() is not None and handle.record.state != "lost":
                    updated = handle.record.with_state("lost", at=time.time())
                    handle.record = updated
                    self.registry.replace(updated)

    def _wait_for_status(
        self,
        path: Path,
        process: subprocess.Popen[bytes],
        timeout: float,
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise BrokerRequestError(
                    f"worker exited during startup with code {process.returncode}"
                )
            try:
                return self.runtime.read_json(path)
            except FileNotFoundError:
                time.sleep(0.05)
        raise BrokerRequestError("worker did not publish startup status")

    @staticmethod
    def _validate_status(
        status: dict[str, object],
        session_id: str,
        profile_name: str,
        *,
        root_session: bool,
    ) -> None:
        expected_fields = {
            "session_id",
            "profile_name",
            "pid",
            "pipe",
            "protocol_version",
            "state",
            "root_session",
        }
        if set(status) != expected_fields:
            raise BrokerRequestError("worker status fields are invalid")
        if (
            status["session_id"] != session_id
            or status["profile_name"] != profile_name
            or status["protocol_version"] != WORKER_PROTOCOL_VERSION
            or status["state"] != "created"
            or status["root_session"] is not root_session
        ):
            raise BrokerRequestError("worker status identity is invalid")
        if (
            isinstance(status["pid"], bool)
            or not isinstance(status["pid"], int)
            or status["pid"] < 1
            or not isinstance(status["pipe"], str)
        ):
            raise BrokerRequestError("worker process details are invalid")

    @staticmethod
    def _terminate_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
