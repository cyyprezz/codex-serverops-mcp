from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from codex_serverops_mcp.config import TomlProfileRepository
from codex_serverops_mcp.installer.paths import InstallPaths
from codex_serverops_mcp.installer.setup import prepare_local_install, remove_local_data


@unittest.skipUnless(os.name == "nt", "installer ACL contract is Windows-only")
class InstallerSetupTests(unittest.TestCase):
    def test_prepare_creates_valid_current_user_local_state(self) -> None:
        from codex_serverops_mcp.ipc.security import inspect_path_security

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = InstallPaths(
                root / "codex-serverops-mcp",
                root / "codex-serverops-mcp" / "config.toml",
                root / "codex-serverops-mcp" / "runtime",
                root / "codex-serverops-mcp" / "audit",
                root / ".codex" / "config.toml",
            )
            result = prepare_local_install(paths)
            snapshot = TomlProfileRepository(paths.config_file).load()
            self.assertEqual(result["status"], "prepared")
            self.assertEqual(len(snapshot.config.profiles), 0)
            for path in (paths.app_dir, paths.config_file, paths.runtime_dir, paths.audit_dir):
                self.assertTrue(path.exists())
                self.assertTrue(inspect_path_security(str(path)).current_user_only)

            remove_local_data(paths)
            self.assertFalse(paths.app_dir.exists())


if __name__ == "__main__":
    unittest.main()
