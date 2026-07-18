from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_serverops_mcp.config import Authentication
from codex_serverops_mcp.setup.draft import build_profile_draft, profile_confirmation_text


def values(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "profile_name": "prod",
        "display_name": "Production",
        "connection_type": "direct",
        "target": "192.0.2.70",
        "user": "deploy",
        "port": "22",
        "credential_mode": "password",
        "identity_file": "",
        "public_key_file": "",
        "install_public_key": False,
        "allowed_roots": "/opt/app\n/var/log/app",
        "allow_terminal": True,
        "allow_file_read": True,
        "allow_file_write": False,
        "elevation_mode": "interactive",
        "allow_root_session": False,
        "environment": "production",
        "command_timeout": "60",
        "max_output": "2097152",
    }
    result.update(overrides)
    return result


class SetupDraftTests(unittest.TestCase):
    def test_direct_password_draft_preserves_permissions_and_risk_summary(self) -> None:
        draft = build_profile_draft(**values())  # type: ignore[arg-type]

        self.assertEqual(draft.profile.authentication, Authentication.INTERACTIVE_PASSWORD)
        self.assertEqual(draft.profile.allowed_roots, ("/opt/app", "/var/log/app"))
        self.assertIn("keine Sandbox", profile_confirmation_text(draft))

    def test_new_key_install_builds_separate_password_staging_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "id_ed25519"
            draft = build_profile_draft(
                **values(
                    credential_mode="new_key",
                    identity_file=str(destination),
                    install_public_key=True,
                )  # type: ignore[arg-type]
            )

        self.assertEqual(draft.profile.authentication, Authentication.OPENSSH)
        self.assertEqual(
            draft.password_profile.authentication,  # type: ignore[union-attr]
            Authentication.INTERACTIVE_PASSWORD,
        )
        self.assertIsNone(draft.password_profile.identity_file)  # type: ignore[union-attr]

    def test_alias_rejects_password_mode_and_automatic_key_install(self) -> None:
        with self.assertRaises(ValueError):
            build_profile_draft(
                **values(
                    connection_type="ssh_config",
                    credential_mode="password",
                    target="corp-prod",
                )  # type: ignore[arg-type]
            )
        with tempfile.TemporaryDirectory() as temporary:
            key = Path(temporary) / "id"
            key.write_text("private fixture", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_profile_draft(
                    **values(
                        connection_type="ssh_config",
                        credential_mode="existing_key",
                        identity_file=str(key),
                        install_public_key=True,
                        target="corp-prod",
                    )  # type: ignore[arg-type]
                )


if __name__ == "__main__":
    unittest.main()
