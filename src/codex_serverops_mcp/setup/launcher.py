from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Protocol


class SetupProcess(Protocol):
    @property
    def pid(self) -> int: ...


class SetupLauncher(Protocol):
    def launch(self, request_id: str) -> SetupProcess: ...


class VisibleSetupProcessLauncher:
    def launch(self, request_id: str) -> SetupProcess:
        executable = self._windowed_python()
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        if executable == Path(sys.executable):
            creationflags |= subprocess.CREATE_NO_WINDOW
        try:
            return subprocess.Popen(
                [
                    str(executable),
                    "-m",
                    "codex_serverops_mcp.setup.app",
                    "--request-id",
                    request_id,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as error:
            raise RuntimeError("the local server setup window could not be started") from error

    @staticmethod
    def _windowed_python() -> Path:
        executable = Path(sys.executable)
        pythonw = executable.with_name("pythonw.exe")
        return pythonw if pythonw.is_file() else executable
