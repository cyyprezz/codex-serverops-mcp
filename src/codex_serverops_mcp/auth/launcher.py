from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol

from .errors import AuthenticationLaunchError
from .server import AuthLaunchDescriptor

AUTH_TOKEN_ENVIRONMENT = "SERVEROPS_AUTH_TOKEN"


class AuthProcess(Protocol):
    def wait(self, timeout: float | None = None) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class AuthLauncher(Protocol):
    def launch(self, descriptor: AuthLaunchDescriptor) -> AuthProcess: ...


class VisibleAuthProcessLauncher:
    def launch(self, descriptor: AuthLaunchDescriptor) -> AuthProcess:
        environment = dict(os.environ)
        environment[AUTH_TOKEN_ENVIRONMENT] = descriptor.token
        executable = self._windowed_python()
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        if executable == Path(sys.executable):
            creationflags |= subprocess.CREATE_NO_WINDOW
        try:
            return subprocess.Popen(
                [
                    str(executable),
                    "-m",
                    "codex_serverops_mcp.auth.app",
                    "--pipe",
                    descriptor.pipe,
                    "--request-id",
                    descriptor.request_id,
                ],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as error:
            raise AuthenticationLaunchError(
                "the local authentication window could not be started"
            ) from error

    @staticmethod
    def _windowed_python() -> Path:
        executable = Path(sys.executable)
        pythonw = executable.with_name("pythonw.exe")
        return pythonw if pythonw.is_file() else executable
