from __future__ import annotations

from typing import Any

import pywintypes
import win32api
import win32com.client
import win32con

from codex_serverops_mcp.errors import ServerOpsError

from .task_model import (
    BrokerTaskSpec,
    BrokerTaskStatus,
    broker_task_name,
    managed_description_matches,
)

TASK_ACTION_EXEC = 0
TASK_CREATE_OR_UPDATE = 6
TASK_INSTANCES_IGNORE_NEW = 2
TASK_LOGON_INTERACTIVE_TOKEN = 3
TASK_RUNLEVEL_LUA = 0
TASK_STATE_RUNNING = 4
TASK_TRIGGER_LOGON = 9
ERROR_FILE_NOT_FOUND_HRESULT = 0x80070002


def _managed_definition(
    definition: Any,
    description: str,
    executable: str | None,
    arguments: str | None,
    trigger: Any | None,
    account_name: str,
) -> bool:
    if executable is None or arguments is None or trigger is None:
        return False
    try:
        return (
            managed_description_matches(description, executable, arguments)
            and str(definition.Principal.UserId) == account_name
            and int(definition.Principal.LogonType) == TASK_LOGON_INTERACTIVE_TOKEN
            and int(definition.Principal.RunLevel) == TASK_RUNLEVEL_LUA
            and bool(trigger.Enabled)
            and str(trigger.UserId) == account_name
        )
    except (AttributeError, TypeError, ValueError, pywintypes.com_error):
        return False


class BrokerTaskError(ServerOpsError):
    code = "broker_task_error"


class BrokerTaskUnavailable(BrokerTaskError):
    code = "broker_task_unavailable"


class BrokerTaskController:
    def __init__(self, service: Any, *, account_name: str, task_name: str) -> None:
        self.service = service
        self.account_name = account_name
        self.task_name = task_name
        self.root = service.GetFolder("\\")

    @classmethod
    def connect(cls) -> BrokerTaskController:
        try:
            service = win32com.client.Dispatch("Schedule.Service")
            service.Connect()
            account = win32api.GetUserNameEx(win32con.NameSamCompatible)
            return cls(service, account_name=account, task_name=broker_task_name())
        except pywintypes.com_error as error:
            raise BrokerTaskUnavailable("Windows Task Scheduler is unavailable") from error

    def inspect(self) -> BrokerTaskStatus:
        task = self._get_task()
        if task is None:
            return BrokerTaskStatus(self.task_name, False, False, False)
        description = str(task.Definition.RegistrationInfo.Description or "")
        definition = task.Definition
        action = definition.Actions.Item(1) if definition.Actions.Count == 1 else None
        trigger = definition.Triggers.Item(1) if definition.Triggers.Count == 1 else None
        executable = str(action.Path) if action is not None else None
        arguments = str(action.Arguments) if action is not None else None
        managed = _managed_definition(
            definition,
            description,
            executable,
            arguments,
            trigger,
            self.account_name,
        )
        return BrokerTaskStatus(
            name=self.task_name,
            exists=True,
            managed=managed,
            running=int(task.State) == TASK_STATE_RUNNING,
            executable=executable,
            arguments=arguments,
        )

    def register(self, spec: BrokerTaskSpec) -> BrokerTaskStatus:
        spec.validate()
        existing = self.inspect()
        if existing.exists and not existing.managed:
            raise BrokerTaskError(
                f"refusing to replace unmanaged scheduled task: {self.task_name}"
            )
        definition = self.service.NewTask(0)
        definition.RegistrationInfo.Description = spec.description
        definition.Principal.UserId = self.account_name
        definition.Principal.LogonType = TASK_LOGON_INTERACTIVE_TOKEN
        definition.Principal.RunLevel = TASK_RUNLEVEL_LUA
        settings = definition.Settings
        settings.Enabled = True
        settings.AllowDemandStart = True
        settings.StartWhenAvailable = True
        settings.Hidden = False
        settings.DisallowStartIfOnBatteries = False
        settings.StopIfGoingOnBatteries = False
        settings.ExecutionTimeLimit = "PT0S"
        settings.MultipleInstances = TASK_INSTANCES_IGNORE_NEW
        trigger = definition.Triggers.Create(TASK_TRIGGER_LOGON)
        trigger.Enabled = True
        trigger.UserId = self.account_name
        action = definition.Actions.Create(TASK_ACTION_EXEC)
        action.Path = str(spec.executable)
        action.Arguments = spec.argument_line
        if spec.working_directory is not None:
            action.WorkingDirectory = str(spec.working_directory)
        try:
            self.root.RegisterTaskDefinition(
                self.task_name,
                definition,
                TASK_CREATE_OR_UPDATE,
                self.account_name,
                None,
                TASK_LOGON_INTERACTIVE_TOKEN,
            )
        except pywintypes.com_error as error:
            raise BrokerTaskError("could not register the per-user broker task") from error
        return self.inspect()

    def start_if_installed(self) -> bool:
        status = self.inspect()
        if not status.exists:
            return False
        if not status.managed:
            raise BrokerTaskError(
                f"scheduled task name is occupied by an unmanaged task: {self.task_name}"
            )
        try:
            self.root.GetTask(self.task_name).Run("")
        except pywintypes.com_error as error:
            raise BrokerTaskError("could not start the managed broker task") from error
        return True

    def remove(self) -> bool:
        status = self.inspect()
        if not status.exists:
            return False
        if not status.managed:
            raise BrokerTaskError(
                f"refusing to remove unmanaged scheduled task: {self.task_name}"
            )
        try:
            self.root.DeleteTask(self.task_name, 0)
        except pywintypes.com_error as error:
            raise BrokerTaskError("could not remove the managed broker task") from error
        return True

    def _get_task(self) -> Any | None:
        try:
            return self.root.GetTask(self.task_name)
        except pywintypes.com_error as error:
            if _hresult(error) == ERROR_FILE_NOT_FOUND_HRESULT:
                return None
            raise BrokerTaskUnavailable("could not inspect the per-user broker task") from error


def _hresult(error: pywintypes.com_error) -> int:
    details = error.excepinfo
    if (
        isinstance(details, tuple)
        and len(details) > 5
        and isinstance(details[5], int)
        and details[5] != 0
    ):
        return details[5] & 0xFFFFFFFF
    return int(error.hresult) & 0xFFFFFFFF
