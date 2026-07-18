from __future__ import annotations

import os
import subprocess
import threading
import time
import unittest

from codex_serverops_mcp.auth.errors import (
    AuthenticationCancelled,
    AuthenticationProtocolError,
    AuthenticationTimedOut,
)
from codex_serverops_mcp.auth.model import AuthTargetContext
from codex_serverops_mcp.config import Authentication, ConnectionType, ServerProfile
from codex_serverops_mcp.ssh.auth_policy import ConnectionPromptPolicy
from codex_serverops_mcp.ssh.prompts import PromptEvent, PromptKind

if __package__:
    from .test_ssh_auth_policy import HOST_KEY_NOTICE, direct_profile
else:
    from test_ssh_auth_policy import HOST_KEY_NOTICE, direct_profile


class FixedCoordinator:
    def __init__(self, response: bytes = b"fixture-password", failure=None) -> None:
        self.response = response
        self.failure = failure
        self.events: list[PromptEvent] = []

    def respond(self, event, sink) -> None:
        self.events.append(event)
        if self.failure is not None:
            raise self.failure
        sink.submit(bytearray(self.response))

    def cancel_active(self) -> None:
        return


class BlockingCoordinator:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.cancelled = threading.Event()

    def respond(self, event, sink) -> None:
        del event, sink
        self.entered.set()
        if not self.cancelled.wait(10):
            raise AuthenticationTimedOut("blocking coordinator was not cancelled")
        raise AuthenticationCancelled("authentication was cancelled with the relay")

    def cancel_active(self) -> None:
        self.cancelled.set()


def alias_profile() -> ServerProfile:
    return ServerProfile(
        display_name="Alias",
        connection_type=ConnectionType.SSH_CONFIG,
        authentication=Authentication.OPENSSH,
        ssh_host="production",
    )


@unittest.skipUnless(os.name == "nt", "Askpass relay uses Windows named pipes")
class AskpassRelayTests(unittest.TestCase):
    target = AuthTargetContext("prod", "Production", "example.test", 22, "deploy")

    def _relay(self, profile, coordinator):
        from codex_serverops_mcp.worker.askpass import OpenSshAskpassRelay

        return OpenSshAskpassRelay(
            self.target,
            ConnectionPromptPolicy.from_profile(profile),
            coordinator,
            timeout=10,
        )

    @staticmethod
    def _invoke(relay, prompt: str) -> subprocess.CompletedProcess[bytes]:
        environment = dict(os.environ)
        environment.update(relay.environment)
        return subprocess.run(
            [relay.environment["SSH_ASKPASS"], prompt],
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=10,
            check=False,
        )

    @staticmethod
    def _wait_for_failure(relay, expected) -> None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                relay.check()
            except expected:
                return
            time.sleep(0.01)
        relay.check()
        raise AssertionError("Askpass relay did not publish its failure")

    def test_existing_entry_point_returns_only_the_authorized_password(self) -> None:
        coordinator = FixedCoordinator()
        relay = self._relay(direct_profile(Authentication.INTERACTIVE_PASSWORD), coordinator)
        relay.start()
        try:
            completed = self._invoke(relay, "deploy@example.test's password:")

            self.assertEqual(completed.returncode, 0)
            self.assertEqual(completed.stdout.strip(), b"fixture-password")
            self.assertEqual([event.kind for event in coordinator.events], [PromptKind.PASSWORD])
            relay.check()
            self.assertTrue(relay.security_report.current_user_only)
            self.assertNotIn("fixture-password", repr(relay.environment))
        finally:
            relay.close()

    def test_full_host_key_notice_reaches_the_visible_auth_coordinator(self) -> None:
        coordinator = FixedCoordinator(response=b"yes")
        relay = self._relay(direct_profile(Authentication.OPENSSH), coordinator)
        relay.start()
        try:
            completed = self._invoke(relay, HOST_KEY_NOTICE)

            self.assertEqual(completed.returncode, 0)
            self.assertEqual(completed.stdout.strip(), b"yes")
            self.assertEqual(coordinator.events[0].prompt, HOST_KEY_NOTICE)
        finally:
            relay.close()

    def test_profile_mismatches_fail_before_opening_visible_auth(self) -> None:
        cases = (
            (
                direct_profile(Authentication.INTERACTIVE_PASSWORD),
                r"Enter passphrase for key C:\Users\user\.ssh\id_ed25519:",
            ),
            (direct_profile(Authentication.OPENSSH), "deploy@example.test's password:"),
        )
        for profile, prompt in cases:
            with self.subTest(prompt=prompt):
                coordinator = FixedCoordinator()
                relay = self._relay(profile, coordinator)
                relay.start()
                try:
                    completed = self._invoke(relay, prompt)
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertEqual(completed.stdout, b"")
                    self.assertEqual(coordinator.events, [])
                    self._wait_for_failure(relay, AuthenticationProtocolError)
                finally:
                    relay.close()

    def test_second_credential_and_post_auth_host_key_are_rejected(self) -> None:
        coordinator = FixedCoordinator()
        relay = self._relay(alias_profile(), coordinator)
        relay.start()
        try:
            first = self._invoke(
                relay,
                r"Enter passphrase for key C:\Users\user\.ssh\id_ed25519:",
            )
            second = self._invoke(relay, "deploy@example.test's password:")

            self.assertEqual(first.returncode, 0)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(
                [event.kind for event in coordinator.events],
                [PromptKind.KEY_PASSPHRASE],
            )
            self._wait_for_failure(relay, AuthenticationProtocolError)
        finally:
            relay.close()

    def test_cancel_and_timeout_are_returned_without_secret_output(self) -> None:
        cases = (
            AuthenticationCancelled("cancelled by operator"),
            AuthenticationTimedOut("local window timed out"),
        )
        for failure in cases:
            with self.subTest(failure=type(failure).__name__):
                coordinator = FixedCoordinator(failure=failure)
                relay = self._relay(
                    direct_profile(Authentication.INTERACTIVE_PASSWORD), coordinator
                )
                relay.start()
                try:
                    completed = self._invoke(relay, "deploy@example.test's password:")
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertEqual(completed.stdout, b"")
                    self._wait_for_failure(relay, type(failure))
                finally:
                    relay.close()

    def test_close_cancels_an_active_prompt_and_joins_the_relay_thread(self) -> None:
        coordinator = BlockingCoordinator()
        relay = self._relay(
            direct_profile(Authentication.INTERACTIVE_PASSWORD), coordinator
        )
        relay.start()
        environment = dict(os.environ)
        environment.update(relay.environment)
        helper = subprocess.Popen(
            [relay.environment["SSH_ASKPASS"], "deploy@example.test's password:"],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertTrue(coordinator.entered.wait(5))

        relay.close()
        _stdout, _stderr = helper.communicate(timeout=5)

        self.assertTrue(coordinator.cancelled.is_set())
        self.assertIsNotNone(relay._thread)
        assert relay._thread is not None
        self.assertFalse(relay._thread.is_alive())
        self.assertEqual(relay.token, "")
        self.assertNotEqual(helper.returncode, 0)


if __name__ == "__main__":
    unittest.main()
