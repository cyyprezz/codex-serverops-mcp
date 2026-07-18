from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from time import monotonic, sleep

from winpty import Backend, PtyProcess, WinptyError

from .buffer import BufferRead, TerminalRingBuffer

if os.name != "nt":  # pragma: no cover - module is deliberately Windows-only
    raise ImportError("The ConPTY backend is available only on Windows")


class ConPtyError(RuntimeError):
    pass


class ConPtyProcess:
    """Own one child process connected to a selected pywinpty backend."""

    def __init__(
        self, *, max_output_bytes: int = 1_048_576, backend: str = "conpty"
    ) -> None:
        try:
            self._backend = {"conpty": Backend.ConPTY, "winpty": Backend.WinPTY}[backend]
        except KeyError as exc:
            raise ValueError("backend must be 'conpty' or 'winpty'") from exc
        self.backend_name = backend
        self.buffer = TerminalRingBuffer(max_output_bytes)
        self._process: PtyProcess | None = None
        self._reader: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self._closed = False
        self._device_attributes_replies = 0
        self._cursor_position_replies = 0
        self._protocol_tail = ""

    @property
    def running(self) -> bool:
        process = self._process
        return process is not None and process.isalive()

    @property
    def output_cursor(self) -> int:
        return self.buffer.end_cursor

    def start(
        self,
        arguments: Sequence[str],
        *,
        cwd: str | Path | None = None,
        environment: dict[str, str] | None = None,
        columns: int = 120,
        rows: int = 30,
    ) -> None:
        if self._process is not None:
            raise ConPtyError("process already started")
        if not arguments:
            raise ValueError("arguments must not be empty")
        if not (1 <= columns <= 32767 and 1 <= rows <= 32767):
            raise ValueError("terminal dimensions are out of range")
        command_line = subprocess.list2cmdline(list(arguments))
        try:
            self._process = PtyProcess.spawn(
                command_line,
                cwd=None if cwd is None else str(cwd),
                env=environment,
                dimensions=(rows, columns),
                backend=self._backend,
            )
        except Exception as exc:
            raise ConPtyError(f"could not start ConPTY child: {exc}") from exc
        self._reader = threading.Thread(
            target=self._read_output, name="serverops-conpty-reader", daemon=True
        )
        self._reader.start()

    def write(self, data: bytes) -> None:
        if not data:
            return
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("ConPTY input must be valid UTF-8") from exc
        self._write_text(text)

    def interrupt(self) -> None:
        process = self._require_process()
        if self._closed:
            raise ConPtyError("terminal input is closed")
        with self._write_lock:
            try:
                process.sendintr()
            except Exception as exc:
                raise ConPtyError(f"could not send ConPTY interrupt: {exc}") from exc

    def resize(self, columns: int, rows: int) -> None:
        if not (1 <= columns <= 32767 and 1 <= rows <= 32767):
            raise ValueError("terminal dimensions are out of range")
        process = self._require_process()
        if self._closed:
            raise ConPtyError("pseudoconsole is closed")
        try:
            process.setwinsize(rows, columns)
        except Exception as exc:
            raise ConPtyError(f"could not resize ConPTY: {exc}") from exc

    def read(self, cursor: int) -> BufferRead:
        return self.buffer.read(cursor)

    def wait_for_data(self, cursor: int, timeout: float | None = None) -> BufferRead:
        return self.buffer.wait_for_data(cursor, timeout)

    def wait(self, timeout: float | None = None) -> int | None:
        process = self._require_process()
        deadline = None if timeout is None else monotonic() + timeout
        while process.isalive():
            if deadline is not None and monotonic() >= deadline:
                return None
            sleep(0.01)
        return process.wait()

    def terminate(self, exit_code: int = 1) -> None:
        del exit_code  # pywinpty/ConPTY chooses the forced termination status.
        process = self._process
        if process is not None and process.isalive():
            try:
                process.terminate(force=True)
            except Exception as exc:
                raise ConPtyError(f"could not terminate ConPTY child: {exc}") from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        if process is not None:
            with suppress(EOFError, OSError, WinptyError):
                process.close(force=True)
            # pywinpty 3.0.5 marks PtyProcess.closed as soon as isalive() sees
            # process exit. Its close() then skips the two local relay sockets,
            # so close them explicitly and cancel the native blocking read.
            with suppress(Exception):
                process.pty.cancel_io()
            with suppress(Exception):
                process.fileobj.close()
            with suppress(Exception):
                process._server.close()  # noqa: SLF001 - pywinpty lifecycle workaround
        reader = self._reader
        if reader is not None:
            reader.join(timeout=2)
        self.buffer.close()

    def _require_process(self) -> PtyProcess:
        process = self._process
        if process is None:
            raise ConPtyError("process has not been started")
        return process

    def _write_text(self, text: str) -> None:
        process = self._require_process()
        if self._closed:
            raise ConPtyError("terminal input is closed")
        with self._write_lock:
            try:
                process.write(text)
            except Exception as exc:
                raise ConPtyError(f"could not write ConPTY input: {exc}") from exc

    def _read_output(self) -> None:
        process = self._require_process()
        try:
            while process.isalive():
                try:
                    text = process.read(4096)
                except (EOFError, OSError, WinptyError):
                    break
                if not text:
                    continue
                self.buffer.append(text.encode("utf-8"))
                self._answer_terminal_protocol_queries(text)
        finally:
            self.buffer.close()

    def _answer_terminal_protocol_queries(self, text: str) -> None:
        # A raw ConPTY host must answer terminal queries. Without the primary DA
        # response, a newly attached cmd.exe/ssh.exe can remain blocked before its
        # first prompt. Keep a short tail so escape sequences may cross reads.
        combined = self._protocol_tail + text
        self._protocol_tail = combined[-16:]
        device_queries = combined.count("\x1b[c")
        if device_queries > self._device_attributes_replies:
            for _ in range(device_queries - self._device_attributes_replies):
                self._write_text("\x1b[?1;0c")
            self._device_attributes_replies = device_queries
        cursor_queries = combined.count("\x1b[6n")
        if cursor_queries > self._cursor_position_replies:
            for _ in range(cursor_queries - self._cursor_position_replies):
                self._write_text("\x1b[1;1R")
            self._cursor_position_replies = cursor_queries

    def __enter__(self) -> ConPtyProcess:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
