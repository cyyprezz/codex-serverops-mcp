from __future__ import annotations

import os
import time
from pathlib import Path
from types import TracebackType


class AuditFileLock:
    def __init__(self, path: Path, *, timeout: float = 5.0) -> None:
        self.path = path
        self.timeout = timeout
        self._file: object | None = None

    def __enter__(self) -> AuditFileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _secure_for_current_user(self.path.parent, directory=True)
        lock_file = self.path.open("a+b")
        if lock_file.seek(0, os.SEEK_END) == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        _secure_for_current_user(self.path, directory=False)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover - product runtime is Windows
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._file = lock_file
                return self
            except OSError as error:
                if time.monotonic() >= deadline:
                    lock_file.close()
                    raise TimeoutError("timed out waiting for the audit log lock") from error
                time.sleep(0.05)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        lock_file = self._file
        self._file = None
        if lock_file is None:
            return
        try:
            lock_file.seek(0)  # type: ignore[attr-defined]
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
            else:  # pragma: no cover - product runtime is Windows
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
        finally:
            lock_file.close()  # type: ignore[attr-defined]


def _secure_for_current_user(path: Path, *, directory: bool) -> None:
    if os.name == "nt":
        from codex_serverops_mcp.ipc.security import secure_path_for_current_user

        secure_path_for_current_user(str(path), directory=directory)
    else:  # pragma: no cover - production target is Windows
        path.chmod(0o700 if directory else 0o600)
