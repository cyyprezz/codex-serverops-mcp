from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_serverops_mcp.application import ApplicationServices
from codex_serverops_mcp.config import (
    Authentication,
    ConnectionType,
    ServerOpsConfig,
    ServerProfile,
    TomlProfileRepository,
)
from codex_serverops_mcp.security import AuditLogger


class FakeBrokerClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object] | None]] = []

    def request(
        self,
        message_type: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.requests.append((message_type, payload))
        return {"message_type": message_type, **(payload or {})}

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        pass


class FakeBrokerProvider:
    def __init__(self) -> None:
        self.client = FakeBrokerClient()

    def connect(self) -> FakeBrokerClient:
        return self.client


class FakeSetupCoordinator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def start(self, action: str, **parameters: object) -> dict[str, object]:
        self.calls.append(("start", (action,), parameters))
        return {"status": "user_interaction_required", "request_id": "setup-request"}

    def status(self, request_id: str) -> dict[str, object]:
        self.calls.append(("status", (request_id,), {}))
        return {"status": "running", "request_id": request_id}

    def wait(self, request_id: str, timeout: float) -> dict[str, object]:
        self.calls.append(("wait", (request_id, timeout), {}))
        return {"status": "created", "request_id": request_id}


class ApplicationServicesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        repository = TomlProfileRepository(Path(self.temporary.name) / "config.toml")
        repository.save(
            ServerOpsConfig(
                profiles={
                    "prod": ServerProfile(
                        display_name="Production",
                        connection_type=ConnectionType.DIRECT,
                        authentication=Authentication.OPENSSH,
                        host="192.0.2.30",
                        port=22,
                        user="deploy",
                        environment="production",
                    )
                }
            )
        )
        self.broker = FakeBrokerProvider()
        self.setup = FakeSetupCoordinator()
        self.services = ApplicationServices(repository, self.broker, self.setup)  # type: ignore[arg-type]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_profiles_expose_non_secret_summary_and_details(self) -> None:
        listed = self.services.server_profiles("list")
        inspected = self.services.server_profiles("inspect", "prod")

        self.assertEqual(listed["profiles"][0]["name"], "prod")
        self.assertEqual(inspected["profile"]["user"], "deploy")
        self.assertNotIn("password", repr((listed, inspected)).lower())

    def test_connection_actions_map_to_versioned_broker_operations(self) -> None:
        session_id = "sess-0123456789abcdef"

        self.services.server_connection("open", profile_name="prod")
        self.services.server_connection("list")
        self.services.server_connection("status", session_id=session_id)
        reconnected = self.services.server_connection("reconnect", session_id=session_id)
        self.services.server_connection("close", session_id=session_id)

        self.assertEqual(
            [request[0] for request in self.broker.client.requests],
            [
                "session.open",
                "session.list",
                "session.status",
                "session.reconnect",
                "session.close",
            ],
        )
        self.assertEqual(reconnected["message_type"], "session.reconnect")

    def test_setup_actions_start_or_poll_only_the_local_coordinator(self) -> None:
        started = self.services.server_profile_setup(
            "add",
            suggested_host="192.0.2.44",
            suggested_user="deploy",
        )
        waited = self.services.server_profile_setup(
            "wait",
            request_id="setup-request",
            wait_timeout=2,
        )

        self.assertEqual(started["status"], "user_interaction_required")
        self.assertEqual(waited["status"], "created")
        self.assertEqual(self.setup.calls[0][0], "start")
        self.assertEqual(self.setup.calls[1], ("wait", ("setup-request", 2), {}))

    def test_setup_polling_rejects_profile_suggestions(self) -> None:
        with self.assertRaises(ValueError):
            self.services.server_profile_setup(
                "status",
                request_id="setup-request",
                suggested_host="host",
            )
        self.assertEqual(self.setup.calls, [])

    def test_exec_and_terminal_pass_no_implicit_retry_instruction(self) -> None:
        session_id = "sess-0123456789abcdef"

        self.services.server_exec(session_id, "printf ok", timeout=5)
        self.services.server_terminal("read", session_id, cursor=0, timeout=1)

        exec_type, exec_payload = self.broker.client.requests[0]
        self.assertEqual(exec_type, "session.exec")
        self.assertNotIn("retry", exec_payload)
        self.assertEqual(
            self.broker.client.requests[1],
            (
                "session.terminal",
                {"session_id": session_id, "action": "read", "cursor": 0, "timeout": 1},
            ),
        )

    def test_structured_file_calls_keep_read_and_write_protocols_separate(self) -> None:
        session_id = "sess-0123456789abcdef"

        self.services.server_files(
            "read_text",
            session_id,
            path="/opt/app/a.txt",
            byte_limit=100,
        )
        self.services.server_file_edit(
            "write_text",
            session_id,
            path="/opt/app/a.txt",
            content="updated",
            expected_sha256="0" * 64,
        )

        self.assertEqual(
            self.broker.client.requests[-2],
            (
                "session.files",
                {
                    "session_id": session_id,
                    "action": "read_text",
                    "path": "/opt/app/a.txt",
                    "byte_limit": 100,
                },
            ),
        )
        self.assertEqual(self.broker.client.requests[-1][0], "session.file_edit")

    def test_elevation_actions_use_one_exact_broker_contract(self) -> None:
        session_id = "sess-0123456789abcdef"

        self.services.server_elevation("acquire", session_id)
        self.services.server_elevation("exec", session_id, command="id -u", timeout=5)
        self.services.server_elevation("open_root_session", session_id)

        self.assertEqual(
            self.broker.client.requests,
            [
                ("session.elevation", {"session_id": session_id, "action": "acquire"}),
                (
                    "session.elevation",
                    {
                        "session_id": session_id,
                        "action": "exec",
                        "command": "id -u",
                        "timeout": 5.0,
                    },
                ),
                (
                    "session.elevation",
                    {"session_id": session_id, "action": "open_root_session"},
                ),
            ],
        )

        with self.assertRaises(ValueError):
            self.services.server_elevation("status", session_id, command="unexpected")

    def test_invalid_action_parameter_combinations_fail_before_broker(self) -> None:
        with self.assertRaises(ValueError):
            self.services.server_connection("list", profile_name="prod")
        with self.assertRaises(ValueError):
            self.services.server_exec("bad-session", "pwd")
        self.assertEqual(self.broker.client.requests, [])

    def test_operational_call_writes_redacted_audit_and_marks_response(self) -> None:
        audit_root = Path(self.temporary.name) / "audit"
        self.services.audit = AuditLogger(audit_root)
        command = "curl -H 'Authorization: Bearer abcdefghijklmnop' example.test"

        result = self.services.server_exec("sess-0123456789abcdef", command)

        self.assertTrue(result["audit"]["logged"])
        self.assertTrue(result["audit"]["command_redacted"])
        event = json.loads(next(audit_root.glob("*.jsonl")).read_text(encoding="utf-8"))
        self.assertEqual(event["tool"], "server_exec")
        self.assertEqual(event["action"], "exec")
        self.assertNotIn("abcdefghijklmnop", repr(event))


if __name__ == "__main__":
    unittest.main()
