from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "codex-serverops-mcp"
CLAUDE_PLUGIN_ROOT = ROOT / "plugins" / "claude-serverops-mcp"
PUBLIC_VERSION = "0.1.1"
TOOLS = {
    "server_profile_setup",
    "server_profiles",
    "server_connection",
    "server_exec",
    "server_terminal",
    "server_files",
    "server_file_edit",
    "server_elevation",
}


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


class PluginDistributionTests(unittest.TestCase):
    def test_marketplace_points_at_matching_plugin(self) -> None:
        marketplace = load_json(ROOT / ".agents" / "plugins" / "marketplace.json")
        self.assertEqual(marketplace["name"], "serverops-codex")
        self.assertEqual(marketplace["interface"], {"displayName": "ServerOps"})

        entries = marketplace["plugins"]
        self.assertIsInstance(entries, list)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["name"], PLUGIN_ROOT.name)
        self.assertEqual(
            entry["source"],
            {"source": "local", "path": "./plugins/codex-serverops-mcp"},
        )
        self.assertEqual(
            entry["policy"],
            {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        )
        self.assertEqual(entry["category"], "Productivity")

    def test_plugin_mcp_pin_matches_public_release(self) -> None:
        registry = load_json(ROOT / "server.json")
        manifest = load_json(PLUGIN_ROOT / ".codex-plugin" / "plugin.json")
        mcp_config = load_json(PLUGIN_ROOT / ".mcp.json")
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

        self.assertEqual(manifest["name"], PLUGIN_ROOT.name)
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertEqual(manifest["version"], project["version"])
        self.assertEqual(registry["version"], project["version"])

        server = mcp_config["mcpServers"]["serverops"]
        self.assertEqual(server["command"], "uvx")
        self.assertEqual(
            server["args"],
            [
                "--from",
                f"codex-serverops-mcp=={registry['version']}",
                "codex-serverops-mcp",
            ],
        )
        self.assertEqual(server["startup_timeout_sec"], 60)
        self.assertEqual(server["tool_timeout_sec"], 3730)
        self.assertNotIn("cwd", server)
        self.assertNotIn("env", server)

    def test_claude_marketplace_manifest_and_exact_public_pin(self) -> None:
        marketplace = load_json(ROOT / ".claude-plugin" / "marketplace.json")
        self.assertEqual(marketplace["name"], "serverops-claude")
        self.assertNotIn("displayName", marketplace)
        self.assertEqual(len(marketplace["plugins"]), 1)
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], "serverops")
        self.assertEqual(entry["source"], "./plugins/claude-serverops-mcp")
        self.assertEqual(entry["version"], PUBLIC_VERSION)
        self.assertTrue(entry["strict"])

        manifest = load_json(CLAUDE_PLUGIN_ROOT / ".claude-plugin" / "plugin.json")
        self.assertEqual(manifest["name"], "serverops")
        self.assertEqual(manifest["displayName"], "ServerOps")
        self.assertEqual(manifest["version"], PUBLIC_VERSION)
        self.assertNotIn("mcpServers", manifest)
        self.assertNotIn("skills", manifest)

        mcp = load_json(CLAUDE_PLUGIN_ROOT / ".mcp.json")["mcpServers"]["serverops"]
        self.assertEqual(set(mcp), {"type", "command", "args", "timeout"})
        self.assertEqual(mcp["type"], "stdio")
        self.assertEqual(mcp["command"], "uvx")
        self.assertEqual(
            mcp["args"],
            ["--from", f"codex-serverops-mcp=={PUBLIC_VERSION}", "codex-serverops-mcp"],
        )
        self.assertEqual(mcp["timeout"], 3_730_000)

    def test_codex_and_claude_skills_are_client_neutral_and_identical(self) -> None:
        for name in ("serverops-control", "serverops-diagnose"):
            codex = (PLUGIN_ROOT / "skills" / name / "SKILL.md").read_bytes()
            claude = (CLAUDE_PLUGIN_ROOT / "skills" / name / "SKILL.md").read_bytes()
            self.assertEqual(codex, claude)
            text = codex.decode("utf-8")
            self.assertNotIn("allowed-tools:", text)
            self.assertNotIn("Codex", text)
            self.assertNotIn("Claude", text)
            mentioned = set(re.findall(r"`(server_[a-z_]+)`", text))
            self.assertLessEqual(mentioned, TOOLS)

    def test_bundled_skill_preserves_security_contract(self) -> None:
        skill = (PLUGIN_ROOT / "skills" / "serverops-control" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("[TODO:", skill)
        self.assertRegex(
            skill,
            re.compile(r"^---\s+name: serverops-control\s+description:", re.S),
        )
        for required in (
            "server_profile_setup",
            "server_connection",
            "server_file_edit",
            "outcome_unknown",
            "Never retry automatically",
            "local ServerOps windows",
        ):
            self.assertIn(required, skill)

        diagnose = (PLUGIN_ROOT / "skills" / "serverops-diagnose" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        for required in ("read-only", "hypotheses", "outcome_unknown", "raw-text floods"):
            self.assertIn(required, diagnose)

    def test_public_docs_explain_plugin_install_without_duplicate_mcp_config(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        installation = (ROOT / "docs" / "installation.md").read_text(encoding="utf-8")

        for document in (readme, installation):
            self.assertIn("codex plugin marketplace add cyyprezz/codex-serverops-mcp", document)
            self.assertIn("codex plugin add codex-serverops-mcp@serverops-codex", document)
            self.assertIn("claude plugin marketplace add cyyprezz/codex-serverops-mcp", document)
            self.assertIn("claude plugin install serverops@serverops-claude", document)
            self.assertIn("codex-config --remove", document)
        self.assertNotIn("The package is not published as `0.1.0` yet", readme)
        self.assertNotIn("untagged `0.1.0` candidate", installation)


if __name__ == "__main__":
    unittest.main()
