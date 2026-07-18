from __future__ import annotations

import unittest
from unittest.mock import patch

from codex_serverops_mcp.config import Authentication
from codex_serverops_mcp.spike import product_probe
from codex_serverops_mcp.ssh.prompts import PromptKind


class FakeSession:
    def __init__(self) -> None:
        self.arguments: list[str] = []
        self.environment: dict[str, str] = {}
        self.failure_check = None

    def open(
        self,
        arguments,
        *,
        timeout: float,
        environment,
        failure_check,
    ) -> None:
        self.arguments = list(arguments)
        self.environment = dict(environment)
        self.failure_check = failure_check
        self.failure_check()


class FakeRelay:
    instances: list[FakeRelay] = []

    def __init__(self, target, policy, coordinator, *, timeout: float) -> None:
        self.target = target
        self.policy = policy
        self.coordinator = coordinator
        self.timeout = timeout
        self.environment = {
            "SSH_ASKPASS": "serverops-auth.exe",
            "SSH_ASKPASS_REQUIRE": "force",
            "SERVEROPS_ASKPASS_TOKEN": "fixture-capability",
        }
        self.started = False
        self.closed = False
        self.checks = 0
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def check(self) -> None:
        self.checks += 1

    def close(self) -> None:
        self.closed = True


class ProductProbeAskpassTests(unittest.TestCase):
    arguments = [
        "ssh.exe",
        "-tt",
        "-p",
        "2222",
        "-l",
        "serverops",
        "127.0.0.1",
        "bash",
        "--noprofile",
        "--norc",
        "-i",
    ]

    def setUp(self) -> None:
        FakeRelay.instances.clear()

    def test_product_probe_opens_connection_through_secret_free_askpass_relay(self) -> None:
        secret = "fixture-password-must-not-enter-environment"
        coordinator = product_probe.FixtureAuthenticationCoordinator(
            {PromptKind.PASSWORD: secret}
        )
        target = product_probe._target_from_arguments(self.arguments)
        profile = product_probe._profile_for_target(
            target,
            Authentication.INTERACTIVE_PASSWORD,
        )
        session = FakeSession()

        with patch.object(product_probe, "OpenSshAskpassRelay", FakeRelay):
            product_probe._open_with_askpass(
                session,
                self.arguments,
                profile,
                target,
                coordinator,
            )

        relay = FakeRelay.instances[0]
        self.assertTrue(relay.started)
        self.assertTrue(relay.closed)
        self.assertGreaterEqual(relay.checks, 2)
        self.assertEqual(session.environment["SSH_ASKPASS_REQUIRE"], "force")
        self.assertNotIn(secret, repr(session.environment))
        self.assertIs(session.failure_check.__self__, relay)
        self.assertEqual(target.host, "127.0.0.1")
        self.assertEqual(target.port, 2222)
        self.assertEqual(target.user, "serverops")


if __name__ == "__main__":
    unittest.main()
