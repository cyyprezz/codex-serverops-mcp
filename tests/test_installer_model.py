from __future__ import annotations

import unittest
from pathlib import Path

from codex_serverops_mcp.installer.model import CheckReport, failed, passed, warning
from codex_serverops_mcp.installer.paths import InstallPaths


class InstallerModelTests(unittest.TestCase):
    def test_report_status_is_fail_closed_then_warning_then_ready(self) -> None:
        self.assertEqual(CheckReport((passed("ok", "ok"),)).status, "ready")
        self.assertEqual(CheckReport((warning("risk", "risk"),)).status, "ready_with_warnings")
        self.assertEqual(CheckReport((failed("bad", "bad"),)).status, "failed")

    def test_paths_respect_codex_home_without_checkout_paths(self) -> None:
        paths = InstallPaths.from_environment(
            {
                "LOCALAPPDATA": "C:/Users/example/AppData/Local",
                "USERPROFILE": "C:/Users/example",
                "CODEX_HOME": "D:/CodexHome",
            }
        )
        self.assertEqual(
            paths.config_file,
            Path("C:/Users/example/AppData/Local/codex-serverops-mcp/config.toml"),
        )
        self.assertEqual(paths.codex_config_file, Path("D:/CodexHome/config.toml"))


if __name__ == "__main__":
    unittest.main()
