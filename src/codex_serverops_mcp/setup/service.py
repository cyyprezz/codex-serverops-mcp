from __future__ import annotations

import time
from dataclasses import dataclass

from .launcher import SetupLauncher, VisibleSetupProcessLauncher
from .model import SetupAction, SetupRequest, SetupStatus
from .store import SetupRequestStore


@dataclass(slots=True)
class SetupCoordinator:
    store: SetupRequestStore
    launcher: SetupLauncher

    @classmethod
    def create(cls) -> SetupCoordinator:
        return cls(SetupRequestStore(), VisibleSetupProcessLauncher())

    def start(
        self,
        action: str,
        *,
        profile_name: str | None = None,
        suggested_host: str | None = None,
        suggested_user: str | None = None,
    ) -> dict[str, object]:
        try:
            setup_action = SetupAction(action)
        except ValueError as error:
            raise ValueError(f"unsupported setup action: {action}") from error
        request = SetupRequest.create(
            setup_action,
            profile_name=profile_name,
            suggested_host=suggested_host,
            suggested_user=suggested_user,
        )
        record = self.store.create(request)
        try:
            self.launcher.launch(request.request_id)
        except Exception as error:
            self.store.update(
                request.request_id,
                SetupStatus.FAILED,
                message="The local setup window could not be started.",
            )
            raise RuntimeError("the local setup window could not be started") from error
        return record.public_result()

    def status(self, request_id: str) -> dict[str, object]:
        return self.store.expire_if_needed(request_id).public_result()

    def wait(self, request_id: str, timeout: float) -> dict[str, object]:
        if isinstance(timeout, bool) or not isinstance(timeout, int | float):
            raise ValueError("wait_timeout must be a number")
        if not 0.1 <= timeout <= 30:
            raise ValueError("wait_timeout must be from 0.1 through 30 seconds")
        deadline = time.monotonic() + float(timeout)
        while True:
            record = self.store.expire_if_needed(request_id)
            if record.status.terminal or time.monotonic() >= deadline:
                return record.public_result()
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
