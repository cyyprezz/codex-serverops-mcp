from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from scripts.verify_distribution import EXPECTED_COMMANDS
from scripts.verify_release import (
    REQUIRED_EVIDENCE_ENVIRONMENT,
    REQUIRED_EXTERNAL_SCENARIOS,
    REQUIRED_MANUAL_CHECKS,
    ReleaseContractError,
    _verify_evidence,
    verify_release,
)


def _evidence_document() -> dict[str, object]:
    return {
        "schema_version": 2,
        "package_version": "0.1.1",
        "source_revision": "a" * 40,
        "completed_at": "2026-07-18T12:00:00Z",
        "environment": dict.fromkeys(REQUIRED_EVIDENCE_ENVIRONMENT, "fixture-version"),
        "checks": dict.fromkeys(REQUIRED_MANUAL_CHECKS, True),
        "external_scenarios": dict.fromkeys(REQUIRED_EXTERNAL_SCENARIOS, "automated"),
    }


class ReleaseContractTests(unittest.TestCase):
    def test_untagged_candidate_satisfies_pre_release_contract(self) -> None:
        self.assertEqual(verify_release(), "0.1.1")

    def test_stable_tag_cannot_be_claimed_without_committed_evidence(self) -> None:
        with self.assertRaisesRegex(ReleaseContractError, "committed manual release evidence"):
            verify_release(tag="v0.1.1")

    def test_stable_tag_has_no_automated_only_evidence_bypass(self) -> None:
        with patch("scripts.verify_release._verify_evidence") as evidence:
            self.assertEqual(verify_release(tag="v0.1.1"), "0.1.1")
        evidence.assert_called_once()

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
                json.dumps(_evidence_document()),
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
                _verify_evidence(Path(temporary), evidence, "0.1.1")

    def test_manual_evidence_allows_only_its_own_follow_up_commit(self) -> None:
        with TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "release-evidence.json"
            evidence.write_text(
                json.dumps(_evidence_document()),
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
                _verify_evidence(Path(temporary), evidence, "0.1.1")

    def test_manual_evidence_rejects_multiple_evidence_only_follow_ups(self) -> None:
        with TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "release-evidence.json"
            evidence.write_text(
                json.dumps(_evidence_document()),
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
                _verify_evidence(Path(temporary), evidence, "0.1.1")

    def test_manual_evidence_requires_complete_environment_metadata(self) -> None:
        with TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "release-evidence.json"
            document = _evidence_document()
            environment = dict(document["environment"])
            del environment["sudo_version"]
            document["environment"] = environment
            evidence.write_text(json.dumps(document), encoding="utf-8")

            with self.assertRaisesRegex(ReleaseContractError, "environment metadata"):
                _verify_evidence(Path(temporary), evidence, "0.1.1")

    def test_manual_evidence_rejects_unverified_external_scenario(self) -> None:
        with TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "release-evidence.json"
            document = _evidence_document()
            scenarios = dict(document["external_scenarios"])
            scenarios["timeout_recovery"] = "not_tested"
            document["external_scenarios"] = scenarios
            evidence.write_text(json.dumps(document), encoding="utf-8")

            with self.assertRaisesRegex(ReleaseContractError, "unverified external"):
                _verify_evidence(Path(temporary), evidence, "0.1.1")


if __name__ == "__main__":
    unittest.main()
