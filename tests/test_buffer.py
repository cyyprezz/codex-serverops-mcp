from __future__ import annotations

import unittest

from codex_serverops_mcp.terminal.buffer import TerminalRingBuffer


class TerminalRingBufferTests(unittest.TestCase):
    def test_absolute_cursor_reports_dropped_output(self) -> None:
        buffer = TerminalRingBuffer(5)
        buffer.append(b"abc")
        buffer.append(b"def")

        result = buffer.read(0)

        self.assertEqual(result.data, b"bcdef")
        self.assertEqual(result.next_cursor, 6)
        self.assertTrue(result.dropped_before_cursor)

    def test_current_cursor_returns_only_new_output(self) -> None:
        buffer = TerminalRingBuffer(10)
        buffer.append(b"abc")
        cursor = buffer.end_cursor
        buffer.append(b"def")

        result = buffer.read(cursor)

        self.assertEqual(result.data, b"def")
        self.assertFalse(result.dropped_before_cursor)


if __name__ == "__main__":
    unittest.main()

