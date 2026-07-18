from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_serverops_mcp.config import (
    Authentication,
    ConnectionType,
    ServerProfile,
    TomlProfileRepository,
)
from codex_serverops_mcp.errors import ConfigurationError
from codex_serverops_mcp.setup.operations import (
    ProfileSetupOperations,
    build_public_key_install_command,
)

PUBLIC_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHXdDb8Re7YltiXmQ3K7ZCbkGqYwRoyJSR+7JNn6sSoN "
    "serverops:test"
)


class FakeBrokerClient:
    def __init__(self, *, fail_key_login: bool = False) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.open_count = 0
        self.fail_key_login = fail_key_login

    def request(self, message_type: str, payload: dict[str, object]) -> dict[str, object]:
        self.requests.append((message_type, payload))
        if message_type == "session.open":
            self.open_count += 1
            if self.fail_key_login and self.open_count == 2:
                raise RuntimeError("key login failed")
            return {
                "session_id": f"sess-{self.open_count:016x}",
                "effective_user": "deploy",
            }
        if message_type == "session.exec":
            return {"status": "completed", "exit_code": 0}
        if message_type == "session.close":
            return {"status": "closed"}
        raise AssertionError(message_type)

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        pass


class FakeBrokerProvider:
    def __init__(self, *, fail_key_login: bool = False) -> None:
        self.client = FakeBrokerClient(fail_key_login=fail_key_login)

    def connect(self) -> FakeBrokerClient:
        return self.client


def profile(authentication: Authentication, *, identity_file: str | None = None) -> ServerProfile:
    return ServerProfile(
        display_name="Production",
        connection_type=ConnectionType.DIRECT,
        authentication=authentication,
        host="192.0.2.60",
        port=22,
        user="deploy",
        identity_file=identity_file,
        allowed_roots=("/opt/app",),
        allow_file_read=True,
        environment="production",
    )


class SetupOperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = TomlProfileRepository(Path(self.temporary.name) / "config.toml")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_add_edit_remove_and_test_have_explicit_profile_semantics(self) -> None:
        broker = FakeBrokerProvider()
        operations = ProfileSetupOperations(self.repository, broker)

        operations.add("prod", profile(Authentication.INTERACTIVE_PASSWORD))
        with self.assertRaises(ConfigurationError):
            operations.add("prod", profile(Authentication.INTERACTIVE_PASSWORD))
        edited = operations.edit("prod", profile(Authentication.OPENSSH, identity_file="key"))
        tested = operations.test("prod")
        removed = operations.remove("prod")

        self.assertEqual(edited["profile"]["authentication"], "openssh")
        self.assertEqual(tested["connection"], "ready")
        self.assertEqual(removed["profile_name"], "prod")
        self.assertNotIn("prod", self.repository.load().config.profiles)

    def test_install_adds_only_public_key_then_tests_fresh_key_login(self) -> None:
        broker = FakeBrokerProvider()
        operations = ProfileSetupOperations(self.repository, broker)

        result = operations.install_public_key_and_switch(
            "prod",
            profile(Authentication.INTERACTIVE_PASSWORD),
            profile(Authentication.OPENSSH, identity_file="C:/Users/test/id_ed25519"),
            PUBLIC_KEY,
            replace_existing=False,
        )

        self.assertTrue(result["public_key_installed"])
        stored = self.repository.load().config.profiles["prod"]
        self.assertEqual(stored.authentication, Authentication.OPENSSH)
        self.assertEqual(broker.client.open_count, 2)
        install_request = next(
            payload
            for message_type, payload in broker.client.requests
            if message_type == "session.exec"
        )
        command = str(install_request["command"])
        self.assertIn("grep -qxF", command)
        self.assertNotIn(PUBLIC_KEY, command)
        self.assertNotIn("PRIVATE", command)

    def test_failed_fresh_key_login_restores_original_local_configuration(self) -> None:
        broker = FakeBrokerProvider(fail_key_login=True)
        operations = ProfileSetupOperations(self.repository, broker)

        with self.assertRaises(RuntimeError):
            operations.install_public_key_and_switch(
                "prod",
                profile(Authentication.INTERACTIVE_PASSWORD),
                profile(Authentication.OPENSSH, identity_file="C:/Users/test/id_ed25519"),
                PUBLIC_KEY,
                replace_existing=False,
            )

        self.assertNotIn("prod", self.repository.load().config.profiles)

    def test_public_key_command_rejects_multiline_input(self) -> None:
        with self.assertRaises(ValueError):
            build_public_key_install_command(f"{PUBLIC_KEY}\nmalicious")
        with self.assertRaises(ValueError):
            build_public_key_install_command(
                "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestServerOpsKey"
            )


if __name__ == "__main__":
    unittest.main()
