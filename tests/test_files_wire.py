from __future__ import annotations

import base64
import unittest

from codex_serverops_mcp.files.errors import RemoteFileError
from codex_serverops_mcp.files.wire import parse_file_response


def cell(value: str | bytes) -> str:
    content = value.encode("utf-8") if isinstance(value, str) else value
    return base64.b64encode(content).decode("ascii")


class FileWireTests(unittest.TestCase):
    def test_success_rows_preserve_binary_blob_until_service_decodes_it(self) -> None:
        token = "0123456789abcdef"
        output = "\n".join(
            (
                f"__SERVEROPS_FILE_BEGIN_{token}__",
                f"status\t{cell('ok')}",
                f"path\t{cell('/opt/app/a.txt')}",
                f"content\t{cell(b'hello\x00world')}",
                f"__SERVEROPS_FILE_END_{token}__",
            )
        )

        response = parse_file_response(output, token)

        self.assertEqual(response.one("path"), "/opt/app/a.txt")
        self.assertEqual(response.one_bytes("content"), b"hello\x00world")

    def test_structured_remote_error_preserves_controlled_code(self) -> None:
        token = "0123456789abcdef"
        output = "\n".join(
            (
                f"__SERVEROPS_FILE_BEGIN_{token}__",
                f"status\t{cell('error')}",
                f"code\t{cell('path_outside_roots')}",
                f"message\t{cell('Remote path is outside allowed roots.')}",
                f"__SERVEROPS_FILE_END_{token}__",
            )
        )

        with self.assertRaises(RemoteFileError) as captured:
            parse_file_response(output, token)

        self.assertEqual(captured.exception.code, "path_outside_roots")

    def test_missing_markers_and_invalid_base64_fail_closed(self) -> None:
        with self.assertRaises(RemoteFileError):
            parse_file_response("plain output", "0123456789abcdef")
        token = "0123456789abcdef"
        with self.assertRaises(RemoteFileError):
            parse_file_response(
                "\n".join(
                    (
                        f"__SERVEROPS_FILE_BEGIN_{token}__",
                        "status\tnot-base64!",
                        f"__SERVEROPS_FILE_END_{token}__",
                    )
                ),
                token,
            )


if __name__ == "__main__":
    unittest.main()
