from __future__ import annotations

import os
import threading
import unittest
from typing import Protocol

from codex_serverops_mcp.auth.errors import (
    AuthenticationProtocolError,
    AuthenticationReplayError,
    AuthenticationTimedOut,
)
from codex_serverops_mcp.auth.model import AuthTargetContext
from codex_serverops_mcp.auth.wire import AuthResponse, AuthResponseKind
from codex_serverops_mcp.ssh.prompts import PromptEvent, PromptKind


class CollectableChallenge(Protocol):
    def collect(self) -> AuthResponse: ...


@unittest.skipUnless(os.name == "nt", "direct authentication uses Windows named pipes")
class AuthChallengeTests(unittest.TestCase):
    @staticmethod
    def _server(*, timeout: float = 2):
        from codex_serverops_mcp.auth.server import AuthChallengeServer

        return AuthChallengeServer(
            AuthTargetContext("prod", "Production", "example.test", 22, "deploy"),
            PromptEvent(PromptKind.PASSWORD, "deploy@example.test's password:"),
            timeout=timeout,
        )

    def test_secret_uses_one_direct_connection_and_client_buffer_is_zeroed(self) -> None:
        from codex_serverops_mcp.auth.client import DirectAuthClient

        server = self._server()
        self.assertTrue(server.listener.security_report.current_user_only)
        response, errors, thread = self._collect_in_thread(server)
        descriptor = server.descriptor
        secret = bytearray(b"disposable-test-value")
        with DirectAuthClient(
            descriptor.pipe,
            descriptor.request_id,
            descriptor.token,
        ) as client:
            prompt = client.open()
            self.assertEqual(prompt.target.profile_name, "prod")
            self.assertEqual(client.submit_secret(secret), "submitted")
        thread.join(timeout=3)

        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(secret, bytearray(len(secret)))
        collected = response[0]
        self.assertEqual(collected.kind, AuthResponseKind.SECRET)
        self.assertEqual(collected.secret, bytearray(b"disposable-test-value"))
        collected.clear()
        with self.assertRaises(AuthenticationReplayError):
            server.collect()
        with self.assertRaises(AuthenticationProtocolError):
            DirectAuthClient(
                descriptor.pipe,
                descriptor.request_id,
                descriptor.token,
                timeout=0.1,
            ).open()

    def test_invalid_token_is_rejected_without_consuming_the_request(self) -> None:
        from codex_serverops_mcp.auth.client import DirectAuthClient

        server = self._server()
        response, errors, thread = self._collect_in_thread(server)
        descriptor = server.descriptor
        with self.assertRaises(AuthenticationProtocolError):
            DirectAuthClient(
                descriptor.pipe,
                descriptor.request_id,
                "wrong-token-value-that-is-long-enough",
            ).open()

        with DirectAuthClient(
            descriptor.pipe,
            descriptor.request_id,
            descriptor.token,
        ) as client:
            client.open()
            client.cancel()
        thread.join(timeout=3)

        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(response[0].kind, AuthResponseKind.CANCEL)

    def test_unanswered_request_expires_and_closes_its_listener(self) -> None:
        from codex_serverops_mcp.auth.client import DirectAuthClient

        server = self._server(timeout=0.15)
        descriptor = server.descriptor

        with self.assertRaises(AuthenticationTimedOut):
            server.collect()
        with self.assertRaises(AuthenticationProtocolError):
            DirectAuthClient(
                descriptor.pipe,
                descriptor.request_id,
                descriptor.token,
                timeout=0.1,
            ).open()

    def test_connected_but_unresponsive_client_cannot_extend_the_deadline(self) -> None:
        from codex_serverops_mcp.auth.client import DirectAuthClient

        server = self._server(timeout=0.2)
        response, errors, thread = self._collect_in_thread(server)
        descriptor = server.descriptor
        client = DirectAuthClient(
            descriptor.pipe,
            descriptor.request_id,
            descriptor.token,
        )
        client.open()
        thread.join(timeout=3)
        client.close()

        self.assertFalse(thread.is_alive())
        self.assertEqual(response, [])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], AuthenticationTimedOut)

    @staticmethod
    def _collect_in_thread(server: CollectableChallenge):
        responses: list[AuthResponse] = []
        errors: list[BaseException] = []

        def collect() -> None:
            try:
                responses.append(server.collect())
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=collect)
        thread.start()
        return responses, errors, thread


if __name__ == "__main__":
    unittest.main()
