from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
CAPABILITIES = json.loads((ROOT / "docs" / "capabilities.json").read_text(encoding="utf-8"))
EXPECTED_TOOLS = {
    "server_profile_setup",
    "server_profiles",
    "server_connection",
    "server_exec",
    "server_terminal",
    "server_files",
    "server_file_edit",
    "server_elevation",
}


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


class ProductClaimTests(unittest.TestCase):
    def test_capability_contract_matches_versions_marketplaces_and_tool_surface(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        registry = _load_json(ROOT / "server.json")
        codex_marketplace = _load_json(ROOT / ".agents" / "plugins" / "marketplace.json")
        claude_marketplace = _load_json(ROOT / ".claude-plugin" / "marketplace.json")

        self.assertEqual(CAPABILITIES["product"], "ServerOps")
        self.assertEqual(CAPABILITIES["package"], project["name"])
        self.assertEqual(CAPABILITIES["published_version"], project["version"])
        self.assertEqual(CAPABILITIES["published_version"], registry["version"])
        self.assertEqual(CAPABILITIES["marketplaces"]["codex"], codex_marketplace["name"])
        self.assertEqual(CAPABILITIES["marketplaces"]["claude"], claude_marketplace["name"])
        self.assertEqual(set(CAPABILITIES["tools"]), EXPECTED_TOOLS)
        self.assertEqual(len(CAPABILITIES["tools"]), 8)

    def test_each_claim_has_a_unique_status_and_readme_marker(self) -> None:
        all_ids: list[str] = []
        for status in ("available", "candidate", "planned"):
            for entry in CAPABILITIES[status]:
                capability_id = entry["id"]
                all_ids.append(capability_id)
                marker_status = "capability" if status == "available" else status
                self.assertIn(f"<!-- {marker_status}:{capability_id} -->", README)
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_available_and_candidate_evidence_paths_exist(self) -> None:
        for status in ("available", "candidate"):
            for entry in CAPABILITIES[status]:
                self.assertTrue(entry["evidence"], entry["id"])
                for relative in entry["evidence"]:
                    self.assertTrue((ROOT / relative).exists(), f"missing evidence: {relative}")

    def test_required_product_sections_are_present(self) -> None:
        required = (
            "# ServerOps",
            "## Three promises",
            "## See it in action",
            "## Available today",
            "## Codex quickstart",
            "## Claude Code quickstart",
            "## Automatic local bootstrap",
            "## Optional installer and broker task",
            "## Typical workflows",
            "## One-off SSH command or ServerOps?",
            "## Architecture",
            "## Requirements and honest limits",
            "## Capability status",
            "## Roadmap",
            "## Documentation and project",
        )
        for heading in required:
            self.assertIn(heading, README)
        self.assertIn("```mermaid", README)

    def test_public_quickstarts_use_exact_release_and_need_no_setup_prerequisite(self) -> None:
        version = CAPABILITIES["published_version"]
        codex_quickstart = README.split("## Codex quickstart", 1)[1].split(
            "## Claude Code quickstart", 1
        )[0]
        claude_quickstart = README.split("## Claude Code quickstart", 1)[1].split(
            "## Automatic local bootstrap", 1
        )[0]
        self.assertNotIn("serverops-install setup", codex_quickstart)
        self.assertNotIn("serverops-install setup", claude_quickstart)
        for command in (
            "codex plugin marketplace add cyyprezz/codex-serverops-mcp",
            "codex plugin add codex-serverops-mcp@serverops-codex",
            "claude plugin marketplace add cyyprezz/codex-serverops-mcp",
            "claude plugin install serverops@serverops-claude",
        ):
            self.assertIn(command, README)
        self.assertIn(f"pinned `{version}` MCP", README)
        self.assertIn(f"same pinned `{version}` runtime", README)
        self.assertIn(f"Version `{version}` starts without a separate setup command", README)

    def test_available_section_does_not_claim_planned_runtime_features(self) -> None:
        available = README.split("## Available today", 1)[1].split("\n## ", 1)[0].lower()
        for forbidden in (
            "serveropssetup.exe",
            "persistent job",
            "eventlog",
            "log engine",
            "binary transfer",
            "incident system",
            "fleet rollout",
            "transactional change",
            "backup assurance",
            "native database",
        ):
            self.assertNotIn(forbidden, available)

    def test_readme_has_no_fabricated_social_or_performance_proof(self) -> None:
        for forbidden in (
            "trusted by",
            "customer logo",
            "testimonial",
            "downloads per month",
            "faster than ssh",
        ):
            self.assertNotIn(forbidden, README.lower())

    def test_relative_readme_links_resolve(self) -> None:
        links = re.findall(r"(?<!!)\[[^]]+\]\(([^)]+)\)", README)
        checked = 0
        for target in links:
            if target.startswith(("http://", "https://", "#")):
                continue
            path_text = unquote(target.split("#", 1)[0])
            self.assertTrue((ROOT / path_text).exists(), f"broken README link: {target}")
            checked += 1
        self.assertGreaterEqual(checked, 15)

    def test_badges_are_real_project_or_package_endpoints(self) -> None:
        badge_lines = [line for line in README.splitlines() if line.startswith("[![")]
        self.assertEqual(len(badge_lines), 4)
        self.assertTrue(any("actions/workflows/ci.yml/badge.svg" in line for line in badge_lines))
        self.assertTrue(any("pypi/v/codex-serverops-mcp" in line for line in badge_lines))
        self.assertTrue(any("pypi/pyversions/codex-serverops-mcp" in line for line in badge_lines))
        self.assertTrue(
            any("github/license/cyyprezz/codex-serverops-mcp" in line for line in badge_lines)
        )


if __name__ == "__main__":
    unittest.main()
