from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "codex-serverops-mcp"


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


class PluginDistributionTests(unittest.TestCase):
    def test_marketplace_points_at_matching_plugin(self) -> None:
        marketplace = load_json(ROOT / ".agents" / "plugins" / "marketplace.json")
        self.assertEqual(marketplace["name"], "serverops-codex")
        self.assertEqual(marketplace["interface"], {"displayName": "ServerOps Codex"})

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
        self.assertEqual(entry["category"], "Developer Tools")

    def test_plugin_mcp_pin_matches_public_release(self) -> None:
        registry = load_json(ROOT / "server.json")
        manifest = load_json(PLUGIN_ROOT / ".codex-plugin" / "plugin.json")
        mcp_config = load_json(PLUGIN_ROOT / ".mcp.json")
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

        self.assertEqual(manifest["name"], PLUGIN_ROOT.name)
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertRegex(str(manifest["version"]), r"^\d+\.\d+\.\d+$")
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
            "separate local ServerOps windows",
        ):
            self.assertIn(required, skill)

    def test_public_docs_explain_plugin_install_without_duplicate_mcp_config(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        installation = (ROOT / "docs" / "installation.md").read_text(encoding="utf-8")

        for document in (readme, installation):
            self.assertIn("codex plugin marketplace add cyyprezz/codex-serverops-mcp", document)
            self.assertIn("codex plugin add codex-serverops-mcp@serverops-codex", document)
            self.assertIn("codex-config --remove", document)
        self.assertNotIn("The package is not published as `0.1.0` yet", readme)
        self.assertNotIn("untagged `0.1.0` candidate", installation)


if __name__ == "__main__":
    unittest.main()
