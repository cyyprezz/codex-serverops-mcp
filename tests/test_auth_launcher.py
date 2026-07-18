from __future__ import annotations

import os
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.name == "nt", "visible auth launcher is Windows-only")
class AuthLauncherTests(unittest.TestCase):
    def test_one_use_token_is_inherited_but_never_put_on_command_line(self) -> None:
        from codex_serverops_mcp.auth.launcher import (
            AUTH_TOKEN_ENVIRONMENT,
            VisibleAuthProcessLauncher,
        )
        from codex_serverops_mcp.auth.server import AuthLaunchDescriptor

        descriptor = AuthLaunchDescriptor(
            request_id="auth_0123456789abcdef0123456789abcdef",
            pipe=r"\\.\pipe\codex-serverops-auth-test-current-user",
            token="one-use-connection-token-value",
            expires_at=123.0,
        )
        with patch("codex_serverops_mcp.auth.launcher.subprocess.Popen") as popen:
            VisibleAuthProcessLauncher().launch(descriptor)

        command = popen.call_args.args[0]
        environment = popen.call_args.kwargs["env"]
        self.assertNotIn(descriptor.token, command)
        self.assertEqual(environment[AUTH_TOKEN_ENVIRONMENT], descriptor.token)
        self.assertIn(descriptor.pipe, command)
        self.assertIn(descriptor.request_id, command)
        self.assertNotIn("example.test", command)
        self.assertNotIn("deploy", command)

    def test_auth_program_fails_closed_without_inherited_token(self) -> None:
        from codex_serverops_mcp.auth.app import run_auth_app
        from codex_serverops_mcp.auth.launcher import AUTH_TOKEN_ENVIRONMENT

        with patch.dict(os.environ, {}, clear=True):
            self.assertNotIn(AUTH_TOKEN_ENVIRONMENT, os.environ)
            self.assertEqual(run_auth_app("unused", "unused"), 3)


if __name__ == "__main__":
    unittest.main()
