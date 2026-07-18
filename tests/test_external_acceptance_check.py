from __future__ import annotations

import unittest

from codex_serverops_mcp.config import (
    Authentication,
    ConnectionType,
    ElevationMode,
    ServerProfile,
)
from scripts.external_acceptance_check import validate_acceptance_profile


def profile(*, environment: str = "test", roots: tuple[str, ...] = ("/opt/test",)):
    return ServerProfile(
        display_name="External acceptance",
        connection_type=ConnectionType.DIRECT,
        authentication=Authentication.INTERACTIVE_PASSWORD,
        host="192.0.2.1",
        port=22,
        user="deploy",
        allowed_roots=roots,
        allow_terminal=True,
        allow_file_read=True,
        allow_file_write=True,
        elevation_mode=ElevationMode.INTERACTIVE,
        allow_root_session=True,
        environment=environment,
    )


class ExternalAcceptanceCheckTests(unittest.TestCase):
    def test_disposable_profile_with_exact_root_is_accepted(self) -> None:
        validate_acceptance_profile(profile(), "/opt/test")

    def test_non_test_profile_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "marked as test"):
            validate_acceptance_profile(profile(environment="production"), "/opt/test")

    def test_extra_or_broad_roots_are_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "exactly"):
            validate_acceptance_profile(profile(roots=("/opt/test", "/var/log")), "/opt/test")
        with self.assertRaisesRegex(RuntimeError, "too broad"):
            validate_acceptance_profile(profile(roots=("/opt",)), "/opt")


if __name__ == "__main__":
    unittest.main()
