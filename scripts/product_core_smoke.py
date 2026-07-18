from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import time
from contextlib import suppress
from pathlib import Path

from codex_serverops_mcp.application import ApplicationServices
from codex_serverops_mcp.broker.client import BrokerClient
from codex_serverops_mcp.broker.errors import BrokerRemoteError
from codex_serverops_mcp.broker.manager import BrokerManager
from codex_serverops_mcp.config import (
    Authentication,
    ConnectionType,
    ElevationMode,
    ServerOpsConfig,
    ServerProfile,
    TomlProfileRepository,
)
from codex_serverops_mcp.installer.doctor import Doctor
from codex_serverops_mcp.installer.paths import InstallPaths
from codex_serverops_mcp.security import AuditLogger

CONTAINER_NAME = "codex-serverops-product-smoke"
IMAGE_NAME = "codex-serverops-spike:local"


def _run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _wait_for_port(port: int) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError("product smoke SSH fixture did not become reachable")


def _start_fixture(runtime: Path, password_path: Path, public_key: Path) -> int:
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        check=False,
        capture_output=True,
        text=True,
    )
    _run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            CONTAINER_NAME,
            "--publish",
            "127.0.0.1::22",
            "--mount",
            f"type=bind,source={password_path},target=/run/secrets/serverops_password,readonly",
            "--mount",
            f"type=bind,source={public_key},target=/run/secrets/serverops_authorized_key,readonly",
            IMAGE_NAME,
        ]
    )
    mapping = _run(["docker", "port", CONTAINER_NAME, "22/tcp"]).stdout.strip()
    port = int(mapping.rsplit(":", 1)[1])
    _wait_for_port(port)
    return port


def _stop_fixture() -> None:
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        check=False,
        capture_output=True,
        text=True,
    )


def _write_fixture_host_key(port: int, known_hosts: Path) -> None:
    public_key = _run(
        [
            "docker",
            "exec",
            CONTAINER_NAME,
            "cat",
            "/etc/ssh/ssh_host_ed25519_key.pub",
        ]
    ).stdout.split()
    if len(public_key) < 2 or public_key[0] != "ssh-ed25519":
        raise RuntimeError("fixture did not expose its public ED25519 host key")
    line = f"[127.0.0.1]:{port} {public_key[0]} {public_key[1]}"
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    known_hosts.write_text(line + "\n", encoding="utf-8")


def run(project_root: Path) -> dict[str, object]:
    runtime = (project_root / ".product-smoke-runtime").resolve()
    if runtime.name != ".product-smoke-runtime":
        raise RuntimeError("unexpected product smoke runtime path")
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir()
    password_path = runtime / "password"
    identity = runtime / "id_ed25519"
    public_key = identity.with_suffix(".pub")
    password_path.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    _run(
        [
            "ssh-keygen.exe",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            str(identity),
        ]
    )
    manager = BrokerManager(runtime / "broker-runtime")
    previous_local_app_data = os.environ.get("LOCALAPPDATA")
    os.environ["LOCALAPPDATA"] = str(runtime / "local-app-data")
    repository = TomlProfileRepository()
    session_id: str | None = None
    root_session_id: str | None = None
    broker_pid: object = None
    worker_pid: object = None
    try:
        port = _start_fixture(runtime, password_path, public_key)
        known_hosts = repository.path.parent / "known_hosts"
        _write_fixture_host_key(port, known_hosts)
        repository.save(
            ServerOpsConfig(
                profiles={
                    "product-smoke": ServerProfile(
                        display_name="Product smoke fixture",
                        connection_type=ConnectionType.DIRECT,
                        authentication=Authentication.OPENSSH,
                        host="127.0.0.1",
                        port=port,
                        user="serverops",
                        identity_file=str(identity),
                        allowed_roots=("/opt/app",),
                        allow_file_read=True,
                        allow_file_write=True,
                        elevation_mode=ElevationMode.NON_INTERACTIVE,
                        allow_root_session=True,
                        environment="test",
                    )
                }
            )
        )
        audit_root = runtime / "audit"
        services = ApplicationServices(repository, manager, audit=AuditLogger(audit_root))
        opened = services.server_connection("open", profile_name="product-smoke")
        session_id = str(opened["session_id"])
        worker_pid = opened["worker_pid"]
        services.server_exec(session_id, "cd /opt/app")
        current = services.server_exec(session_id, "pwd")
        if current["output"].strip() != "/opt/app":
            raise AssertionError("held shell did not preserve cwd")
        services.server_exec(session_id, ". .venv/bin/activate")
        environment = services.server_exec(
            session_id,
            "python3 -c 'import sys; print(sys.prefix)'",
        )
        if environment["output"].strip() != "/opt/app/.venv":
            raise AssertionError("held shell did not preserve the virtual environment")
        exit_result = services.server_exec(session_id, "bash -c 'exit 7'")
        if exit_result["exit_code"] != 7:
            raise AssertionError("completed command exit code was not preserved")
        synthetic_secret = "synthetic-audit-secret-value"
        audit_probe = services.server_exec(
            session_id,
            f"printf audit-ok # password={synthetic_secret}",
        )
        if not audit_probe["audit"]["command_redacted"]:
            raise AssertionError("known command secret was not marked as redacted")
        file_stat_preflight = services.server_files(
            "stat",
            session_id,
            path="/opt/app",
        )
        if file_stat_preflight["type"] != "directory":
            raise AssertionError("structured file stat preflight failed")
        large_content = "x" * 65_535 + "\n"
        large_created = services.server_file_edit(
            "write_text",
            session_id,
            path="/opt/app/structured-large.txt",
            content=large_content,
        )
        large_read = services.server_files(
            "read_text",
            session_id,
            path="/opt/app/structured-large.txt",
            byte_limit=65_536,
        )
        if large_read["content"] != large_content:
            raise AssertionError("large structured transfer changed UTF-8 text")
        services.server_file_edit(
            "remove",
            session_id,
            path="/opt/app/structured-large.txt",
            expected_sha256=str(large_created["sha256"]),
        )
        created = services.server_file_edit(
            "write_text",
            session_id,
            path="/opt/app/structured.txt",
            content="alpha\nbeta\n",
        )
        initial_hash = str(created["sha256"])
        read_text = services.server_files(
            "read_text",
            session_id,
            path="/opt/app/structured.txt",
            byte_limit=1_024,
        )
        if read_text["content"] != "alpha\nbeta\n" or read_text["sha256"] != initial_hash:
            raise AssertionError("structured UTF-8 read did not preserve content and hash")
        patched = services.server_file_edit(
            "apply_patch",
            session_id,
            path="/opt/app/structured.txt",
            patch="@@ -1,2 +1,2 @@\n alpha\n-beta\n+gamma\n",
            expected_sha256=initial_hash,
        )
        patched_hash = str(patched["sha256"])
        try:
            services.server_file_edit(
                "write_text",
                session_id,
                path="/opt/app/structured.txt",
                content="stale write\n",
                expected_sha256=initial_hash,
            )
        except BrokerRemoteError as error:
            if error.code != "file_conflict":
                raise
        else:
            raise AssertionError("stale structured write was not rejected")
        services.server_file_edit(
            "mkdir",
            session_id,
            path="/opt/app/structured-dir",
        )
        renamed = services.server_file_edit(
            "rename",
            session_id,
            path="/opt/app/structured.txt",
            destination_path="/opt/app/structured-dir/renamed.txt",
        )
        searched = services.server_files(
            "search_text",
            session_id,
            path="/opt/app/structured-dir",
            query="gamma",
        )
        if len(searched["matches"]) != 1:
            raise AssertionError("structured text search did not return the expected match")
        hashed = services.server_files(
            "hash",
            session_id,
            path=str(renamed["destination"]),
        )
        if hashed["sha256"] != patched_hash:
            raise AssertionError("structured hash changed after rename")
        services.server_exec(session_id, "ln -s /etc/passwd /opt/app/escape-link")
        try:
            services.server_files(
                "read_text",
                session_id,
                path="/opt/app/escape-link",
            )
        except BrokerRemoteError as error:
            if error.code != "path_outside_roots":
                raise
        else:
            raise AssertionError("structured read followed a symlink outside allowed roots")
        services.server_exec(session_id, "rm -f /opt/app/escape-link")
        services.server_file_edit(
            "remove",
            session_id,
            path=str(renamed["destination"]),
            expected_sha256=patched_hash,
        )
        services.server_file_edit(
            "remove",
            session_id,
            path="/opt/app/structured-dir",
        )
        services.server_elevation("release", session_id)
        try:
            services.server_elevation("acquire", session_id)
        except BrokerRemoteError as error:
            if error.code != "elevation_authentication_required":
                raise
        else:
            raise AssertionError("non-interactive sudo unexpectedly prompted or succeeded")
        _run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "sh",
                "-c",
                "printf 'serverops ALL=(ALL:ALL) NOPASSWD: ALL\\n' "
                "> /etc/sudoers.d/serverops; chmod 0440 /etc/sudoers.d/serverops",
            ]
        )
        acquired = services.server_elevation("acquire", session_id)
        if not acquired["active"]:
            raise AssertionError("non-interactive NOPASSWD sudo was not acquired")
        elevation_status = services.server_elevation("status", session_id)
        if not elevation_status["active"]:
            raise AssertionError("sudo status did not observe the active credential")
        elevated = services.server_elevation(
            "exec",
            session_id,
            command="printf 'elevated-user='; id -u; exit 7",
        )
        if elevated["exit_code"] != 7 or elevated["output"] != "elevated-user=0\n":
            raise AssertionError("one-shot elevated execution contract failed")
        services.server_elevation("release", session_id)
        root_opened = services.server_elevation("open_root_session", session_id)
        root_session_id = str(root_opened["session_id"])
        if (
            root_opened["effective_user"] != "root"
            or not root_opened["root_session"]
            or root_opened["parent_session_id"] != session_id
        ):
            raise AssertionError("root session identity contract is invalid")
        root_identity = services.server_exec(root_session_id, "id -u")
        if root_identity["output"].strip() != "0":
            raise AssertionError("dedicated root session did not retain effective UID zero")
        try:
            services.server_files("stat", root_session_id, path="/opt/app")
        except BrokerRemoteError as error:
            if error.code != "root_session_file_access_disabled":
                raise
        else:
            raise AssertionError("root session exposed structured file tools")
        services.server_elevation("close_root_session", root_session_id)
        root_session_id = None
        terminal = services.server_terminal("start", session_id, command="cat")
        cursor = int(terminal["output_cursor"])
        services.server_terminal("write", session_id, text="terminal-smoke\r\n")
        terminal_output = ""
        terminal_deadline = time.monotonic() + 3
        while "terminal-smoke" not in terminal_output and time.monotonic() < terminal_deadline:
            read = services.server_terminal(
                "read",
                session_id,
                cursor=cursor,
                timeout=0.5,
            )
            terminal_output += str(read["output"])
            cursor = int(read["next_cursor"])
        if "terminal-smoke" not in terminal_output:
            raise AssertionError("raw terminal output was not readable")
        services.server_terminal("close", session_id)
        rediscovered = services.server_connection("rediscover", session_id=session_id)
        if not rediscovered["rediscovered"] or rediscovered["command_retried"]:
            raise AssertionError("MCP session rediscovery contract is invalid")
        services.server_connection("close", session_id=session_id)
        session_id = None
        audit_text = "".join(
            path.read_text(encoding="utf-8") for path in sorted(audit_root.glob("*.jsonl"))
        )
        if synthetic_secret in audit_text or "alpha\\nbeta" in audit_text:
            raise AssertionError("audit log retained a secret or structured file content")
        if '"effective_user":"root"' not in audit_text or '"elevated":true' not in audit_text:
            raise AssertionError("audit log did not identify elevated operations")
        doctor_paths = InstallPaths(
            repository.path.parent,
            repository.path,
            manager.runtime_path,
            audit_root,
            runtime / "codex-home" / "config.toml",
        )
        doctor = Doctor(doctor_paths, manager).run("product-smoke")
        doctor_codes = {check.code for check in doctor.checks}
        if not doctor.succeeded or not {
            "profile_resolved",
            "connection",
            "bash",
            "remote_commands",
            "allowed_root",
            "effective_user",
        }.issubset(doctor_codes):
            raise AssertionError(f"Doctor remote preflight failed: {doctor.to_dict()}")
        with manager.connect() as broker:
            broker_pid = broker.request("broker.ping")["pid"]
            broker.request("broker.shutdown")
        manager.wait_for_launched_broker()
        return {
            "status": "passed",
            "broker_pid": broker_pid,
            "worker_pid": worker_pid,
            "checks": [
                "profile_open",
                "persistent_cwd",
                "persistent_virtual_environment",
                "exit_code",
                "redacted_audit_log",
                "doctor_remote_preflight",
                "structured_file_read_write_patch",
                "structured_file_large_transfer",
                "structured_file_hash_conflict",
                "structured_file_symlink_escape",
                "sudo_non_interactive_failure",
                "sudo_cache_acquire_status_release",
                "sudo_elevated_exec",
                "dedicated_root_session",
                "raw_terminal",
                "mcp_rediscovery_without_retry",
            ],
        }
    finally:
        with suppress(Exception):
            with BrokerClient(manager.runtime_path) as broker:
                if session_id is not None:
                    broker.request("session.close", {"session_id": session_id})
                if root_session_id is not None:
                    broker.request("session.close", {"session_id": root_session_id})
                broker.request("broker.shutdown")
            manager.wait_for_launched_broker()
        _stop_fixture()
        for path in (password_path, identity, public_key):
            path.unlink(missing_ok=True)
        if previous_local_app_data is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = previous_local_app_data


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    report = run(project_root)
    report_path = project_root / ".product-smoke-runtime" / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
