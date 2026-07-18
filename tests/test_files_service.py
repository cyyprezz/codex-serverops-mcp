from __future__ import annotations

import base64
import hashlib
import re
import unittest

from codex_serverops_mcp.config import Authentication, ConnectionType, ServerProfile
from codex_serverops_mcp.files.errors import FileConflictError, RemoteFileError
from codex_serverops_mcp.files.service import RemoteFileService

TOKEN = re.compile(r"__SERVEROPS_FILE_BEGIN_([0-9a-f]{32})__")


def profile(*, read: bool = True, write: bool = True) -> ServerProfile:
    return ServerProfile(
        display_name="Files",
        connection_type=ConnectionType.DIRECT,
        authentication=Authentication.OPENSSH,
        host="example.test",
        port=22,
        user="deploy",
        allowed_roots=("/opt/app",),
        allow_terminal=True,
        allow_file_read=read,
        allow_file_write=write,
    )


class SequencedRunner:
    def __init__(self, responses: list[list[tuple[str, tuple[str | bytes, ...]]]]) -> None:
        self.responses = responses
        self.commands: list[str] = []

    def __call__(self, command: str, timeout: float | None) -> dict[str, object]:
        del timeout
        self.commands.append(command)
        match = TOKEN.search(command)
        assert match is not None
        token = match.group(1)
        rows = self.responses.pop(0)
        lines = [f"__SERVEROPS_FILE_BEGIN_{token}__", _row("status", "ok")]
        lines.extend(_row(key, *values) for key, values in rows)
        lines.append(f"__SERVEROPS_FILE_END_{token}__")
        return {
            "status": "completed",
            "exit_code": 0,
            "output": "\n".join(lines),
            "truncated": False,
        }


def _row(key: str, *values: str | bytes) -> str:
    encoded = []
    for value in values:
        content = value.encode("utf-8") if isinstance(value, str) else value
        encoded.append(base64.b64encode(content).decode("ascii"))
    return "\t".join((key, *encoded))


class RemoteFileServiceTests(unittest.TestCase):
    def test_read_text_reports_hash_range_and_safe_utf8_boundary_truncation(self) -> None:
        digest = hashlib.sha256(b"hello world").hexdigest()
        runner = SequencedRunner(
            [[
                ("path", ("/opt/app/a.txt",)),
                ("sha256", (digest,)),
                ("selected_bytes", ("12",)),
                ("truncated", ("true",)),
                ("content", (b"hello \xe2\x82",)),
            ]]
        )
        service = RemoteFileService(profile(), runner)

        result = service.read("read_text", {"path": "a.txt", "byte_limit": 8})

        self.assertEqual(result["content"], "hello ")
        self.assertTrue(result["truncated"])
        self.assertEqual(result["sha256"], digest)

    def test_binary_and_invalid_utf8_files_fail_with_controlled_codes(self) -> None:
        digest = "0" * 64
        for content, code in ((b"a\0b", "binary_file"), (b"\xff", "invalid_utf8")):
            runner = SequencedRunner(
                [[
                    ("path", ("/opt/app/a",)),
                    ("sha256", (digest,)),
                    ("selected_bytes", (str(len(content)),)),
                    ("truncated", ("false",)),
                    ("content", (content,)),
                ]]
            )
            with self.assertRaises(RemoteFileError) as captured:
                RemoteFileService(profile(), runner).read("read_text", {"path": "/opt/app/a"})
            self.assertEqual(captured.exception.code, code)

    def test_apply_patch_reads_then_writes_with_observed_hash(self) -> None:
        original = b"one\ntwo\n"
        updated = b"one\nsecond\n"
        original_hash = hashlib.sha256(original).hexdigest()
        updated_hash = hashlib.sha256(updated).hexdigest()
        runner = SequencedRunner(
            [
                [
                    ("path", ("/opt/app/a.txt",)),
                    ("sha256", (original_hash,)),
                    ("selected_bytes", (str(len(original)),)),
                    ("truncated", ("false",)),
                    ("content", (original,)),
                ],
                [
                    ("path", ("/opt/app/a.txt",)),
                    ("sha256", (updated_hash,)),
                    ("created", ("false",)),
                ],
            ]
        )
        service = RemoteFileService(profile(), runner)

        result = service.edit(
            "apply_patch",
            {
                "path": "/opt/app/a.txt",
                "patch": "@@ -1,2 +1,2 @@\n one\n-two\n+second\n",
                "expected_sha256": original_hash,
            },
        )

        self.assertEqual(result["sha256"], updated_hash)
        self.assertIn(original_hash, runner.commands[1])

    def test_apply_patch_rejects_stale_caller_hash_before_write(self) -> None:
        content = b"one\n"
        observed = hashlib.sha256(content).hexdigest()
        runner = SequencedRunner(
            [[
                ("path", ("/opt/app/a",)),
                ("sha256", (observed,)),
                ("selected_bytes", (str(len(content)),)),
                ("truncated", ("false",)),
                ("content", (content,)),
            ]]
        )

        with self.assertRaises(FileConflictError):
            RemoteFileService(profile(), runner).edit(
                "apply_patch",
                {
                    "path": "/opt/app/a",
                    "patch": "@@ -1 +1 @@\n-one\n+two\n",
                    "expected_sha256": "0" * 64,
                },
            )

        self.assertEqual(len(runner.commands), 1)

    def test_profile_capabilities_and_input_limits_are_enforced_locally(self) -> None:
        with self.assertRaises(RemoteFileError):
            RemoteFileService(profile(read=False, write=False), SequencedRunner([])).read(
                "stat", {"path": "/opt/app"}
            )
        with self.assertRaises(ValueError):
            RemoteFileService(profile(), SequencedRunner([])).read(
                "search_text", {"path": "/opt/app", "query": "bad\nquery"}
            )
        with self.assertRaises(ValueError):
            RemoteFileService(profile(), SequencedRunner([])).edit(
                "write_text", {"path": "/opt/app/a", "content": "x" * 131_073}
            )


if __name__ == "__main__":
    unittest.main()
