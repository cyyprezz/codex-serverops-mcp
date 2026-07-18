from __future__ import annotations

import os
import struct
import threading
import time
from contextlib import suppress

if os.name != "nt":  # pragma: no cover - product IPC is Windows-only
    raise ImportError("Windows named-pipe connections are available only on Windows")

import pywintypes
import win32file
import win32pipe

from .constants import MAX_IPC_MESSAGE_BYTES
from .errors import IpcClosed, IpcMessageError, IpcTimeout
from .messages import Envelope, decode_envelope, encode_envelope

LENGTH_PREFIX = struct.Struct("!I")
BROKEN_PIPE_ERRORS = {109, 232, 233}


class PipeConnection:
    def __init__(self, handle: object, *, server_side: bool = False) -> None:
        self._handle = handle
        self._server_side = server_side
        self._write_lock = threading.Lock()
        self._closed = False

    def send(self, envelope: Envelope, *, max_bytes: int = MAX_IPC_MESSAGE_BYTES) -> None:
        payload = encode_envelope(envelope, max_bytes=max_bytes)
        self.send_bytes(payload, max_bytes=max_bytes)

    def receive(
        self,
        *,
        max_bytes: int = MAX_IPC_MESSAGE_BYTES,
        timeout: float | None = None,
    ) -> Envelope:
        return decode_envelope(
            self.receive_bytes(max_bytes=max_bytes, timeout=timeout),
            max_bytes=max_bytes,
        )

    def send_bytes(
        self,
        payload: bytes | bytearray,
        *,
        max_bytes: int = MAX_IPC_MESSAGE_BYTES,
    ) -> None:
        if not payload or len(payload) > max_bytes:
            raise IpcMessageError(f"message exceeds the {max_bytes}-byte limit")
        frame = bytearray(LENGTH_PREFIX.pack(len(payload)))
        frame.extend(payload)
        try:
            with self._write_lock:
                self._write_all(frame)
        finally:
            if isinstance(payload, bytearray):
                frame[:] = b"\0" * len(frame)

    def receive_bytes(
        self,
        *,
        max_bytes: int = MAX_IPC_MESSAGE_BYTES,
        timeout: float | None = None,
    ) -> bytes:
        deadline = None if timeout is None else time.monotonic() + max(0, timeout)
        length = LENGTH_PREFIX.unpack(
            self._read_exact(LENGTH_PREFIX.size, deadline=deadline)
        )[0]
        if length < 1 or length > max_bytes:
            raise IpcMessageError(f"declared message length exceeds the {max_bytes}-byte limit")
        return self._read_exact(length, deadline=deadline)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        if self._server_side:
            with suppress(pywintypes.error):
                win32file.FlushFileBuffers(handle)
            with suppress(pywintypes.error):
                win32pipe.DisconnectNamedPipe(handle)
        win32file.CloseHandle(handle)

    def _read_exact(self, size: int, *, deadline: float | None = None) -> bytes:
        if self._closed or self._handle is None:
            raise IpcClosed("named-pipe connection is closed")
        chunks = bytearray()
        while len(chunks) < size:
            read_size = size - len(chunks)
            if deadline is not None:
                read_size = min(read_size, self._wait_for_available_bytes(deadline))
            try:
                _status, chunk = win32file.ReadFile(self._handle, read_size)
            except pywintypes.error as error:
                if error.winerror in BROKEN_PIPE_ERRORS:
                    raise IpcClosed("named-pipe peer closed the connection") from error
                raise
            if not chunk:
                raise IpcClosed("named-pipe peer returned end of stream")
            chunks.extend(chunk)
        return bytes(chunks)

    def _wait_for_available_bytes(self, deadline: float) -> int:
        while True:
            if self._closed or self._handle is None:
                raise IpcClosed("named-pipe connection is closed")
            try:
                _data, available, _remaining = win32pipe.PeekNamedPipe(self._handle, 0)
            except pywintypes.error as error:
                if error.winerror in BROKEN_PIPE_ERRORS:
                    raise IpcClosed("named-pipe peer closed the connection") from error
                raise
            if available > 0:
                return available
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise IpcTimeout("timed out waiting for a named-pipe message")
            time.sleep(min(0.01, remaining))

    def _write_all(self, data: bytes | bytearray) -> None:
        if self._closed or self._handle is None:
            raise IpcClosed("named-pipe connection is closed")
        offset = 0
        while offset < len(data):
            try:
                _status, written = win32file.WriteFile(self._handle, data[offset:])
            except pywintypes.error as error:
                if error.winerror in BROKEN_PIPE_ERRORS:
                    raise IpcClosed("named-pipe peer closed the connection") from error
                raise
            if written < 1:
                raise IpcClosed("named-pipe write made no progress")
            offset += written

    def __enter__(self) -> PipeConnection:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
