from __future__ import annotations

import os
import time
from pathlib import Path

from codex_serverops_mcp.ipc.security import secure_path_for_current_user
from codex_serverops_mcp.runtime import RuntimeDirectory, default_runtime_path

from .model import SetupRecord, SetupRequest, SetupStatus, validate_setup_request_id


class SetupRequestStore:
    def __init__(self, runtime_path: Path | None = None) -> None:
        root = (runtime_path or default_runtime_path()).resolve()
        self.runtime = RuntimeDirectory(root)
        self.path = root / "setup"

    def prepare(self) -> None:
        self.runtime.prepare()
        self.path.mkdir(parents=True, exist_ok=True)
        secure_path_for_current_user(str(self.path), directory=True)

    def create(self, request: SetupRequest) -> SetupRecord:
        self.prepare()
        path = self._path(request.request_id)
        if path.exists():
            raise FileExistsError("setup request already exists")
        record = SetupRecord(request, SetupStatus.PENDING, request.created_at)
        self._write_new(path, record)
        return record

    def load(self, request_id: str) -> SetupRecord:
        path = self._path(request_id)
        if not path.is_file():
            raise FileNotFoundError(f"setup request does not exist: {request_id}")
        return SetupRecord.from_dict(self.runtime.read_json(path))

    def update(
        self,
        request_id: str,
        status: SetupStatus,
        *,
        result: dict[str, object] | None = None,
        message: str | None = None,
        now: float | None = None,
    ) -> SetupRecord:
        current = self.load(request_id)
        if current.status.terminal:
            raise ValueError("completed setup requests cannot be changed")
        record = SetupRecord(
            current.request,
            status,
            time.time() if now is None else now,
            result=result,
            message=message,
        )
        self.runtime.write_json(self._path(request_id), record.to_dict())
        return record

    def expire_if_needed(self, request_id: str, *, now: float | None = None) -> SetupRecord:
        record = self.load(request_id)
        current_time = time.time() if now is None else now
        if not record.status.terminal and current_time >= record.request.expires_at:
            return self.update(
                request_id,
                SetupStatus.EXPIRED,
                message="The local setup request expired before completion.",
                now=current_time,
            )
        return record

    def _path(self, request_id: str) -> Path:
        validate_setup_request_id(request_id)
        return self.path / f"{request_id}.json"

    def _write_new(self, path: Path, record: SetupRecord) -> None:
        # Reserve the name first so two launchers cannot replace each other's request.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        secure_path_for_current_user(str(path))
        try:
            self.runtime.write_json(path, record.to_dict())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
