from __future__ import annotations

import unittest

from codex_serverops_mcp.ssh.framing import (
    CommandFrameParser,
    FrameProtocolError,
    command_wrapper,
    interrupt_recovery_wrapper,
    shell_bootstrap_wrapper,
)

SHELL_NONCE = "D4E5F6"


class CommandFrameParserTests(unittest.TestCase):
    def test_markers_and_utf8_can_cross_every_chunk_boundary(self) -> None:
        token = "A1B2"
        payload = (
            b"noise\r\n__SERVEROPS_BEGIN_A1B2__\r\nGr\xc3\xbc\xc3\x9fe\r\n"
            b"__SERVEROPS_DEBUG_A1B2__\r\n__SERVEROPS_DEBUG_END_A1B2__\r\n"
            b"__SERVEROPS_END_A1B2__:7\r\n__SERVEROPS_CWD_A1B2__:/opt/app\r\n"
            b"__SERVEROPS_HEALTH_A1B2__:D4E5F6\r\n"
        )
        for split in range(1, len(payload)):
            parser = CommandFrameParser(token, shell_nonce=SHELL_NONCE)
            result = parser.feed(payload[:split])
            if result is None:
                result = parser.feed(payload[split:])
            self.assertIsNotNone(result, f"split={split}")
            assert result is not None
            self.assertEqual(result.output, "Gr\u00fc\u00dfe")
            self.assertEqual(result.exit_code, 7)
            self.assertEqual(result.cwd, "/opt/app")

    def test_ansi_sequences_are_ignored_around_markers(self) -> None:
        parser = CommandFrameParser("ABC", shell_nonce=SHELL_NONCE)
        result = parser.feed(
            b"\x1b[32m__SERVEROPS_BEGIN_ABC__\x1b[0m\ntext\n"
            b"__SERVEROPS_DEBUG_ABC__\n__SERVEROPS_DEBUG_END_ABC__\n"
            b"__SERVEROPS_END_ABC__:0\n__SERVEROPS_CWD_ABC__:/tmp\n"
            b"__SERVEROPS_HEALTH_ABC__:D4E5F6\n"
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.output, "text")

    def test_nested_pty_carriage_returns_do_not_create_blank_lines(self) -> None:
        parser = CommandFrameParser("ABC", shell_nonce=SHELL_NONCE)
        result = parser.feed(
            b"__SERVEROPS_BEGIN_ABC__\r\nroot\r\r\n"
            b"__SERVEROPS_DEBUG_ABC__\r\n__SERVEROPS_DEBUG_END_ABC__\r\n"
            b"__SERVEROPS_END_ABC__:0\r\n__SERVEROPS_CWD_ABC__:/root\r\n"
            b"__SERVEROPS_HEALTH_ABC__:D4E5F6\r\n"
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.output, "root")

    def test_wrapper_saves_exit_code_before_reporting_cwd(self) -> None:
        wrapper = command_wrapper("false", "ABC123", shell_nonce=SHELL_NONCE)
        self.assertLess(wrapper.index("_serverops_exit=$?"), wrapper.index("builtin pwd"))
        self.assertIn('"$_serverops_exit"', wrapper)
        self.assertIn("builtin printf", wrapper)
        self.assertIn("builtin pwd", wrapper)
        self.assertNotIn("\nprintf '", wrapper)

    def test_wrapper_closes_a_multiline_command_without_a_leading_semicolon(self) -> None:
        wrapper = command_wrapper(
            "(\nprintf ok\n)\n",
            "ABC123",
            shell_nonce=SHELL_NONCE,
        )

        self.assertIn("{\n(\nprintf ok\n)\n}; _serverops_exit=$?", wrapper)
        self.assertNotIn("\n; }", wrapper)

    def test_interrupt_recovery_reports_130_without_repeating_command(self) -> None:
        wrapper = interrupt_recovery_wrapper(
            "ABC123",
            shell_nonce=SHELL_NONCE,
        )
        self.assertIn("__SERVEROPS_END_ABC123__:%s", wrapper)
        self.assertIn('"130"', wrapper)
        self.assertIn("__SERVEROPS_CWD_ABC123__", wrapper)
        self.assertIn("__SERVEROPS_HEALTH_ABC123__", wrapper)
        self.assertIn("__SERVEROPS_DEBUG_ABC123__", wrapper)
        self.assertIn("builtin trap -p DEBUG", wrapper)
        self.assertIn("builtin printf", wrapper)
        self.assertIn("builtin pwd", wrapper)

    def test_bootstrap_initializes_non_exported_readonly_original_shell_nonce(self) -> None:
        wrapper = shell_bootstrap_wrapper(SHELL_NONCE, "ABC123")

        self.assertIn("builtin readonly _SERVEROPS_SHELL_NONCE='D4E5F6'", wrapper)
        self.assertNotIn("export _SERVEROPS_SHELL_NONCE", wrapper)
        self.assertIn("builtin export PS1='' PS2='' PS3='' PS4=''", wrapper)
        self.assertIn(
            "builtin readonly PROMPT_COMMAND='' PS0='' PS1='' PS2='' PS3='' PS4=''",
            wrapper,
        )
        self.assertIn("builtin command -p stty -echo intr '^]'", wrapper)
        self.assertIn("builtin unset PROMPT_COMMAND PS0", wrapper)

    def test_shell_health_rejects_prompt_hooks_and_mutated_prompt_state(self) -> None:
        wrapper = command_wrapper("true", "ABC123", shell_nonce=SHELL_NONCE)

        for name in ("PROMPT_COMMAND", "PS0", "PS1", "PS2", "PS3", "PS4"):
            self.assertIn(f"[[ ${{{name}-}} == '' ]]", wrapper)
            self.assertIn(f"builtin declare -p {name}", wrapper)

    def test_marker_like_user_output_is_not_a_frame(self) -> None:
        parser = CommandFrameParser("ABC", shell_nonce=SHELL_NONCE)
        result = parser.feed(
            b"__SERVEROPS_BEGIN_ABC__\n"
            b"prefix __SERVEROPS_END_ABC__:0 suffix\n"
            b"__SERVEROPS_CWD_OTHER__:/forged\n"
            b"__SERVEROPS_DEBUG_ABC__\n__SERVEROPS_DEBUG_END_ABC__\n"
            b"__SERVEROPS_END_ABC__:0\n"
            b"__SERVEROPS_CWD_ABC__:/real\n"
            b"__SERVEROPS_HEALTH_ABC__:D4E5F6\n"
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("prefix __SERVEROPS_END_ABC__:0 suffix", result.output)
        self.assertEqual(result.cwd, "/real")

    def test_wrong_health_or_malformed_correlated_frame_fails_closed(self) -> None:
        cases = (
            (
                b"__SERVEROPS_BEGIN_ABC__\n__SERVEROPS_DEBUG_ABC__\n"
                b"__SERVEROPS_DEBUG_END_ABC__\n__SERVEROPS_END_ABC__:x\n"
            ),
            (
                b"__SERVEROPS_BEGIN_ABC__\n__SERVEROPS_DEBUG_ABC__\n"
                b"__SERVEROPS_DEBUG_END_ABC__\n__SERVEROPS_END_ABC__:0\n"
                b"not-a-cwd\n"
            ),
            (
                b"__SERVEROPS_BEGIN_ABC__\n__SERVEROPS_DEBUG_ABC__\n"
                b"__SERVEROPS_DEBUG_END_ABC__\n__SERVEROPS_END_ABC__:0\n"
                b"__SERVEROPS_CWD_ABC__:/tmp\n__SERVEROPS_HEALTH_ABC__:WRONG\n"
            ),
            (
                b"__SERVEROPS_BEGIN_ABC__\n__SERVEROPS_DEBUG_ABC__\n"
                b"trap -- 'echo debug' DEBUG\n__SERVEROPS_DEBUG_END_ABC__\n"
            ),
        )
        for payload in cases:
            with self.subTest(payload=payload):
                parser = CommandFrameParser("ABC", shell_nonce=SHELL_NONCE)
                with self.assertRaises(FrameProtocolError):
                    parser.feed(payload)

    def test_large_output_is_bounded_and_marked_truncated(self) -> None:
        parser = CommandFrameParser(
            "ABC",
            max_output_bytes=5,
            shell_nonce=SHELL_NONCE,
        )
        result = parser.feed(
            b"__SERVEROPS_BEGIN_ABC__\nabcdefghij\n"
            b"__SERVEROPS_DEBUG_ABC__\n__SERVEROPS_DEBUG_END_ABC__\n"
            b"__SERVEROPS_END_ABC__:0\n__SERVEROPS_CWD_ABC__:/tmp\n"
            b"__SERVEROPS_HEALTH_ABC__:D4E5F6\n"
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.output, "fghij")
        self.assertTrue(result.truncated)

    def test_very_large_output_before_chunked_markers_remains_bounded(self) -> None:
        payload = (
            b"__SERVEROPS_BEGIN_ABC__\n"
            + (b"x" * 50_000)
            + b"\n__SERVEROPS_DEBUG_ABC__\n__SERVEROPS_DEBUG_END_ABC__\n"
            + b"__SERVEROPS_END_ABC__:0\n__SERVEROPS_CWD_ABC__:/tmp\n"
            + b"__SERVEROPS_HEALTH_ABC__:D4E5F6\n"
        )
        parser = CommandFrameParser(
            "ABC",
            max_output_bytes=1_024,
            shell_nonce=SHELL_NONCE,
        )
        result = None
        for byte in payload:
            result = parser.feed(bytes((byte,)))
            if result is not None:
                break

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.output, "x" * 1_024)
        self.assertTrue(result.truncated)


if __name__ == "__main__":
    unittest.main()
