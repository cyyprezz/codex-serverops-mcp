from __future__ import annotations

import unittest

from codex_serverops_mcp.files.errors import FileConflictError, RemoteFileError
from codex_serverops_mcp.files.patch import apply_unified_patch


class UnifiedPatchTests(unittest.TestCase):
    def test_multiple_hunks_apply_against_exact_context(self) -> None:
        original = "one\ntwo\nthree\nfour\n"
        patch = """--- a/file
+++ b/file
@@ -1,2 +1,2 @@
 one
-two
+second
@@ -4,1 +4,2 @@
 four
+five
"""

        result = apply_unified_patch(original, patch)

        self.assertEqual(result, "one\nsecond\nthree\nfour\nfive\n")

    def test_context_mismatch_is_a_hash_style_conflict(self) -> None:
        with self.assertRaises(FileConflictError):
            apply_unified_patch(
                "current\n",
                "@@ -1 +1 @@\n-expected\n+replacement\n",
            )

    def test_no_newline_marker_and_invalid_counts_are_handled(self) -> None:
        result = apply_unified_patch(
            "old",
            "@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n",
        )
        self.assertEqual(result, "new")
        with self.assertRaises(RemoteFileError):
            apply_unified_patch("one\n", "@@ -1,2 +1 @@\n-one\n+new\n")


if __name__ == "__main__":
    unittest.main()
