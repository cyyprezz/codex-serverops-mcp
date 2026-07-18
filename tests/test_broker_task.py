from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pywintypes

from codex_serverops_mcp.broker.manager import BrokerManager
from codex_serverops_mcp.broker.task_model import (
    MANAGED_TASK_MARKER,
    BrokerTaskSpec,
    broker_task_name,
    production_broker_task_spec,
    wheel_broker_task_spec,
)
from codex_serverops_mcp.broker.task_scheduler import (
    TASK_INSTANCES_IGNORE_NEW,
    TASK_LOGON_INTERACTIVE_TOKEN,
    TASK_RUNLEVEL_LUA,
    BrokerTaskController,
    BrokerTaskError,
)


class _Collection:
    def __init__(self, factory: type[SimpleNamespace]) -> None:
        self.factory = factory
        self.items: list[SimpleNamespace] = []

    @property
    def Count(self) -> int:
        return len(self.items)

    def Create(self, _kind: int) -> SimpleNamespace:
        item = self.factory()
        self.items.append(item)
        return item

    def Item(self, index: int) -> SimpleNamespace:
        return self.items[index - 1]


def _action() -> SimpleNamespace:
    return SimpleNamespace(Path="", Arguments="", WorkingDirectory="")


def _trigger() -> SimpleNamespace:
    return SimpleNamespace(Enabled=False, UserId="")


def _definition() -> SimpleNamespace:
    return SimpleNamespace(
        RegistrationInfo=SimpleNamespace(Description=""),
        Principal=SimpleNamespace(UserId="", LogonType=None, RunLevel=None),
        Settings=SimpleNamespace(),
        Triggers=_Collection(_trigger),
        Actions=_Collection(_action),
    )


class _Task:
    def __init__(self, definition: SimpleNamespace) -> None:
        self.Definition = definition
        self.State = 3
        self.run_count = 0

    def Run(self, _parameters: str) -> None:
        self.run_count += 1
        self.State = 4


class _Root:
    def __init__(self) -> None:
        self.tasks: dict[str, _Task] = {}

    def GetTask(self, name: str) -> _Task:
        try:
            return self.tasks[name]
        except KeyError as error:
            raise pywintypes.com_error(
                -2147352567,
                "wrapped COM error",
                (0, None, None, None, 0, -2147024894),
                None,
            ) from error

    def RegisterTaskDefinition(
        self,
        name: str,
        definition: SimpleNamespace,
        *_arguments: object,
    ) -> _Task:
        task = _Task(definition)
        self.tasks[name] = task
        return task

    def DeleteTask(self, name: str, _flags: int) -> None:
        del self.tasks[name]


class _Service:
    def __init__(self) -> None:
        self.root = _Root()

    def GetFolder(self, path: str) -> _Root:
        if path != "\\":
            raise AssertionError("unexpected task folder")
        return self.root

    @staticmethod
    def NewTask(_flags: int) -> SimpleNamespace:
        return _definition()


class BrokerTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = _Service()
        self.controller = BrokerTaskController(
            self.service,
            account_name="EXAMPLE\\operator",
            task_name="Codex ServerOps MCP Broker test",
        )
        self.spec = BrokerTaskSpec(
            executable=Path(sys.executable),
            arguments=("-m", "codex_serverops_mcp.broker.server"),
            source="unit-test",
        )

    def test_task_identity_and_pinned_production_action_are_deterministic(self) -> None:
        self.assertEqual(broker_task_name("S-1-5-21-test"), broker_task_name("S-1-5-21-test"))
        spec = production_broker_task_spec(version="0.1.0", uvx_path=sys.executable)
        self.assertEqual(
            spec.arguments,
            ("--from", "codex-serverops-mcp==0.1.0", "serverops-broker"),
        )

    def test_development_wheel_action_pins_its_offline_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "dist").mkdir()
            (root / ".uv-cache").mkdir()
            wheel = root / "dist" / "candidate.whl"
            wheel.touch()

            spec = wheel_broker_task_spec(
                wheel,
                uvx_path=sys.executable,
                python_path=sys.executable,
            )

            self.assertEqual(
                spec.arguments,
                (
                    "--python",
                    str(Path(sys.executable).resolve()),
                    "--cache-dir",
                    str(root / ".uv-cache"),
                    "--offline",
                    "--from",
                    str(wheel),
                    "serverops-broker",
                ),
            )

    def test_registers_least_privilege_no_password_current_user_task(self) -> None:
        status = self.controller.register(self.spec)

        self.assertTrue(status.exists)
        self.assertTrue(status.managed)
        task = self.service.root.tasks[self.controller.task_name]
        definition = task.Definition
        self.assertIn(MANAGED_TASK_MARKER, definition.RegistrationInfo.Description)
        self.assertEqual(definition.Principal.UserId, "EXAMPLE\\operator")
        self.assertEqual(definition.Principal.LogonType, TASK_LOGON_INTERACTIVE_TOKEN)
        self.assertEqual(definition.Principal.RunLevel, TASK_RUNLEVEL_LUA)
        self.assertEqual(
            definition.Settings.MultipleInstances,
            TASK_INSTANCES_IGNORE_NEW,
        )
        self.assertEqual(definition.Settings.ExecutionTimeLimit, "PT0S")
        self.assertFalse(definition.Settings.Hidden)
        self.assertTrue(self.controller.start_if_installed())
        self.assertTrue(self.controller.inspect().running)
        self.assertTrue(self.controller.remove())
        self.assertFalse(self.controller.inspect().exists)

    def test_refuses_to_replace_or_remove_unmanaged_name_collision(self) -> None:
        definition = _definition()
        definition.RegistrationInfo.Description = "someone else's task"
        self.service.root.tasks[self.controller.task_name] = _Task(definition)

        with self.assertRaisesRegex(BrokerTaskError, "unmanaged"):
            self.controller.register(self.spec)
        with self.assertRaisesRegex(BrokerTaskError, "unmanaged"):
            self.controller.remove()

    def test_marker_substring_or_changed_action_never_claims_task_ownership(self) -> None:
        definition = _definition()
        definition.RegistrationInfo.Description = f"spoofed {MANAGED_TASK_MARKER} marker"
        self.service.root.tasks[self.controller.task_name] = _Task(definition)
        self.assertFalse(self.controller.inspect().managed)

        self.service.root.tasks.clear()
        self.controller.register(self.spec)
        task = self.service.root.tasks[self.controller.task_name]
        task.Definition.Actions.Item(1).Arguments = "changed action"

        self.assertFalse(self.controller.inspect().managed)
        with self.assertRaisesRegex(BrokerTaskError, "unmanaged"):
            self.controller.start_if_installed()
        with self.assertRaisesRegex(BrokerTaskError, "unmanaged"):
            self.controller.remove()

        task.Definition.Actions.Item(1).Arguments = self.spec.argument_line
        task.Definition.Principal.LogonType = None
        self.assertFalse(self.controller.inspect().managed)

    def test_manager_prefers_installed_task_for_default_runtime(self) -> None:
        task = Mock()
        task.start_if_installed.return_value = True
        with patch(
            "codex_serverops_mcp.broker.manager.BrokerTaskController.connect",
            return_value=task,
        ):
            manager = BrokerManager()
            manager._start_broker()

        task.start_if_installed.assert_called_once_with()
        self.assertIsNone(manager._launched_process)


if __name__ == "__main__":
    unittest.main()
