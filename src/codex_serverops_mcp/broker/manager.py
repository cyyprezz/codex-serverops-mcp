from __future__ import annotations

import os
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

from .client import BrokerClient
from .errors import BrokerUnavailable
from .task_model import production_broker_task_spec
from .task_scheduler import BrokerTaskController, BrokerTaskError, BrokerTaskUnavailable


class BrokerManager:
    def __init__(self, runtime_path: Path | None = None, *, startup_timeout: float = 10) -> None:
        self.runtime_path = runtime_path
        self.startup_timeout = startup_timeout
        self._launched_process: subprocess.Popen[bytes] | None = None

    def connect(self) -> BrokerClient:
        self._validate_installed_task()
        try:
            return BrokerClient(self.runtime_path)
        except BrokerUnavailable:
            self._start_broker()
        deadline = time.monotonic() + self.startup_timeout
        last_error: BrokerUnavailable | None = None
        while time.monotonic() < deadline:
            try:
                return BrokerClient(self.runtime_path)
            except BrokerUnavailable as error:
                last_error = error
                time.sleep(0.05)
        raise BrokerUnavailable("broker did not become reachable") from last_error

    def wait_for_launched_broker(self, timeout: float = 10) -> None:
        process = self._launched_process
        if process is None:
            return
        process.wait(timeout=timeout)
        self._launched_process = None

    @property
    def launched_broker_is_running(self) -> bool:
        process = self._launched_process
        return process is not None and process.poll() is None

    def shutdown_launched_broker(self, timeout: float = 10) -> bool:
        process = self._launched_process
        if process is None:
            return False
        if process.poll() is None:
            with suppress(Exception), BrokerClient(self.runtime_path) as client:
                client.request("broker.shutdown")
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=timeout)
        self._launched_process = None
        return True

    def _start_broker(self) -> None:
        process = self._launched_process
        if process is not None and process.poll() is None:
            return
        if self.runtime_path is None:
            try:
                if BrokerTaskController.connect().start_if_installed(
                    expected=production_broker_task_spec()
                ):
                    return
            except BrokerTaskUnavailable:
                pass
            except BrokerTaskError as error:
                raise BrokerUnavailable("managed broker task could not start") from error
        arguments = [sys.executable, "-m", "codex_serverops_mcp.broker.server"]
        if self.runtime_path is not None:
            arguments.extend(("--runtime", str(self.runtime_path.resolve())))
        creationflags = 0
        if os.name == "nt":
            creationflags = (
                subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
            )
        self._launched_process = subprocess.Popen(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

    def _validate_installed_task(self) -> None:
        if self.runtime_path is not None:
            return
        try:
            BrokerTaskController.connect().inspect_compatible(
                production_broker_task_spec()
            )
        except BrokerTaskUnavailable:
            return
        except BrokerTaskError as error:
            raise BrokerUnavailable(str(error)) from error
