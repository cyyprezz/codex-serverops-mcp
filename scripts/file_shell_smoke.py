from __future__ import annotations

import json
import subprocess
from contextlib import suppress

from codex_serverops_mcp.config import Authentication, ConnectionType, ServerProfile
from codex_serverops_mcp.files import RemoteFileService
from codex_serverops_mcp.files.errors import RemoteFileError

CONTAINER_NAME = "codex-serverops-file-shell-smoke"
IMAGE_NAME = "codex-serverops-spike:local"


def _run(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


class DockerCommandRunner:
    def __call__(self, command: str, timeout: float | None) -> dict[str, object]:
        completed = subprocess.run(
            [
                "docker",
                "exec",
                "--user",
                "serverops",
                CONTAINER_NAME,
                "bash",
                "--noprofile",
                "--norc",
                "-c",
                command,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "status": "completed",
            "exit_code": completed.returncode,
            "output": completed.stdout + completed.stderr,
            "truncated": False,
        }


def run() -> dict[str, object]:
    _run(["docker", "rm", "-f", CONTAINER_NAME], check=False)
    _run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            CONTAINER_NAME,
            "--entrypoint",
            "sleep",
            IMAGE_NAME,
            "infinity",
        ]
    )
    profile = ServerProfile(
        display_name="File shell smoke",
        connection_type=ConnectionType.DIRECT,
        authentication=Authentication.OPENSSH,
        host="127.0.0.1",
        port=22,
        user="serverops",
        allowed_roots=("/opt/app",),
        allow_file_read=True,
        allow_file_write=True,
        environment="test",
    )
    service = RemoteFileService(profile, DockerCommandRunner())
    try:
        created = service.edit(
            "write_text",
            {"path": "/opt/app/file-smoke.txt", "content": "alpha\nbeta\n"},
        )
        read = service.read("read_text", {"path": "/opt/app/file-smoke.txt"})
        line_read = service.read(
            "read_text",
            {"path": "/opt/app/file-smoke.txt", "start_line": 2, "end_line": 2},
        )
        if line_read["content"] != "beta\n":
            raise AssertionError("structured line read did not preserve the selected line")
        listed = service.read("list", {"path": "/opt/app", "max_results": 1_000})
        if "file-smoke.txt" not in {entry["name"] for entry in listed["entries"]}:
            raise AssertionError("structured listing omitted the created file")
        patched = service.edit(
            "apply_patch",
            {
                "path": "/opt/app/file-smoke.txt",
                "patch": "@@ -1,2 +1,2 @@\n alpha\n-beta\n+gamma\n",
                "expected_sha256": created["sha256"],
            },
        )
        searched = service.read(
            "search_text",
            {"path": "/opt/app/file-smoke.txt", "query": "gamma", "max_results": 10},
        )
        if len(searched["matches"]) != 1:
            raise AssertionError(f"unexpected structured search result: {searched!r}")
        empty = service.edit(
            "write_text",
            {"path": "/opt/app/empty-smoke.txt", "content": ""},
        )
        empty_read = service.read("read_text", {"path": "/opt/app/empty-smoke.txt"})
        if empty_read["content"] != "":
            raise AssertionError("empty structured write returned non-empty content")
        service.edit(
            "remove",
            {"path": "/opt/app/empty-smoke.txt", "expected_sha256": empty["sha256"]},
        )
        _run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "sh",
                "-c",
                "printf YQBi | base64 -d > /opt/app/binary-smoke.bin; "
                "chown serverops /opt/app/binary-smoke.bin",
            ]
        )
        try:
            service.read("read_text", {"path": "/opt/app/binary-smoke.bin"})
        except RemoteFileError as error:
            if error.code != "binary_file":
                raise
        else:
            raise AssertionError("binary structured read was not rejected")
        _run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "ln",
                "-s",
                "/etc/passwd",
                "/opt/app/file-smoke-escape",
            ]
        )
        try:
            service.read("read_text", {"path": "/opt/app/file-smoke-escape"})
        except RemoteFileError as error:
            if error.code != "path_outside_roots":
                raise
        else:
            raise AssertionError("file helper followed a symlink outside allowed roots")
        _run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "sh",
                "-c",
                "printf locked > /opt/app/root-owned.txt; chmod 666 /opt/app/root-owned.txt; "
                "mkdir /opt/app/foreign-tree; chown serverops /opt/app/foreign-tree; "
                "printf locked > /opt/app/foreign-tree/root-owned.txt",
            ]
        )
        for action, payload in (
            (
                "write_text",
                {"path": "/opt/app/root-owned.txt", "content": "replacement\n"},
            ),
            (
                "remove",
                {"path": "/opt/app/foreign-tree", "recursive": True},
            ),
        ):
            try:
                service.edit(action, payload)
            except RemoteFileError as error:
                if error.code != "ownership_unsupported":
                    raise
            else:
                raise AssertionError(f"{action} accepted a foreign-owned path")
        return {
            "status": "passed",
            "created": created["status"],
            "read_content": read["content"],
            "patched_sha256": patched["sha256"],
            "checks": [
                "write",
                "read",
                "line_read",
                "list",
                "patch",
                "search",
                "empty_write",
                "binary_rejection",
                "symlink_escape",
                "foreign_ownership",
            ],
        }
    finally:
        with suppress(Exception):
            _run(["docker", "rm", "-f", CONTAINER_NAME], check=False)


def main() -> None:
    print(json.dumps(run(), sort_keys=True))


if __name__ == "__main__":
    main()
