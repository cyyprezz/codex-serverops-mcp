from __future__ import annotations

import os
import threading
import time

if os.name != "nt":  # pragma: no cover - product IPC is Windows-only
    raise ImportError("Windows named pipes are available only on Windows")

import pywintypes
import win32con
import win32file
import win32pipe

from .connection import PipeConnection
from .constants import PIPE_BUFFER_BYTES
from .errors import IpcClosed, IpcError
from .security import (
    PipeSecurityReport,
    current_user_security_attributes,
    require_current_user_only,
)

PIPE_CONNECTED = 535
RETRYABLE_CONNECT_ERRORS = {2, 121, 231}


def _validate_pipe_name(path: str) -> None:
    if not path.startswith(r"\\.\pipe\codex-serverops-") or len(path) > 240:
        raise ValueError("named-pipe path is outside the ServerOps namespace")


class NamedPipeListener:
    def __init__(self, path: str) -> None:
        _validate_pipe_name(path)
        self.path = path
        self._closed = False
        self._created_any = False
        self._pending: object | None = None
        self._connecting: object | None = None
        self._lock = threading.Lock()
        self._accept_lock = threading.Lock()
        self._pending = self._create_instance(first=True)

    @property
    def security_report(self) -> PipeSecurityReport:
        with self._lock:
            handle = self._pending
        if handle is None:
            raise IpcError("no pending pipe instance is available for inspection")
        return require_current_user_only(handle)

    def accept(self) -> PipeConnection:
        with self._accept_lock:
            with self._lock:
                if self._closed:
                    raise IpcClosed("named-pipe listener is closed")
                handle = self._pending or self._create_instance(first=False)
                self._pending = None
                self._connecting = handle
            try:
                try:
                    win32pipe.ConnectNamedPipe(handle, None)
                except pywintypes.error as error:
                    if error.winerror != PIPE_CONNECTED:
                        raise
                require_current_user_only(handle)
                with self._lock:
                    if self._closed or self._connecting is not handle:
                        raise IpcClosed("named-pipe listener closed during accept")
                    # Transfer handle ownership to the returned connection before
                    # close() can observe it as listener-owned.
                    self._connecting = None
                return PipeConnection(handle, server_side=True)
            except BaseException:
                with self._lock:
                    was_closed = self._closed
                    listener_owns_handle = self._connecting is handle
                    if listener_owns_handle:
                        self._connecting = None
                if listener_owns_handle and not was_closed:
                    win32file.CloseHandle(handle)
                raise

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            handles = tuple(
                handle for handle in (self._pending, self._connecting) if handle is not None
            )
            self._pending = None
            self._connecting = None
        for handle in handles:
            win32file.CloseHandle(handle)

    def _create_instance(self, *, first: bool) -> object:
        open_mode = win32pipe.PIPE_ACCESS_DUPLEX
        if first and not self._created_any:
            open_mode |= win32pipe.FILE_FLAG_FIRST_PIPE_INSTANCE
        handle = win32pipe.CreateNamedPipe(
            self.path,
            open_mode,
            win32pipe.PIPE_TYPE_BYTE
            | win32pipe.PIPE_READMODE_BYTE
            | win32pipe.PIPE_WAIT
            | win32pipe.PIPE_REJECT_REMOTE_CLIENTS,
            win32pipe.PIPE_UNLIMITED_INSTANCES,
            PIPE_BUFFER_BYTES,
            PIPE_BUFFER_BYTES,
            5_000,
            current_user_security_attributes(),
        )
        self._created_any = True
        require_current_user_only(handle)
        return handle

    def __enter__(self) -> NamedPipeListener:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def connect_named_pipe(path: str, *, timeout: float = 5) -> PipeConnection:
    _validate_pipe_name(path)
    deadline = time.monotonic() + timeout
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            remaining_ms = max(1, round((deadline - time.monotonic()) * 1_000))
            win32pipe.WaitNamedPipe(path, remaining_ms)
            handle = win32file.CreateFile(
                path,
                win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                0,
                None,
                win32con.OPEN_EXISTING,
                0,
                None,
            )
            try:
                require_current_user_only(handle)
            except BaseException:
                win32file.CloseHandle(handle)
                raise
            return PipeConnection(handle)
        except pywintypes.error as error:
            last_error = error
            if error.winerror not in RETRYABLE_CONNECT_ERRORS:
                raise IpcError(f"could not connect to named pipe: {error.winerror}") from error
            time.sleep(0.05)
    raise IpcError("timed out connecting to the local named pipe") from last_error
