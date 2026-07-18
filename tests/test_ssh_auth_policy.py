from __future__ import annotations

import unittest

from codex_serverops_mcp.config import Authentication, ConnectionType, ServerProfile
from codex_serverops_mcp.ssh.auth_policy import (
    ConnectionPromptPolicy,
    PromptPolicyError,
    classify_askpass_prompt,
)
from codex_serverops_mcp.ssh.prompts import PromptEvent, PromptKind

HOST_KEY_NOTICE = (
    "The authenticity of host 'example.test (192.0.2.10)' can't be established.\n"
    "ED25519 key fingerprint is SHA256:0123456789abcdefghijklmnopqrstuv.\n"
    "Are you sure you want to continue connecting (yes/no/[fingerprint])?"
)


def direct_profile(authentication: Authentication) -> ServerProfile:
    return ServerProfile(
        display_name="Direct",
        connection_type=ConnectionType.DIRECT,
        authentication=authentication,
        host="192.0.2.10",
        port=22,
        user="deploy",
    )


class ConnectionPromptPolicyTests(unittest.TestCase):
    def test_askpass_classification_preserves_complete_host_key_notice(self) -> None:
        event = classify_askpass_prompt(HOST_KEY_NOTICE)

        self.assertEqual(event.kind, PromptKind.HOST_KEY)
        self.assertEqual(event.prompt, HOST_KEY_NOTICE)
        self.assertIn("ED25519", event.prompt)
        self.assertIn("SHA256:", event.prompt)

    def test_credential_classification_rejects_sudo_and_incomplete_host_key_text(self) -> None:
        self.assertEqual(
            classify_askpass_prompt("deploy@example.test's password:").kind,
            PromptKind.PASSWORD,
        )
        self.assertEqual(
            classify_askpass_prompt(
                r"Enter passphrase for key C:\Users\user\.ssh\id_ed25519:"
            ).kind,
            PromptKind.KEY_PASSPHRASE,
        )
        for text in (
            "[sudo] password for deploy:",
            "Are you sure you want to continue connecting (yes/no/[fingerprint])?",
        ):
            with self.subTest(text=text), self.assertRaises(PromptPolicyError):
                classify_askpass_prompt(text)

    def test_password_profile_never_authorizes_key_passphrase(self) -> None:
        policy = ConnectionPromptPolicy.from_profile(
            direct_profile(Authentication.INTERACTIVE_PASSWORD)
        )

        policy.authorize(PromptEvent(PromptKind.PASSWORD, "password:"))
        with self.assertRaises(PromptPolicyError):
            policy.authorize(PromptEvent(PromptKind.KEY_PASSPHRASE, "passphrase:"))

    def test_direct_openssh_profile_never_authorizes_account_password(self) -> None:
        policy = ConnectionPromptPolicy.from_profile(direct_profile(Authentication.OPENSSH))

        policy.authorize(PromptEvent(PromptKind.KEY_PASSPHRASE, "passphrase:"))
        with self.assertRaises(PromptPolicyError):
            policy.authorize(PromptEvent(PromptKind.PASSWORD, "password:"))

    def test_alias_follows_openssh_but_accepts_only_one_credential_answer(self) -> None:
        alias = ServerProfile(
            display_name="Alias",
            connection_type=ConnectionType.SSH_CONFIG,
            authentication=Authentication.OPENSSH,
            ssh_host="production",
        )
        password_policy = ConnectionPromptPolicy.from_profile(alias)
        key_policy = ConnectionPromptPolicy.from_profile(alias)
        password_policy.authorize(PromptEvent(PromptKind.PASSWORD, "password:"))
        key_policy.authorize(PromptEvent(PromptKind.KEY_PASSPHRASE, "passphrase:"))
        password_policy.record_answer(PromptKind.PASSWORD)

        for kind in (PromptKind.HOST_KEY, PromptKind.PASSWORD, PromptKind.KEY_PASSPHRASE):
            with self.subTest(kind=kind), self.assertRaises(PromptPolicyError):
                password_policy.authorize(PromptEvent(kind, "later prompt"))

    def test_host_key_decision_is_bounded_to_one_before_the_credential(self) -> None:
        policy = ConnectionPromptPolicy.from_profile(direct_profile(Authentication.OPENSSH))
        event = PromptEvent(PromptKind.HOST_KEY, HOST_KEY_NOTICE)
        policy.authorize(event)
        policy.record_answer(PromptKind.HOST_KEY)

        with self.assertRaises(PromptPolicyError):
            policy.authorize(event)


if __name__ == "__main__":
    unittest.main()

