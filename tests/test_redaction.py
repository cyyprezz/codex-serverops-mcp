from __future__ import annotations

import unittest

from codex_serverops_mcp.security import redact_preview


class RedactionTests(unittest.TestCase):
    def test_known_secret_patterns_are_replaced(self) -> None:
        command = (
            "curl -H 'Authorization: Bearer abcdefghijklmnop' "
            "https://alice:correct-horse@example.test/ "
            "--password hunter2 password=another "
            "ghp_abcdefghijklmnopqrstuvwxyz123456"
        )

        result = redact_preview(command, max_bytes=1024)

        self.assertTrue(result.redacted)
        for secret in ("abcdefghijklmnop", "correct-horse", "hunter2", "another", "ghp_"):
            self.assertNotIn(secret, result.text)

    def test_private_key_block_is_never_preserved(self) -> None:
        key = "-----BEGIN OPENSSH PRIVATE KEY-----\nsecret\n-----END OPENSSH PRIVATE KEY-----"
        result = redact_preview(f"printf '{key}'", max_bytes=1024)
        self.assertEqual(result.text, "printf '[REDACTED_PRIVATE_KEY]'")
        self.assertTrue(result.redacted)

    def test_utf8_preview_is_bounded_without_broken_character(self) -> None:
        result = redact_preview("ä" * 100, max_bytes=25)
        self.assertLessEqual(len(result.text.encode("utf-8")), 25)
        self.assertTrue(result.truncated)


if __name__ == "__main__":
    unittest.main()
