from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from scripts.verify_distribution import EXPECTED_COMMANDS
from scripts.verify_release import (
    REQUIRED_MANUAL_CHECKS,
    ReleaseContractError,
    _verify_evidence,
    verify_release,
)


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

    def test_manual_evidence_rejects_any_non_evidence_follow_up(self) -> None:
        with TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "release-evidence.json"
            evidence.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "package_version": "0.1.0",
                        "source_revision": "a" * 40,
                        "completed_at": "2026-07-18T12:00:00Z",
                        "checks": dict.fromkeys(REQUIRED_MANUAL_CHECKS, True),
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch(
                    "scripts.verify_release.subprocess.run",
                    side_effect=(
                        SimpleNamespace(stdout="b" * 40),
                        SimpleNamespace(returncode=0),
                        SimpleNamespace(stdout="1\n"),
                        SimpleNamespace(stdout="README.md\n"),
                    ),
                ),
                self.assertRaisesRegex(ReleaseContractError, "evidence-only commit"),
            ):
                _verify_evidence(Path(temporary), evidence, "0.1.0")

    def test_manual_evidence_allows_only_its_own_follow_up_commit(self) -> None:
        with TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "release-evidence.json"
            evidence.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "package_version": "0.1.0",
                        "source_revision": "a" * 40,
                        "completed_at": "2026-07-18T12:00:00Z",
                        "checks": dict.fromkeys(REQUIRED_MANUAL_CHECKS, True),
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "scripts.verify_release.subprocess.run",
                side_effect=(
                    SimpleNamespace(stdout="b" * 40),
                    SimpleNamespace(returncode=0),
                    SimpleNamespace(stdout="1\n"),
                    SimpleNamespace(stdout="docs/release-evidence.json\n"),
                ),
            ):
                _verify_evidence(Path(temporary), evidence, "0.1.0")

    def test_manual_evidence_rejects_multiple_evidence_only_follow_ups(self) -> None:
        with TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "release-evidence.json"
            evidence.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "package_version": "0.1.0",
                        "source_revision": "a" * 40,
                        "completed_at": "2026-07-18T12:00:00Z",
                        "checks": dict.fromkeys(REQUIRED_MANUAL_CHECKS, True),
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch(
                    "scripts.verify_release.subprocess.run",
                    side_effect=(
                        SimpleNamespace(stdout="b" * 40),
                        SimpleNamespace(returncode=0),
                        SimpleNamespace(stdout="2\n"),
                    ),
                ),
                self.assertRaisesRegex(ReleaseContractError, "exactly one"),
            ):
                _verify_evidence(Path(temporary), evidence, "0.1.0")


if __name__ == "__main__":
    unittest.main()
