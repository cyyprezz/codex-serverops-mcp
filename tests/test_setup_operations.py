from __future__ import annotations

import json
import re
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from codex_serverops_mcp.broker.errors import BrokerOutcomeUnknown
from codex_serverops_mcp.config import (
    Authentication,
    ConnectionType,
    ServerProfile,
    TomlProfileRepository,
)
from codex_serverops_mcp.errors import ConfigurationError
from codex_serverops_mcp.security import AuditLogger, ProfileAudit
from codex_serverops_mcp.setup.keys import GeneratedKey
from codex_serverops_mcp.setup.operations import (
    ProfileSetupOperations,
    build_public_key_install_command,
)
from codex_serverops_mcp.setup.public_key_transition import (
    ROLLED_BACK_WARNING,
    PublicKeyInstallOutcomeUnknown,
    PublicKeyTransitionError,
)

PUBLIC_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHXdDb8Re7YltiXmQ3K7ZCbkGqYwRoyJSR+7JNn6sSoN "
    "serverops:test"
)


class FakeBrokerClient:
    def __init__(
        self,
        *,
        fail_key_login: bool = False,
        fail_first_open: bool = False,
        exec_outcome_unknown: bool = False,
        install_marker: str = "key_added",
        on_second_open: Callable[[], None] | None = None,
    ) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.open_count = 0
        self.fail_key_login = fail_key_login
        self.fail_first_open = fail_first_open
        self.exec_outcome_unknown = exec_outcome_unknown
        self.install_marker = install_marker
        self.on_second_open = on_second_open

    def request(self, message_type: str, payload: dict[str, object]) -> dict[str, object]:
        self.requests.append((message_type, payload))
        if message_type == "session.open":
            self.open_count += 1
            if self.open_count == 2 and self.on_second_open is not None:
                self.on_second_open()
            if self.fail_first_open and self.open_count == 1:
                raise RuntimeError("profile test failed")
            if self.fail_key_login and self.open_count == 2:
                raise RuntimeError("key login failed")
            return {
                "session_id": f"sess-{self.open_count:016x}",
                "effective_user": "deploy",
            }
        if message_type == "session.exec":
            if self.exec_outcome_unknown:
                raise BrokerOutcomeUnknown("outcome_unknown", "connection lost")
            command = str(payload["command"])
            marker = re.search(r"(__SERVEROPS_PUBLIC_KEY_[0-9a-f]{32}__:)", command)
            if marker is None:
                return {"status": "completed", "exit_code": 0, "output": ""}
            prefix = marker.group(1)
            if self.install_marker == "missing":
                output = "remote command returned no marker"
            elif self.install_marker == "ambiguous":
                output = f"{prefix}key_added\n{prefix}key_already_present"
            else:
                output = f"{prefix}{self.install_marker}"
            return {"status": "completed", "exit_code": 0, "output": output}
        if message_type == "session.close":
            return {"status": "closed"}
        raise AssertionError(message_type)

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        pass


class FakeBrokerProvider:
    def __init__(
        self,
        *,
        fail_key_login: bool = False,
        fail_first_open: bool = False,
        exec_outcome_unknown: bool = False,
        install_marker: str = "key_added",
        on_second_open: Callable[[], None] | None = None,
    ) -> None:
        self.client = FakeBrokerClient(
            fail_key_login=fail_key_login,
            fail_first_open=fail_first_open,
            exec_outcome_unknown=exec_outcome_unknown,
            install_marker=install_marker,
            on_second_open=on_second_open,
        )

    def connect(self) -> FakeBrokerClient:
        return self.client


class FakeKeyGenerator:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def generate(self, *_args: object, **_kwargs: object) -> GeneratedKey:
        if self.fail:
            raise RuntimeError("key generation failed")
        return GeneratedKey(Path("private-key"), Path("public-key"), PUBLIC_KEY)


class FailingAuditLogger:
    def record(self, **_parameters: object):
        raise OSError("audit unavailable")


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

    def audited_operations(
        self,
        broker: FakeBrokerProvider | None = None,
    ) -> tuple[ProfileSetupOperations, Path]:
        audit_root = Path(self.temporary.name) / "audit"
        operations = ProfileSetupOperations(
            self.repository,
            broker or FakeBrokerProvider(),
            ProfileAudit(AuditLogger(audit_root)),
        )
        return operations, audit_root

    @staticmethod
    def audit_events(audit_root: Path) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in next(audit_root.glob("*.jsonl")).read_text(encoding="utf-8").splitlines()
        ]

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

    def test_profile_mutations_and_test_emit_exact_audit_events(self) -> None:
        operations, audit_root = self.audited_operations()

        created = operations.add("prod", profile(Authentication.INTERACTIVE_PASSWORD))
        updated = operations.edit(
            "prod", profile(Authentication.OPENSSH, identity_file="C:/private/key")
        )
        tested = operations.test("prod")
        removed = operations.remove("prod")

        self.assertTrue(created["audit"]["logged"])
        self.assertTrue(updated["audit"]["logged"])
        self.assertTrue(tested["audit"]["logged"])
        self.assertTrue(removed["audit"]["logged"])
        self.assertEqual(
            [event["action"] for event in self.audit_events(audit_root)],
            [
                "profile_created",
                "profile_updated",
                "profile_test_started",
                "profile_test_completed",
                "profile_removed",
            ],
        )

    def test_failed_profile_test_is_audited_without_masking_error(self) -> None:
        operations, audit_root = self.audited_operations(
            FakeBrokerProvider(fail_first_open=True)
        )
        operations.add("prod", profile(Authentication.INTERACTIVE_PASSWORD))

        with self.assertRaisesRegex(RuntimeError, "profile test failed"):
            operations.test("prod")

        self.assertEqual(
            [event["action"] for event in self.audit_events(audit_root)][-2:],
            ["profile_test_started", "profile_test_failed"],
        )

    def test_audit_failure_does_not_change_successful_profile_mutation(self) -> None:
        operations = ProfileSetupOperations(
            self.repository,
            FakeBrokerProvider(),
            ProfileAudit(FailingAuditLogger()),  # type: ignore[arg-type]
        )

        result = operations.add("prod", profile(Authentication.INTERACTIVE_PASSWORD))

        self.assertEqual(result["profile"]["name"], "prod")
        self.assertEqual(result["audit"], {"logged": False})

    def test_install_adds_only_public_key_then_tests_fresh_key_login(self) -> None:
        broker = FakeBrokerProvider()
        operations, audit_root = self.audited_operations(broker)

        result = operations.install_public_key_and_switch(
            "prod",
            profile(Authentication.INTERACTIVE_PASSWORD),
            profile(Authentication.OPENSSH, identity_file="C:/Users/test/id_ed25519"),
            PUBLIC_KEY,
            replace_existing=False,
        )

        self.assertTrue(result["public_key_installed"])
        self.assertTrue(result["public_key_was_new"])
        self.assertTrue(result["audit"]["logged"])
        stored = self.repository.load().config.profiles["prod"]
        self.assertEqual(stored.authentication, Authentication.OPENSSH)
        self.assertEqual(broker.client.open_count, 2)
        install_request = next(
            payload
            for message_type, payload in broker.client.requests
            if message_type == "session.exec"
        )
        command = str(install_request["command"])
        self.assertIn("command awk -v alg=", command)
        self.assertNotIn(PUBLIC_KEY, command)
        self.assertNotIn("PRIVATE", command)
        self.assertEqual(
            [event["action"] for event in self.audit_events(audit_root)],
            [
                "public_key_install_started",
                "public_key_install_completed",
                "profile_test_started",
                "profile_test_completed",
                "profile_created",
            ],
        )

    def test_already_present_key_is_reported_without_false_new_claim(self) -> None:
        operations, _audit_root = self.audited_operations(
            FakeBrokerProvider(install_marker="key_already_present")
        )

        result = operations.install_public_key_and_switch(
            "prod",
            profile(Authentication.INTERACTIVE_PASSWORD),
            profile(Authentication.OPENSSH, identity_file="C:/private/key"),
            PUBLIC_KEY,
            replace_existing=False,
        )

        self.assertTrue(result["public_key_installed"])
        self.assertFalse(result["public_key_was_new"])

    def test_key_generation_start_completion_and_failure_are_audited(self) -> None:
        operations, audit_root = self.audited_operations()

        _generated, status = operations.generate_key(
            FakeKeyGenerator(),  # type: ignore[arg-type]
            "prod",
            object(),  # type: ignore[arg-type]
        )
        self.assertTrue(status.logged)
        with self.assertRaisesRegex(RuntimeError, "key generation failed"):
            operations.generate_key(
                FakeKeyGenerator(fail=True),  # type: ignore[arg-type]
                "failed",
                object(),  # type: ignore[arg-type]
            )

        events = self.audit_events(audit_root)
        self.assertEqual(
            [event["action"] for event in events],
            [
                "key_generation_started",
                "key_generation_completed",
                "key_generation_started",
                "key_generation_failed",
            ],
        )
        self.assertEqual([event["profile_name"] for event in events[:2]], ["prod", "prod"])

    def test_disconnect_after_key_write_is_outcome_unknown_and_audited(self) -> None:
        operations, audit_root = self.audited_operations(
            FakeBrokerProvider(exec_outcome_unknown=True)
        )

        with self.assertRaises(PublicKeyInstallOutcomeUnknown) as caught:
            operations.install_public_key_and_switch(
                "prod",
                profile(Authentication.INTERACTIVE_PASSWORD),
                profile(Authentication.OPENSSH, identity_file="C:/private/key"),
                PUBLIC_KEY,
                replace_existing=False,
            )

        events = self.audit_events(audit_root)
        self.assertEqual(
            [event["action"] for event in events],
            ["public_key_install_started", "public_key_install_outcome_unknown"],
        )
        self.assertEqual(events[-1]["result_status"], "outcome_unknown")
        self.assertTrue(caught.exception.local_profile_rolled_back)
        self.assertIsNone(caught.exception.public_key_installed)
        self.assertIsNone(caught.exception.public_key_was_new)
        self.assertNotIn("prod", self.repository.load().config.profiles)

    def test_failed_fresh_key_login_restores_original_local_configuration(self) -> None:
        broker = FakeBrokerProvider(fail_key_login=True)
        operations, audit_root = self.audited_operations(broker)

        with self.assertRaises(PublicKeyTransitionError) as caught:
            operations.install_public_key_and_switch(
                "prod",
                profile(Authentication.INTERACTIVE_PASSWORD),
                profile(Authentication.OPENSSH, identity_file="C:/Users/test/id_ed25519"),
                PUBLIC_KEY,
                replace_existing=False,
            )

        self.assertNotIn("prod", self.repository.load().config.profiles)
        self.assertEqual(str(caught.exception), ROLLED_BACK_WARNING)
        self.assertTrue(caught.exception.local_profile_rolled_back)
        self.assertTrue(caught.exception.public_key_installed)
        self.assertTrue(caught.exception.public_key_was_new)
        self.assertEqual(
            [event["action"] for event in self.audit_events(audit_root)],
            [
                "public_key_install_started",
                "public_key_install_completed",
                "profile_test_started",
                "profile_test_failed",
            ],
        )

    def test_concurrent_config_change_is_preserved_and_rollback_is_not_claimed(self) -> None:
        concurrent = profile(Authentication.OPENSSH, identity_file="C:/concurrent/key")

        def change_config() -> None:
            self.repository.put_profile("prod", concurrent)

        broker = FakeBrokerProvider(on_second_open=change_config)
        operations, _audit_root = self.audited_operations(broker)

        with self.assertRaises(PublicKeyTransitionError) as caught:
            operations.install_public_key_and_switch(
                "prod",
                profile(Authentication.INTERACTIVE_PASSWORD),
                profile(Authentication.OPENSSH, identity_file="C:/private/key"),
                PUBLIC_KEY,
                replace_existing=False,
            )

        error = caught.exception
        self.assertFalse(error.local_profile_rolled_back)
        self.assertEqual(error.local_profile_rollback_status, "skipped_concurrent_change")
        self.assertNotEqual(str(error), ROLLED_BACK_WARNING)
        self.assertEqual(
            self.repository.load().config.profiles["prod"].identity_file,
            "C:/concurrent/key",
        )
        install_commands = [
            payload["command"]
            for message_type, payload in broker.client.requests
            if message_type == "session.exec"
        ]
        self.assertEqual(len(install_commands), 1)
        self.assertNotIn("authorized_keys.tmp", str(install_commands[0]))

    def test_missing_or_ambiguous_remote_marker_is_outcome_unknown(self) -> None:
        for marker in ("missing", "ambiguous"):
            with self.subTest(marker=marker):
                repository = TomlProfileRepository(
                    Path(self.temporary.name) / f"{marker}.toml"
                )
                operations = ProfileSetupOperations(
                    repository,
                    FakeBrokerProvider(install_marker=marker),
                )
                with self.assertRaises(PublicKeyInstallOutcomeUnknown) as caught:
                    operations.install_public_key_and_switch(
                        "prod",
                        profile(Authentication.INTERACTIVE_PASSWORD),
                        profile(Authentication.OPENSSH, identity_file="C:/private/key"),
                        PUBLIC_KEY,
                        replace_existing=False,
                    )
                self.assertEqual(caught.exception.code, "outcome_unknown")
                self.assertNotIn("prod", repository.load().config.profiles)

    def test_public_key_command_rejects_multiline_input(self) -> None:
        with self.assertRaises(ValueError):
            build_public_key_install_command(f"{PUBLIC_KEY}\nmalicious")
        with self.assertRaises(ValueError):
            build_public_key_install_command(
                "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestServerOpsKey"
            )


if __name__ == "__main__":
    unittest.main()
