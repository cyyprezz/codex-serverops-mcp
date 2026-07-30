from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPIKE = ROOT / "spike" / "windows-packaging"


class WindowsPackagingSpikeTests(unittest.TestCase):
    def test_spike_is_pinned_onedir_and_contains_all_process_roles(self) -> None:
        self.assertEqual(
            (SPIKE / "requirements.lock").read_text(encoding="utf-8"),
            "pyinstaller==6.21.0\n",
        )
        spec = (SPIKE / "serverops.spec").read_text(encoding="utf-8")
        for role in (
            "serverops-mcp",
            "serverops-broker",
            "serverops-session-worker",
            "serverops-install",
            "serverops-setup",
            "serverops-auth",
        ):
            self.assertIn(f'("{role}"', spec)
        self.assertIn('name="ServerOps"', spec)
        self.assertNotIn("onefile", spec.casefold())
        self.assertIn("upx=False", spec)

    def test_spike_is_not_wired_into_release_workflows(self) -> None:
        workflows = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / ".github" / "workflows").glob("*.yml")
        )
        self.assertNotIn("windows-packaging", workflows)
        decision = (
            ROOT / "docs" / "adr" / "017-windows-versioned-multiprocess-package.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Choose option 3", decision)
        self.assertIn("Inno Setup", decision)


if __name__ == "__main__":
    unittest.main()
