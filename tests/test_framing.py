from __future__ import annotations

import unittest

from codex_serverops_mcp.ssh.framing import (
    CommandFrameParser,
    command_wrapper,
    interrupt_recovery_wrapper,
)


class CommandFrameParserTests(unittest.TestCase):
    def test_markers_and_utf8_can_cross_every_chunk_boundary(self) -> None:
        token = "A1B2"
        payload = (
            b"noise\r\n__SERVEROPS_BEGIN_A1B2__\r\nGr\xc3\xbc\xc3\x9fe\r\n"
            b"__SERVEROPS_END_A1B2__:7\r\n__SERVEROPS_CWD_A1B2__:/opt/app\r\n"
        )
        for split in range(1, len(payload)):
            parser = CommandFrameParser(token)
            result = parser.feed(payload[:split])
            if result is None:
                result = parser.feed(payload[split:])
            self.assertIsNotNone(result, f"split={split}")
            assert result is not None
            self.assertEqual(result.output, "Gr\u00fc\u00dfe")
            self.assertEqual(result.exit_code, 7)
            self.assertEqual(result.cwd, "/opt/app")

    def test_ansi_sequences_are_ignored_around_markers(self) -> None:
        parser = CommandFrameParser("ABC")
        result = parser.feed(
            b"\x1b[32m__SERVEROPS_BEGIN_ABC__\x1b[0m\ntext\n"
            b"__SERVEROPS_END_ABC__:0\n__SERVEROPS_CWD_ABC__:/tmp\n"
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.output, "text")

    def test_nested_pty_carriage_returns_do_not_create_blank_lines(self) -> None:
        parser = CommandFrameParser("ABC")
        result = parser.feed(
            b"__SERVEROPS_BEGIN_ABC__\r\nroot\r\r\n"
            b"__SERVEROPS_END_ABC__:0\r\n__SERVEROPS_CWD_ABC__:/root\r\n"
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.output, "root")

    def test_wrapper_saves_exit_code_before_reporting_cwd(self) -> None:
        wrapper = command_wrapper("false", "ABC123")
        self.assertLess(wrapper.index("_serverops_exit=$?"), wrapper.index("$PWD"))
        self.assertIn('"$_serverops_exit"', wrapper)

    def test_wrapper_closes_a_multiline_command_without_a_leading_semicolon(self) -> None:
        wrapper = command_wrapper("(\nprintf ok\n)\n", "ABC123")

        self.assertIn("{\n(\nprintf ok\n)\n}; _serverops_exit=$?", wrapper)
        self.assertNotIn("\n; }", wrapper)

    def test_interrupt_recovery_reports_130_without_repeating_command(self) -> None:
        wrapper = interrupt_recovery_wrapper("ABC123")
        self.assertIn("__SERVEROPS_END_ABC123__:130", wrapper)
        self.assertIn("__SERVEROPS_CWD_ABC123__", wrapper)

    def test_large_output_is_bounded_and_marked_truncated(self) -> None:
        parser = CommandFrameParser("ABC", max_output_bytes=5)
        result = parser.feed(
            b"__SERVEROPS_BEGIN_ABC__\nabcdefghij\n"
            b"__SERVEROPS_END_ABC__:0\n__SERVEROPS_CWD_ABC__:/tmp\n"
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.output, "fghij")
        self.assertTrue(result.truncated)


if __name__ == "__main__":
    unittest.main()
