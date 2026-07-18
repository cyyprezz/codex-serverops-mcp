from __future__ import annotations

import unittest

from codex_serverops_mcp import BROKER_PROTOCOL_VERSION
from codex_serverops_mcp.ipc.errors import IpcMessageError, ProtocolVersionError
from codex_serverops_mcp.ipc.messages import Envelope, decode_envelope, encode_envelope
from codex_serverops_mcp.ipc.router import MessageRouter


class IpcMessageTests(unittest.TestCase):
    def test_envelope_round_trip_is_exact_and_versioned(self) -> None:
        original = Envelope.create("session.list", {"limit": 10})

        decoded = decode_envelope(encode_envelope(original))

        self.assertEqual(decoded.protocol_version, BROKER_PROTOCOL_VERSION)
        self.assertEqual(decoded.message_id, original.message_id)
        self.assertEqual(decoded.message_type, "session.list")
        self.assertEqual(dict(decoded.payload), {"limit": 10})

    def test_duplicate_json_fields_are_rejected(self) -> None:
        data = (
            b'{"protocol_version":1,"message_id":"msg_12345678",'
            b'"message_type":"ping","payload":{},"payload":{}}'
        )
        with self.assertRaisesRegex(IpcMessageError, "duplicate JSON field"):
            decode_envelope(data)

    def test_protocol_version_mismatch_fails_closed(self) -> None:
        data = (
            b'{"protocol_version":999,"message_id":"msg_12345678",'
            b'"message_type":"ping","payload":{}}'
        )
        with self.assertRaises(ProtocolVersionError):
            decode_envelope(data)

    def test_message_size_limit_is_enforced_before_transport(self) -> None:
        envelope = Envelope.create("large", {"value": "x" * 100})
        with self.assertRaisesRegex(IpcMessageError, "byte limit"):
            encode_envelope(envelope, max_bytes=32)

    def test_unknown_message_type_returns_a_controlled_error(self) -> None:
        router = MessageRouter()
        request = Envelope.create("not.registered")

        response = router.dispatch(request)

        self.assertEqual(response.message_id, request.message_id)
        self.assertEqual(response.message_type, "error")
        self.assertEqual(response.payload["code"], "unknown_message_type")

    def test_registered_handler_keeps_request_correlation_id(self) -> None:
        router = MessageRouter()
        router.register("ping", lambda payload: {"received": dict(payload)})
        request = Envelope.create("ping", {"value": 1})

        response = router.dispatch(request)

        self.assertEqual(response.message_id, request.message_id)
        self.assertEqual(response.message_type, "ping.result")
        self.assertEqual(response.payload["received"], {"value": 1})


if __name__ == "__main__":
    unittest.main()
