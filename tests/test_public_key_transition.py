from __future__ import annotations

import unittest

from codex_serverops_mcp.setup.public_key_transition import (
    ROLLED_BACK_WARNING,
    LocalRollbackStatus,
    PublicKeyInstallOutcomeUnknown,
    PublicKeyTransitionError,
    build_public_key_install_plan,
)

KEY_BLOB = "AAAAC3NzaC1lZDI1NTE5AAAAIHXdDb8Re7YltiXmQ3K7ZCbkGqYwRoyJSR+7JNn6sSoN"
TOKEN = "1" * 32


class PublicKeyTransitionTests(unittest.TestCase):
    def test_parser_distinguishes_added_and_already_present(self) -> None:
        plan = build_public_key_install_plan(
            f"ssh-ed25519 {KEY_BLOB} first-comment",
            token=TOKEN,
        )

        added = plan.parse(f"{plan.marker_prefix}key_added\n")
        present = plan.parse(f"notice\n{plan.marker_prefix}key_already_present\n")

        self.assertTrue(added.was_new)
        self.assertFalse(present.was_new)

    def test_missing_or_ambiguous_marker_is_outcome_unknown(self) -> None:
        plan = build_public_key_install_plan(f"ssh-ed25519 {KEY_BLOB}", token=TOKEN)

        for output in (
            "",
            f"{plan.marker_prefix}unknown",
            f"{plan.marker_prefix}key_added\n{plan.marker_prefix}key_already_present",
        ):
            with self.subTest(output=output), self.assertRaises(PublicKeyInstallOutcomeUnknown):
                plan.parse(output)

    def test_identity_ignores_comment_and_command_handles_missing_final_newline(self) -> None:
        first = build_public_key_install_plan(
            f"ssh-ed25519 {KEY_BLOB} first-comment",
            token=TOKEN,
        )
        second = build_public_key_install_plan(
            f"ssh-ed25519 {KEY_BLOB} another comment",
            token="2" * 32,
        )

        self.assertEqual(first.key_identity, second.key_identity)
        self.assertIn("for (i = 1; i < NF; i++)", first.command)
        self.assertIn('command tail -c 1 "$HOME/.ssh/authorized_keys"', first.command)
        self.assertIn("builtin printf '\\n' >>", first.command)
        self.assertIn("key_already_present", first.command)
        self.assertIn("key_added", first.command)

    def test_rolled_back_transition_uses_exact_operator_warning(self) -> None:
        error = PublicKeyTransitionError(
            LocalRollbackStatus.ROLLED_BACK,
            public_key_installed=True,
            public_key_was_new=True,
        )

        self.assertEqual(str(error), ROLLED_BACK_WARNING)
        self.assertTrue(error.local_profile_rolled_back)
        self.assertEqual(error.local_profile_rollback_status, "rolled_back")
        self.assertTrue(error.public_key_installed)
        self.assertTrue(error.public_key_was_new)


if __name__ == "__main__":
    unittest.main()
