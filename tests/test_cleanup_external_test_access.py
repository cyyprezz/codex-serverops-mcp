from __future__ import annotations

import base64
import unittest

from scripts.cleanup_external_test_access import (
    REMOVED_MARKER,
    build_authorized_key_removal_command,
)


class ExternalTestAccessCleanupTests(unittest.TestCase):
    @staticmethod
    def _public_key(comment: str) -> str:
        algorithm = b"ssh-ed25519"
        key_bytes = bytes(range(32))
        blob = (
            len(algorithm).to_bytes(4, "big")
            + algorithm
            + len(key_bytes).to_bytes(4, "big")
            + key_bytes
        )
        return f"ssh-ed25519 {base64.b64encode(blob).decode()} {comment}"

    def test_command_removes_one_exact_marked_key_atomically(self) -> None:
        key = self._public_key("serverops:disposable-test")

        command = build_authorized_key_removal_command(key)

        encoded = base64.b64encode(key.encode()).decode()
        self.assertIn(encoded, command)
        self.assertNotIn(key, command)
        self.assertIn('test "$_serverops_count" -eq 1', command)
        self.assertIn("chmod --reference", command)
        self.assertIn("chgrp --reference", command)
        self.assertIn("mv -f --", command)
        self.assertIn("trap cleanup EXIT TERM INT", command)
        self.assertIn(REMOVED_MARKER, command)

    def test_command_rejects_unmarked_public_keys(self) -> None:
        with self.assertRaises(ValueError):
            build_authorized_key_removal_command(
                self._public_key("personal-key")
            )


if __name__ == "__main__":
    unittest.main()
