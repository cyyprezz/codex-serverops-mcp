from __future__ import annotations

import unittest

from codex_serverops_mcp.config import (
    Authentication,
    ConnectionType,
    ElevationMode,
    ServerOpsConfig,
    ServerProfile,
    decode_config,
    encode_config,
)
from codex_serverops_mcp.errors import ConfigurationError, ConfigVersionError


class ConfigModelTests(unittest.TestCase):
    def test_direct_and_ssh_alias_profiles_round_trip(self) -> None:
        direct = ServerProfile(
            display_name="Kunde Produktion",
            connection_type=ConnectionType.DIRECT,
            authentication=Authentication.INTERACTIVE_PASSWORD,
            host="192.168.1.50",
            port=22,
            user="deploy",
            allowed_roots=("/opt/app",),
            allow_file_read=True,
            allow_file_write=True,
            elevation_mode=ElevationMode.INTERACTIVE,
            environment="production",
        )
        alias = ServerProfile(
            display_name="Beispiel Produktion",
            connection_type=ConnectionType.SSH_CONFIG,
            authentication=Authentication.OPENSSH,
            ssh_host="example-prod",
            allowed_roots=("/opt/example-app",),
            allow_file_read=True,
            elevation_mode=ElevationMode.INTERACTIVE,
            environment="production",
        )
        original = ServerOpsConfig(profiles={"kunde-prod": direct, "example-prod": alias})

        decoded, migrated = decode_config(encode_config(original))

        self.assertFalse(migrated)
        self.assertEqual(decoded, original)

    def test_legacy_draft_migrates_sudo_mode_to_elevation_mode(self) -> None:
        legacy = """
[profiles.demo]
display_name = "Demo"
connection_type = "direct"
authentication = "interactive_password"
host = "127.0.0.1"
port = 22
user = "deploy"
sudo_mode = "interactive"
"""

        config, migrated = decode_config(legacy)

        self.assertTrue(migrated)
        self.assertEqual(config.profiles["demo"].elevation_mode, ElevationMode.INTERACTIVE)
        self.assertIn("schema_version = 1", encode_config(config))
        self.assertNotIn("sudo_mode", encode_config(config))

    def test_forbidden_secret_fields_are_rejected(self) -> None:
        text = """
schema_version = 1
[profiles.demo]
display_name = "Demo"
connection_type = "direct"
authentication = "interactive_password"
host = "127.0.0.1"
port = 22
user = "deploy"
password = "must-not-be-stored"
"""

        with self.assertRaisesRegex(ConfigurationError, "forbidden secret fields"):
            decode_config(text)

    def test_future_schema_fails_closed(self) -> None:
        with self.assertRaises(ConfigVersionError):
            decode_config("schema_version = 999\n")

    def test_direct_and_alias_fields_cannot_be_mixed(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "cannot define ssh_host"):
            ServerProfile(
                display_name="Invalid",
                connection_type=ConnectionType.DIRECT,
                authentication=Authentication.INTERACTIVE_PASSWORD,
                ssh_host="alias",
                host="127.0.0.1",
                port=22,
                user="deploy",
            )

    def test_structured_file_access_requires_normalized_roots(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "absolute normalized"):
            ServerProfile(
                display_name="Invalid",
                connection_type=ConnectionType.DIRECT,
                authentication=Authentication.INTERACTIVE_PASSWORD,
                host="127.0.0.1",
                port=22,
                user="deploy",
                allowed_roots=("../etc",),
                allow_file_read=True,
            )
        with self.assertRaisesRegex(ConfigurationError, "only text paths"):
            ServerProfile(
                display_name="Invalid",
                connection_type=ConnectionType.DIRECT,
                authentication=Authentication.INTERACTIVE_PASSWORD,
                host="127.0.0.1",
                port=22,
                user="deploy",
                allowed_roots=("/opt/app\n/secret",),
                allow_file_read=True,
            )

    def test_file_write_requires_file_read(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "requires allow_file_read"):
            ServerProfile(
                display_name="Invalid",
                connection_type=ConnectionType.DIRECT,
                authentication=Authentication.INTERACTIVE_PASSWORD,
                host="127.0.0.1",
                port=22,
                user="deploy",
                allowed_roots=("/opt/app",),
                allow_file_write=True,
            )

    def test_root_session_requires_terminal_and_elevation(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "enabled elevation mode"):
            ServerProfile(
                display_name="Invalid",
                connection_type=ConnectionType.DIRECT,
                authentication=Authentication.OPENSSH,
                host="127.0.0.1",
                port=22,
                user="deploy",
                allow_root_session=True,
            )
        with self.assertRaisesRegex(ConfigurationError, "terminal access"):
            ServerProfile(
                display_name="Invalid",
                connection_type=ConnectionType.DIRECT,
                authentication=Authentication.OPENSSH,
                host="127.0.0.1",
                port=22,
                user="deploy",
                elevation_mode=ElevationMode.NON_INTERACTIVE,
                allow_root_session=True,
                allow_terminal=False,
            )

    def test_programmatic_callers_must_use_validated_enum_values(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "connection_type"):
            ServerProfile(
                display_name="Invalid",
                connection_type="direct",  # type: ignore[arg-type]
                authentication=Authentication.INTERACTIVE_PASSWORD,
                host="127.0.0.1",
                port=22,
                user="deploy",
            )


if __name__ == "__main__":
    unittest.main()
