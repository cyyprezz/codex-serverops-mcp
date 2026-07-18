from __future__ import annotations

import argparse
import base64
import json
import shlex
from contextlib import suppress
from pathlib import Path

from codex_serverops_mcp.application import ApplicationServices
from codex_serverops_mcp.setup.keys import read_public_key, validate_public_key_line

if __package__:
    from ._external_runtime import isolated_external_services
else:
    from _external_runtime import isolated_external_services

REMOVED_MARKER = "serverops-test-key-removed"


def build_authorized_key_removal_command(public_key: str) -> str:
    public_key = validate_public_key_line(public_key)
    fields = public_key.split()
    if len(fields) < 3 or not any(part.startswith("serverops:") for part in fields[2:]):
        raise ValueError("cleanup requires a public key marked with a serverops comment")
    encoded = base64.b64encode(public_key.encode("utf-8")).decode("ascii")
    return "\n".join(
        (
            "set -eu",
            '_serverops_auth="$HOME/.ssh/authorized_keys"',
            'test -f "$_serverops_auth"',
            'test -O "$_serverops_auth"',
            f"_serverops_key=$(printf '%s' {shlex.quote(encoded)} | base64 -d)",
            "_serverops_count=$(awk -v key=\"$_serverops_key\" "
            "'$0 == key { count++ } END { print count + 0 }' \"$_serverops_auth\")",
            'test "$_serverops_count" -eq 1',
            '_serverops_tmp=$(mktemp "$HOME/.ssh/.authorized_keys.serverops.XXXXXX")',
            'cleanup() { rm -f -- "$_serverops_tmp"; }',
            "trap cleanup EXIT TERM INT",
            "awk -v key=\"$_serverops_key\" '$0 != key' "
            '"$_serverops_auth" > "$_serverops_tmp"',
            'chmod --reference="$_serverops_auth" -- "$_serverops_tmp"',
            'chgrp --reference="$_serverops_auth" -- "$_serverops_tmp"',
            'mv -f -- "$_serverops_tmp" "$_serverops_auth"',
            "trap - EXIT TERM INT",
            'if grep -qxF -- "$_serverops_key" "$_serverops_auth"; then exit 96; fi',
            f"printf '%s' {shlex.quote(REMOVED_MARKER)}",
        )
    )


def run(profile_name: str, public_key_path: Path) -> dict[str, object]:
    if not profile_name.endswith("-test"):
        raise ValueError("external cleanup requires an explicit test profile")
    public_key = read_public_key(public_key_path.resolve())
    command = build_authorized_key_removal_command(public_key)
    with isolated_external_services() as services:
        return _run(profile_name, command, services)


def _run(
    profile_name: str,
    command: str,
    services: ApplicationServices,
) -> dict[str, object]:
    session_id: str | None = None
    try:
        opened = services.server_connection("open", profile_name=profile_name)
        session_id = str(opened["session_id"])
        result = services.server_exec(session_id, command)
        if (
            result.get("status") != "completed"
            or result.get("exit_code") != 0
            or result.get("output") != REMOVED_MARKER
        ):
            raise RuntimeError("the exact test public-key line was not safely removed")
        services.server_connection("close", session_id=session_id)
        session_id = None
        return {
            "status": "removed",
            "profile": profile_name,
            "remote_file": "~/.ssh/authorized_keys",
            "removed_exact_public_key_lines": 1,
        }
    finally:
        if session_id is not None:
            with suppress(Exception):
                services.server_connection("close", session_id=session_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--public-key-file", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.profile, args.public_key_file), indent=2))


if __name__ == "__main__":
    main()
