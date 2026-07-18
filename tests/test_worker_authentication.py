from __future__ import annotations

import unittest

from codex_serverops_mcp.worker.authentication import SecretInputSink


class SecretInputSinkTests(unittest.TestCase):
    def test_response_is_written_once_and_mutable_buffer_is_zeroed(self) -> None:
        writes: list[bytes] = []
        response = bytearray(b"disposable-secret")
        sink = SecretInputSink(writes.append, newline=b"\r\n")

        sink.submit(response)

        self.assertEqual(writes, [b"disposable-secret\r\n"])
        self.assertEqual(response, bytearray(len(response)))
        self.assertTrue(sink.used)
        with self.assertRaisesRegex(RuntimeError, "already used"):
            sink.submit(bytearray(b"again"))

    def test_line_endings_are_rejected(self) -> None:
        sink = SecretInputSink(lambda _data: None, newline=b"\r\n")
        with self.assertRaisesRegex(ValueError, "line ending"):
            sink.submit(bytearray(b"unsafe\nvalue"))


if __name__ == "__main__":
    unittest.main()
