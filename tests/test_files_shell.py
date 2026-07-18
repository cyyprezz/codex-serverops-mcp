from __future__ import annotations

import unittest

from codex_serverops_mcp.files.shell import FileShellBuilder


class FileShellBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = FileShellBuilder(("/opt/app",))

    def test_untrusted_values_are_encoded_not_interpolated_as_shell_syntax(self) -> None:
        hostile = "/opt/app/$(touch SHOULD_NOT_RUN)"

        commands = (
            self.builder.list_directory(hostile, 20),
            self.builder.search_text(hostile, "$(also-not-code)", 10),
            self.builder.write_text(hostile, b"$HOME is content", None),
        )

        for command in commands:
            self.assertNotIn(hostile, command.command)
            self.assertNotIn("$(also-not-code)", command.command)
            self.assertTrue(command.command.startswith("(\n"))
            self.assertTrue(command.command.endswith("\n)\n"))

    def test_write_contract_contains_same_directory_atomic_and_conflict_checks(self) -> None:
        command = self.builder.write_text(
            "/opt/app/a.txt",
            b"updated\n",
            "0" * 64,
        ).command

        for required in (
            "realpath --",
            "mktemp --",
            "sha256sum --",
            "Structured writes require a file owned by the SSH user.",
            "Remote file changed before replacement.",
            "mv -f --",
        ):
            self.assertIn(required, command)

    def test_remove_and_rename_protect_allowed_root_itself(self) -> None:
        remove = self.builder.remove(
            "/opt/app",
            recursive=True,
            expected_sha256=None,
        )
        self.assertIn("protected_root", remove.command)
        self.assertIn("protected_root", self.builder.rename("/opt/app", "/opt/new").command)

    def test_destructive_edits_require_current_user_ownership(self) -> None:
        rename = self.builder.rename("/opt/app/a", "/opt/app/b").command
        remove = self.builder.remove(
            "/opt/app/a",
            recursive=True,
            expected_sha256=None,
        ).command

        self.assertIn("_serverops_owned_tree", rename)
        self.assertIn("ownership_unsupported", rename)
        self.assertIn("Recursive removal contains a foreign-owned path.", remove)


if __name__ == "__main__":
    unittest.main()
