from __future__ import annotations

import time
import unittest

from codex_serverops_mcp.auth.errors import AuthenticationProtocolError
from codex_serverops_mcp.auth.model import AuthPrompt, AuthTargetContext
from codex_serverops_mcp.auth.wire import (
    AuthResponseKind,
    decision_response_frame,
    decode_auth_response,
    secret_response_frame,
)
from codex_serverops_mcp.ssh.prompts import PromptEvent, PromptKind


class AuthModelAndWireTests(unittest.TestCase):
    def test_non_secret_prompt_context_round_trips_exactly(self) -> None:
        target = AuthTargetContext("prod", "Production", "example.test", 22, "deploy")
        prompt = AuthPrompt.from_event(
            "auth_0123456789abcdef0123456789abcdef",
            target,
            PromptEvent(PromptKind.SUDO_PASSWORD, "[sudo] password for deploy:"),
            expires_at=time.time() + 60,
        )

        self.assertEqual(AuthPrompt.from_payload(prompt.to_payload()), prompt)
        self.assertNotIn("response", prompt.to_payload())

        incompatible = prompt.to_payload()
        incompatible["worker_protocol_version"] = 999
        with self.assertRaisesRegex(ValueError, "protocol version"):
            AuthPrompt.from_payload(incompatible)

    def test_secret_wire_response_is_bounded_and_clearable(self) -> None:
        source = bytearray(b"disposable-test-value")
        frame = secret_response_frame(source)
        response = decode_auth_response(bytes(frame))

        self.assertEqual(response.kind, AuthResponseKind.SECRET)
        self.assertEqual(response.secret, source)
        response.clear()
        self.assertEqual(response.secret, bytearray(len(source)))

    def test_decisions_reject_payloads_and_unknown_types(self) -> None:
        self.assertEqual(
            decode_auth_response(decision_response_frame(AuthResponseKind.CANCEL)).kind,
            AuthResponseKind.CANCEL,
        )
        with self.assertRaises(AuthenticationProtocolError):
            decode_auth_response(b"\xff")
        with self.assertRaises(AuthenticationProtocolError):
            decode_auth_response(bytes((AuthResponseKind.CONFIRM, 1)))
        with self.assertRaises(AuthenticationProtocolError):
            secret_response_frame(bytearray(b"unsafe\nvalue"))
        with self.assertRaisesRegex(ValueError, "host"):
            AuthTargetContext("prod", "Production", "spoofed\nhost", 22, "deploy")


if __name__ == "__main__":
    unittest.main()
