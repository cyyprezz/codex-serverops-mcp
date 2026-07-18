from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from .auth_ui import request_visible_auth
from .broker_client import SpikeBrokerClient
from .keygen import generate_protected_ed25519_key
from .product_probe import probe_product_session_core
from .session import OutcomeUnknown, PromptProvider, SshSpikeSession

CONTAINER_NAME = "codex-serverops-spike"
IMAGE_NAME = "codex-serverops-spike:local"


def _run(arguments: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        check=True,
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _prepare_runtime(root: Path) -> None:
    root = root.resolve()
    if root.name != ".spike-runtime":
        raise RuntimeError("the spike runtime directory must be named .spike-runtime")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)


def _wait_for_port(port: int, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"local SSH fixture did not listen on port {port}")


def _start_container(runtime: Path) -> int:
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        capture_output=True,
        text=True,
        check=False,
    )
    password_mount = (
        f"type=bind,source={runtime / 'password'},"
        "target=/run/secrets/serverops_password,readonly"
    )
    key_mount = (
        f"type=bind,source={runtime / 'id_ed25519.pub'},"
        "target=/run/secrets/serverops_authorized_key,readonly"
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
            password_mount,
            "--mount",
            key_mount,
            IMAGE_NAME,
        ]
    )
    mapping = _run(["docker", "port", CONTAINER_NAME, "22/tcp"]).stdout.strip()
    port = int(mapping.rsplit(":", 1)[1])
    _wait_for_port(port)
    return port


def _stop_container() -> None:
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        capture_output=True,
        text=True,
        check=False,
    )


def _ssh_arguments(
    ssh: Path,
    port: int,
    known_hosts: Path,
    *,
    identity: Path | None = None,
) -> list[str]:
    arguments = [
        str(ssh),
        "-tt",
        "-p",
        str(port),
        "-l",
        "serverops",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "StrictHostKeyChecking=ask",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "NumberOfPasswordPrompts=1",
    ]
    if identity is None:
        arguments.extend(
            [
                "-o",
                "PreferredAuthentications=password",
                "-o",
                "PubkeyAuthentication=no",
            ]
        )
    else:
        arguments.extend(
            [
                "-i",
                str(identity),
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "PreferredAuthentications=publickey",
                "-o",
                "PasswordAuthentication=no",
            ]
        )
    arguments.extend(["127.0.0.1", "bash", "--noprofile", "--norc", "-i"])
    return arguments


def _provider(
    password: str,
    key_passphrase: str,
    events: list[str],
    *,
    visible: bool,
    port: int,
) -> PromptProvider:
    values = {
        "host_key": "yes",
        "password": password,
        "sudo_password": password,
        "key_passphrase": key_passphrase,
    }

    def provide(kind: str, prompt: str) -> str:
        if kind not in values:
            raise RuntimeError(f"unexpected prompt kind: {kind}")
        events.append(kind)
        if not visible:
            return values[kind]
        context: dict[str, object] = {
            "profile": "local-spike",
            "host": "127.0.0.1",
            "port": port,
            "user": "serverops",
        }
        if kind != "host_key":
            # This is a disposable local fixture only. The generated value travels
            # directly from this worker to its auth UI and is never audited.
            context["local_fixture_value_to_enter"] = values[kind]
        return request_visible_auth(kind, prompt, context)

    return provide


def _assert_result(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _remove_generated_secret_material(paths: tuple[Path, ...]) -> None:
    """Remove disposable spike credentials on success, failure, or cancellation."""
    for path in paths:
        path.unlink(missing_ok=True)


def _wait_for_file(path: Path, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise TimeoutError(f"expected runtime file was not created: {path.name}")


def _probe_broker_reconnect(
    runtime: Path,
    ssh_arguments: list[str],
) -> tuple[int, int]:
    environment = dict(os.environ)
    broker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "codex_serverops_mcp.spike.broker_process",
            "--runtime",
            str(runtime),
        ],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client: SpikeBrokerClient | None = None
    try:
        _wait_for_file(runtime / "broker.json")
        first_client = SpikeBrokerClient(runtime)
        opened = first_client.request(
            {
                "type": "open",
                "session_id": "sess_reconnect",
                "ssh_arguments": ssh_arguments,
                "password_file": str(runtime / "password"),
                "passphrase_file": str(runtime / "passphrase"),
            }
        )
        _assert_result(opened.get("status") == "ready", f"broker open failed: {opened}")
        worker_pid = int(opened["worker_pid"])
        _assert_result(worker_pid not in {os.getpid(), broker.pid}, "worker is not separate")
        changed = first_client.request(
            {"type": "exec", "session_id": "sess_reconnect", "command": "cd /opt/app"}
        )
        _assert_result(changed.get("cwd") == "/opt/app", "broker worker cd failed")
        first_client.disconnect()

        _assert_result(broker.poll() is None, "broker did not survive client disconnect")
        client = SpikeBrokerClient(runtime)
        sessions = client.request({"type": "list"})
        _assert_result(
            sessions.get("sessions") == ["sess_reconnect"],
            "new client did not rediscover the session",
        )
        current = client.request(
            {"type": "exec", "session_id": "sess_reconnect", "command": "pwd"}
        )
        _assert_result(current.get("output", "").strip() == "/opt/app", "state was lost")
        client.request({"type": "close", "session_id": "sess_reconnect"})
        client.request({"type": "shutdown"})
        client.connection.close()
        client = None
        broker.wait(timeout=10)
        return broker.pid, worker_pid
    finally:
        if client is not None:
            client.connection.close()
        if broker.poll() is None:
            broker.terminate()
            broker.wait(timeout=5)


def run_spike(project_root: Path, *, visible_auth: bool = False) -> dict[str, object]:
    runtime = project_root / ".spike-runtime"
    _prepare_runtime(runtime)
    ssh = Path(shutil.which("ssh.exe") or "")
    ssh_keygen = Path(shutil.which("ssh-keygen.exe") or "")
    if not ssh.exists() or not ssh_keygen.exists():
        raise RuntimeError("Windows OpenSSH client tools are unavailable")

    password = secrets.token_urlsafe(24)
    key_passphrase = secrets.token_urlsafe(24)
    password_path = runtime / "password"
    passphrase_path = runtime / "passphrase"
    identity = runtime / "id_ed25519"
    secret_paths = (
        password_path,
        passphrase_path,
        identity,
        identity.with_suffix(".pub"),
    )
    try:
        password_path.write_text(password, encoding="utf-8")
        passphrase_path.write_text(key_passphrase, encoding="utf-8")
        generate_protected_ed25519_key(ssh_keygen, identity, key_passphrase)
        port = _start_container(runtime)
    except BaseException:
        _remove_generated_secret_material(secret_paths)
        raise

    checks: dict[str, str] = {}
    events: list[str] = []
    provider = _provider(
        password, key_passphrase, events, visible=visible_auth, port=port
    )
    known_hosts = runtime / "known_hosts"
    try:
        password_session = SshSpikeSession()
        try:
            password_session.open(
                _ssh_arguments(ssh, port, known_hosts), provider, timeout=20
            )
            checks["password_authentication"] = "passed"
            checks["host_key_confirmation"] = "passed"

            first = password_session.execute("printf 'first-command'", provider)
            second = password_session.execute("printf 'second-command'", provider)
            _assert_result(
                first.exit_code == 0 and "first-command" in first.output, "first command"
            )
            _assert_result(
                second.exit_code == 0 and "second-command" in second.output,
                "second command",
            )
            checks["multiple_commands_same_shell"] = "passed"

            changed = password_session.execute("cd /opt/app", provider)
            current = password_session.execute("pwd", provider)
            _assert_result(changed.cwd == "/opt/app", "cd result cwd")
            _assert_result(current.output.strip() == "/opt/app", "persistent cwd")
            checks["persistent_cwd"] = "passed"

            password_session.execute(". /opt/app/.venv/bin/activate", provider)
            environment = password_session.execute(
                "python3 -c 'import sys; print(sys.prefix)'", provider
            )
            _assert_result(environment.output.strip() == "/opt/app/.venv", "persistent venv")
            checks["persistent_virtual_environment"] = "passed"

            terminal_state = password_session.execute("stty -a", provider)
            _assert_result("isig" in terminal_state.output, "remote terminal has ISIG disabled")

            holder: dict[str, object] = {}

            def run_long_command() -> None:
                try:
                    holder["result"] = password_session.execute("sleep 30", provider, timeout=10)
                except Exception as exc:  # retained for the main assertion
                    holder["error"] = exc

            command_thread = threading.Thread(target=run_long_command)
            command_thread.start()
            time.sleep(1)
            password_session.interrupt()
            command_thread.join(timeout=12)
            _assert_result(not command_thread.is_alive(), "Ctrl+C did not finish the command")
            _assert_result(
                "error" not in holder,
                f"interrupt failed: {holder.get('error')}\n{password_session.transcript_tail}",
            )
            interrupted = holder.get("result")
            _assert_result(
                getattr(interrupted, "exit_code", None) in {130, 128 + 2},
                "unexpected Ctrl+C exit status",
            )
            checks["running_process_and_ctrl_c"] = "passed"

            elevated = password_session.execute(
                "sudo -k; sudo -v; sudo -n id -u", provider, timeout=20
            )
            _assert_result(elevated.exit_code == 0, "sudo command failed")
            _assert_result(elevated.output.strip().endswith("0"), "sudo effective user")
            checks["sudo_prompt_same_session"] = "passed"
        finally:
            password_session.close()

        key_session = SshSpikeSession()
        try:
            key_session.open(
                _ssh_arguments(ssh, port, known_hosts, identity=identity), provider, timeout=20
            )
            result = key_session.execute("printf 'key-auth-ok'", provider)
            _assert_result(result.exit_code == 0 and "key-auth-ok" in result.output, "key auth")
            checks["protected_key_authentication"] = "passed"
        finally:
            key_session.close()

        product_known_hosts = runtime / "product_known_hosts"
        product_prompt_kinds = probe_product_session_core(
            _ssh_arguments(ssh, port, product_known_hosts),
            _ssh_arguments(ssh, port, product_known_hosts, identity=identity),
            password=password,
            key_passphrase=key_passphrase,
        )
        required_product_prompts = {
            "host_key",
            "password",
            "key_passphrase",
            "sudo_password",
        }
        _assert_result(
            required_product_prompts
            == {prompt_kind.value for prompt_kind in product_prompt_kinds},
            "product worker did not observe every authentication prompt",
        )
        checks["product_session_core"] = "passed"
        product_known_hosts.unlink(missing_ok=True)

        broker_pid, worker_pid = _probe_broker_reconnect(
            runtime,
            _ssh_arguments(ssh, port, known_hosts, identity=identity),
        )
        checks["worker_separate_from_mcp"] = "passed"
        checks["broker_survives_mcp_restart"] = "passed"

        lost_session = SshSpikeSession()
        lost_session.open(_ssh_arguments(ssh, port, known_hosts), provider, timeout=20)
        outcome: dict[str, object] = {}

        def run_uncertain_command() -> None:
            try:
                outcome["result"] = lost_session.execute("sleep 30", provider, timeout=15)
            except Exception as exc:
                outcome["error"] = exc

        lost_thread = threading.Thread(target=run_uncertain_command)
        lost_thread.start()
        time.sleep(1)
        _stop_container()
        lost_thread.join(timeout=10)
        _assert_result(not lost_thread.is_alive(), "disconnect was not detected")
        _assert_result(isinstance(outcome.get("error"), OutcomeUnknown), "outcome was not unknown")
        checks["network_disconnect"] = "passed"
        checks["outcome_unknown_without_retry"] = "passed"
        lost_session.close()
    finally:
        try:
            _stop_container()
        finally:
            _remove_generated_secret_material(secret_paths)

    required_events = {"host_key", "password", "key_passphrase", "sudo_password"}
    _assert_result(
        required_events.issubset(events),
        f"missing prompts: {required_events - set(events)}",
    )
    report = {
        "status": "passed",
        "visible_auth": visible_auth,
        "windows_version": os.sys.getwindowsversion().platform_version,
        "python_version": os.sys.version.split()[0],
        "ssh_path": str(ssh),
        "broker_pid_during_probe": broker_pid,
        "worker_pid_during_probe": worker_pid,
        "checks": checks,
        "prompt_kinds": sorted(set(events)),
        "product_prompt_kinds": sorted(prompt_kind.value for prompt_kind in product_prompt_kinds),
    }
    (runtime / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Windows SSH/ConPTY transport spike")
    parser.add_argument("--visible-auth", action="store_true")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    report = run_spike(args.project_root.resolve(), visible_auth=args.visible_auth)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
