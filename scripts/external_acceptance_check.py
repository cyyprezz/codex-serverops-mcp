from __future__ import annotations

import argparse
import json
import secrets
import shlex
import time
from contextlib import suppress

from codex_serverops_mcp.application import ApplicationServices
from codex_serverops_mcp.broker.errors import BrokerRemoteError
from codex_serverops_mcp.config import ElevationMode, ServerProfile
from codex_serverops_mcp.security import default_audit_path


def validate_acceptance_profile(profile: ServerProfile, expected_root: str) -> None:
    if profile.environment != "test":
        raise RuntimeError("external acceptance requires a profile marked as test")
    if profile.allowed_roots != (expected_root,):
        raise RuntimeError("profile must contain exactly the expected disposable root")
    if expected_root in {"/", "/etc", "/home", "/opt"}:
        raise RuntimeError("expected root is too broad for an external acceptance run")
    if not all((profile.allow_terminal, profile.allow_file_read, profile.allow_file_write)):
        raise RuntimeError("terminal and structured file capabilities must be enabled")
    if profile.elevation_mode is not ElevationMode.INTERACTIVE:
        raise RuntimeError("external acceptance requires interactive elevation")
    if not profile.allow_root_session:
        raise RuntimeError("external acceptance requires the guided root-session gate")


def run(profile_name: str, expected_root: str) -> dict[str, object]:
    services = ApplicationServices.create()
    snapshot = services.profiles.load()
    try:
        profile = snapshot.config.profiles[profile_name]
    except KeyError as error:
        raise RuntimeError(f"profile does not exist: {profile_name}") from error
    validate_acceptance_profile(profile, expected_root)

    token = secrets.token_hex(8)
    workdir = f"{expected_root}/.serverops-acceptance-{token}"
    file_path = f"{workdir}/state.txt"
    link_path = f"{workdir}/outside-link"
    file_content = f"external-file-{token}\n"
    patched_content = f"external-patched-{token}\n"
    synthetic_secret = f"external-audit-password-{token}"
    session_id: str | None = None
    root_session_id: str | None = None
    workdir_created = False
    checks: list[str] = []

    try:
        opened = services.server_connection("open", profile_name=profile_name)
        session_id = str(opened["session_id"])
        _expect(opened.get("effective_user") == profile.user, "normal SSH identity mismatch")
        checks.append("password_login_and_identity")

        root_stat = services.server_files("stat", session_id, path=expected_root)
        _expect(root_stat.get("type") == "directory", "expected root is not a directory")
        services.server_file_edit("mkdir", session_id, path=workdir)
        workdir_created = True
        services.server_exec(session_id, f"cd -- {shlex.quote(workdir)}")
        current = services.server_exec(session_id, "pwd")
        _expect(current.get("output", "").strip() == workdir, "held shell lost cwd")
        exit_result = services.server_exec(session_id, "bash -c 'exit 7'")
        _expect(exit_result.get("exit_code") == 7, "remote exit status was not preserved")
        checks.append("held_bash_state_and_exit_status")

        audit_probe = services.server_exec(
            session_id,
            f"printf audit-ok # password={synthetic_secret}",
        )
        audit = audit_probe.get("audit")
        _expect(
            isinstance(audit, dict) and audit.get("command_redacted") is True,
            "synthetic command secret was not marked as redacted",
        )
        checks.append("audit_redaction")

        created = services.server_file_edit(
            "write_text",
            session_id,
            path=file_path,
            content=file_content,
        )
        original_hash = str(created["sha256"])
        read = services.server_files("read_text", session_id, path=file_path)
        _expect(read.get("content") == file_content, "structured file content changed")
        patched = services.server_file_edit(
            "apply_patch",
            session_id,
            path=file_path,
            patch=(
                "@@ -1 +1 @@\n"
                f"-{file_content.rstrip()}\n"
                f"+{patched_content.rstrip()}\n"
            ),
            expected_sha256=original_hash,
        )
        patched_hash = str(patched["sha256"])
        try:
            services.server_file_edit(
                "write_text",
                session_id,
                path=file_path,
                content="stale-write-must-fail\n",
                expected_sha256=original_hash,
            )
        except BrokerRemoteError as error:
            _expect(error.code == "file_conflict", "stale write returned the wrong error")
        else:
            raise AssertionError("stale structured write was accepted")
        hashed = services.server_files("hash", session_id, path=file_path)
        _expect(hashed.get("sha256") == patched_hash, "structured hash mismatch")
        searched = services.server_files(
            "search_text",
            session_id,
            path=workdir,
            query=patched_content.rstrip(),
        )
        _expect(len(searched.get("matches", [])) == 1, "structured search mismatch")
        checks.append("structured_files_patch_hash_conflict_search")

        services.server_exec(
            session_id,
            f"ln -s -- /etc/passwd {shlex.quote(link_path)}",
        )
        try:
            services.server_files("read_text", session_id, path=link_path)
        except BrokerRemoteError as error:
            _expect(error.code == "path_outside_roots", "symlink escape returned wrong error")
        else:
            raise AssertionError("structured read followed a symlink outside the allowed root")
        services.server_exec(session_id, f"rm -f -- {shlex.quote(link_path)}")
        checks.append("structured_file_symlink_escape")

        terminal = services.server_terminal("start", session_id, command="cat")
        cursor = int(terminal["output_cursor"])
        marker = f"terminal-{token}"
        services.server_terminal("write", session_id, text=f"{marker}\r\n")
        output = ""
        deadline = time.monotonic() + 5
        while marker not in output and time.monotonic() < deadline:
            read_terminal = services.server_terminal(
                "read",
                session_id,
                cursor=cursor,
                timeout=0.5,
            )
            output += str(read_terminal["output"])
            cursor = int(read_terminal["next_cursor"])
        _expect(marker in output, "raw terminal output was not readable")
        services.server_terminal("close", session_id)
        checks.append("raw_terminal")

        services.server_elevation("release", session_id)
        inactive = services.server_elevation("status", session_id)
        _expect(inactive.get("active") is False, "sudo timestamp did not release")
        acquired = services.server_elevation("acquire", session_id)
        _expect(acquired.get("active") is True, "interactive sudo was not acquired")
        active = services.server_elevation("status", session_id)
        _expect(active.get("active") is True, "sudo cache was not observed")
        elevated = services.server_elevation("exec", session_id, command="id -u")
        _expect(
            elevated.get("effective_user") == "root"
            and elevated.get("output", "").strip() == "0",
            "one-shot elevated identity mismatch",
        )
        checks.append("sudo_acquire_cache_and_exec")

        root_opened = services.server_elevation("open_root_session", session_id)
        root_session_id = str(root_opened["session_id"])
        _expect(
            root_opened.get("root_session") is True
            and root_opened.get("effective_user") == "root"
            and root_opened.get("parent_session_id") == session_id,
            "dedicated root-session metadata mismatch",
        )
        root_identity = services.server_exec(root_session_id, "id -u")
        _expect(root_identity.get("output", "").strip() == "0", "root session is not root")
        try:
            services.server_files("stat", root_session_id, path=expected_root)
        except BrokerRemoteError as error:
            _expect(
                error.code == "root_session_file_access_disabled",
                "root structured-file rejection returned the wrong error",
            )
        else:
            raise AssertionError("root session exposed structured file access")
        services.server_elevation("close_root_session", root_session_id)
        root_session_id = None
        checks.append("dedicated_root_session")

        rediscovered = services.server_connection("rediscover", session_id=session_id)
        _expect(
            rediscovered.get("rediscovered") is True
            and rediscovered.get("command_retried") is False,
            "rediscovery contract was not explicit about no retry",
        )
        checks.append("broker_session_rediscovery_no_retry")

        services.server_elevation("release", session_id)
        released = services.server_elevation("status", session_id)
        _expect(released.get("active") is False, "sudo cache remained active after release")
        services.server_file_edit(
            "remove",
            session_id,
            path=workdir,
            recursive=True,
        )
        workdir_created = False
        services.server_connection("close", session_id=session_id)
        session_id = None
        checks.append("remote_directory_sudo_and_session_cleanup")
    finally:
        if root_session_id is not None:
            with suppress(Exception):
                services.server_elevation("close_root_session", root_session_id)
        if session_id is not None:
            with suppress(Exception):
                services.server_elevation("release", session_id)
            if workdir_created:
                with suppress(Exception):
                    services.server_file_edit(
                        "remove",
                        session_id,
                        path=workdir,
                        recursive=True,
                    )
            with suppress(Exception):
                services.server_connection("close", session_id=session_id)

    audit_text = "".join(
        path.read_text(encoding="utf-8")
        for path in sorted(default_audit_path().glob("*.jsonl"))
    )
    _expect(synthetic_secret not in audit_text, "audit retained the synthetic secret")
    _expect(file_content.rstrip() not in audit_text, "audit retained structured file content")
    checks.append("audit_content_absence")
    return {"status": "passed", "profile": profile_name, "checks": checks}


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run destructive-but-contained acceptance checks on a disposable SSH profile."
    )
    parser.add_argument("--profile", required=True)
    parser.add_argument("--expected-root", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.profile, args.expected_root), indent=2))


if __name__ == "__main__":
    main()
