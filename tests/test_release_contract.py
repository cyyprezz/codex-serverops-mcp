from __future__ import annotations

import unittest

from scripts.verify_distribution import EXPECTED_COMMANDS
from scripts.verify_release import ReleaseContractError, verify_release


class ReleaseContractTests(unittest.TestCase):
    def test_development_tree_satisfies_pre_release_contract(self) -> None:
        self.assertEqual(verify_release(), "0.0.0.dev1")

    def test_stable_tag_cannot_be_claimed_from_development_version(self) -> None:
        with self.assertRaisesRegex(ReleaseContractError, "stable package version"):
            verify_release(tag="v0.1.0")

    def test_distribution_exposes_only_six_product_commands(self) -> None:
        self.assertEqual(
            EXPECTED_COMMANDS,
            {
                "codex-serverops-mcp",
                "serverops-install",
                "serverops-setup",
                "serverops-auth",
                "serverops-broker",
                "serverops-session-worker",
            },
        )


if __name__ == "__main__":
    unittest.main()
