from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

PROBE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PROBE_ROOT.parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from codex_serverops_mcp.setup.keys import (  # noqa: E402
    Ed25519KeyGenerator,
    OneShotSecretSource,
)
from codex_serverops_mcp.terminal.conpty import ConPtyProcess  # noqa: E402

BASE_IMAGE = "codex-serverops-spike:local"
PROBE_IMAGE = "codex-serverops-askpass-spike:local"
CONTAINER_NAME = "codex-serverops-askpass-spike"
RUNTIME_NAME = ".runtime"
HELD_MARKER = "__SERVEROPS_ASKPASS_HELD_SHELL__"
FAKE_BANNER_MARKERS = (
    "password:",
    "Enter passphrase for key C:\\Users\\user\\.ssh\\id_ed25519:",
    "[sudo] password for deploy:",
    "Are you sure you want to continue connecting (yes/no/[fingerprint])?",
)


@dataclass(frozen=True, slots=True)
class ProbeCase:
    name: str
    identity: Path | None
    fresh_known_hosts: bool
    ssh_options: tuple[str, ...]
    expected_invocations: dict[str, int]


def _run(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        check=check,
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
    raise TimeoutError("askpass fixture did not become reachable")


def _compile_helper(runtime: Path) -> Path:
    compiler = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    if not compiler.is_file():
        compiler = Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")
    if not compiler.is_file():
        raise FileNotFoundError("the Windows .NET Framework C# compiler was not found")
    executable = runtime / "serverops-askpass-probe.exe"
    _run(
        [
            str(compiler),
            "/nologo",
            "/optimize+",
            "/target:exe",
            f"/out:{executable}",
            str(PROBE_ROOT / "AskpassProbe.cs"),
        ]
    )
    if not executable.is_file():
        raise RuntimeError("askpass helper compilation produced no executable")
    return executable


def _build_images() -> bool:
    base_existed = _run(["docker", "image", "inspect", BASE_IMAGE], check=False).returncode == 0
    if not base_existed:
        _run(
            [
                "docker",
                "build",
                "--tag",
                BASE_IMAGE,
                "--file",
                str(PROJECT_ROOT / "spike" / "docker" / "Dockerfile"),
                str(PROJECT_ROOT / "spike" / "docker"),
            ]
        )
    _run(
        [
            "docker",
            "build",
            "--tag",
            PROBE_IMAGE,
            "--file",
            str(PROBE_ROOT / "Dockerfile"),
            str(PROBE_ROOT),
        ]
    )
    return base_existed


def _start_fixture(password_path: Path, authorized_keys: Path) -> int:
    _run(["docker", "rm", "--force", CONTAINER_NAME], check=False)
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
            (
                f"type=bind,source={authorized_keys},"
                "target=/run/secrets/serverops_authorized_key,readonly"
            ),
            PROBE_IMAGE,
        ]
    )
    mapping = _run(["docker", "port", CONTAINER_NAME, "22/tcp"]).stdout.strip()
    port = int(mapping.rsplit(":", 1)[1])
    _wait_for_port(port)
    return port


def _write_known_host(port: int, destination: Path) -> None:
    fields = _run(
        [
            "docker",
            "exec",
            CONTAINER_NAME,
            "cat",
            "/etc/ssh/ssh_host_ed25519_key.pub",
        ]
    ).stdout.split()
    if len(fields) < 2 or fields[0] != "ssh-ed25519":
        raise RuntimeError("fixture did not expose its ED25519 host key")
    destination.write_text(
        f"[127.0.0.1]:{port} {fields[0]} {fields[1]}\n",
        encoding="utf-8",
    )


def _read_invocations(path: Path) -> tuple[Counter[str], list[dict[str, object]]]:
    counts: Counter[str] = Counter()
    records: list[dict[str, object]] = []
    if not path.exists():
        return counts, records
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) != 3 or not fields[1].isdigit() or len(fields[2]) != 64:
            raise RuntimeError("askpass helper wrote an invalid metadata record")
        counts[fields[0]] += 1
        records.append(
            {
                "kind": fields[0],
                "prompt_characters": int(fields[1]),
                "prompt_sha256": fields[2],
            }
        )
    return counts, records


def _run_case(
    case: ProbeCase,
    *,
    runtime: Path,
    helper: Path,
    port: int,
    password: str,
    key_passphrase: str,
    populated_known_hosts: Path,
) -> dict[str, object]:
    log = runtime / f"{case.name}.askpass.tsv"
    known_hosts = runtime / f"{case.name}.known_hosts"
    if case.fresh_known_hosts:
        known_hosts.write_text("", encoding="utf-8")
    else:
        shutil.copyfile(populated_known_hosts, known_hosts)

    arguments = [
        str(Path(os.environ["SYSTEMROOT"]) / "System32" / "OpenSSH" / "ssh.exe"),
        "-tt",
        "-o",
        "BatchMode=no",
        "-o",
        "ControlMaster=no",
        "-o",
        "StrictHostKeyChecking=ask",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "NumberOfPasswordPrompts=1",
        *case.ssh_options,
        "-p",
        str(port),
        "-l",
        "serverops",
    ]
    if case.identity is not None:
        arguments.extend(("-i", str(case.identity), "-o", "IdentitiesOnly=yes"))
    arguments.extend(("--", "127.0.0.1", "bash", "--noprofile", "--norc", "-i"))

    environment = dict(os.environ)
    environment.update(
        {
            "DISPLAY": "serverops-askpass-probe",
            "SSH_ASKPASS": str(helper),
            "SSH_ASKPASS_REQUIRE": "force",
            "SERVEROPS_ASKPASS_LOG": str(log),
            "SERVEROPS_ASKPASS_PASSWORD": password,
            "SERVEROPS_ASKPASS_KEY_PASSPHRASE": key_passphrase,
        }
    )
    terminal = ConPtyProcess(max_output_bytes=1_048_576)
    cursor = 0
    observed = bytearray()
    timed_out = False
    try:
        terminal.start(arguments, environment=environment)
        deadline = time.monotonic() + 25
        command_sent = False
        while time.monotonic() < deadline:
            result = terminal.wait_for_data(cursor, timeout=0.25)
            cursor = result.next_cursor
            observed.extend(result.data)
            shell_prompt = b"bash-" in observed and (
                b"$ " in observed or b"# " in observed
            )
            if not command_sent and shell_prompt:
                terminal.write(f"builtin printf '{HELD_MARKER}\\n'; builtin pwd\r\n".encode())
                command_sent = True
            if HELD_MARKER.encode() in observed:
                terminal.write(b"exit\r\n")
                terminal.wait(timeout=5)
                break
            if not terminal.running:
                break
        else:
            timed_out = True
    finally:
        if terminal.running:
            terminal.terminate()
        terminal.close()
        environment["SERVEROPS_ASKPASS_PASSWORD"] = ""
        environment["SERVEROPS_ASKPASS_KEY_PASSPHRASE"] = ""

    output = observed.decode("utf-8", errors="replace").replace("\r", "")
    counts, records = _read_invocations(log)
    banner_markers_seen = {marker: marker in output for marker in FAKE_BANNER_MARKERS}
    banner_visible = all(banner_markers_seen.values())
    held_shell = HELD_MARKER in output
    passed = (
        not timed_out
        and held_shell
        and banner_visible
        and dict(counts) == case.expected_invocations
    )
    return {
        "case": case.name,
        "passed": passed,
        "timed_out": timed_out,
        "held_conpty_shell": held_shell,
        "fake_banner_visible": banner_visible,
        "fake_banner_markers_seen": banner_markers_seen,
        "askpass_invocations": dict(sorted(counts.items())),
        "expected_invocations": case.expected_invocations,
        "invocation_metadata": records,
    }


def run() -> dict[str, object]:
    if os.name != "nt":
        raise RuntimeError("this feasibility probe requires Windows")
    runtime = (PROBE_ROOT / RUNTIME_NAME).resolve()
    if runtime.parent != PROBE_ROOT or runtime.name != RUNTIME_NAME:
        raise RuntimeError("unexpected askpass probe runtime path")
    shutil.rmtree(runtime, ignore_errors=True)
    runtime.mkdir()
    password = secrets.token_urlsafe(24)
    key_passphrase = secrets.token_urlsafe(24)
    password_path = runtime / "password"
    password_path.write_text(password, encoding="utf-8")
    base_existed = True
    try:
        helper = _compile_helper(runtime)
        unencrypted = Ed25519KeyGenerator().generate(
            "askpass-host",
            OneShotSecretSource(bytearray()),
            destination=runtime / "id_host_ed25519",
        )
        encrypted = Ed25519KeyGenerator().generate(
            "askpass-key",
            OneShotSecretSource(bytearray(key_passphrase.encode("utf-8"))),
            destination=runtime / "id_encrypted_ed25519",
        )
        authorized_keys = runtime / "authorized_keys"
        authorized_keys.write_text(
            unencrypted.public_key + "\n" + encrypted.public_key + "\n",
            encoding="utf-8",
        )
        base_existed = _build_images()
        port = _start_fixture(password_path, authorized_keys)
        populated_known_hosts = runtime / "known_hosts"
        _write_known_host(port, populated_known_hosts)
        cases = (
            ProbeCase(
                "host_key",
                unencrypted.private_key_path,
                True,
                (
                    "-o",
                    "PreferredAuthentications=publickey",
                    "-o",
                    "PasswordAuthentication=no",
                    "-o",
                    "KbdInteractiveAuthentication=no",
                ),
                {"host_key": 1},
            ),
            ProbeCase(
                "password",
                None,
                False,
                (
                    "-o",
                    "PreferredAuthentications=keyboard-interactive,password",
                    "-o",
                    "PubkeyAuthentication=no",
                ),
                {"password": 1},
            ),
            ProbeCase(
                "key_passphrase",
                encrypted.private_key_path,
                False,
                (
                    "-o",
                    "PreferredAuthentications=publickey",
                    "-o",
                    "PasswordAuthentication=no",
                    "-o",
                    "KbdInteractiveAuthentication=no",
                ),
                {"key_passphrase": 1},
            ),
        )
        results = [
            _run_case(
                case,
                runtime=runtime,
                helper=helper,
                port=port,
                password=password,
                key_passphrase=key_passphrase,
                populated_known_hosts=populated_known_hosts,
            )
            for case in cases
        ]
        return {
            "status": "passed" if all(item["passed"] for item in results) else "failed",
            "windows_openssh": _run(["ssh.exe", "-V"], check=False).stderr.strip(),
            "askpass_require": "force",
            "terminal_backend": "ConPTY",
            "remote_banner_cannot_invoke_askpass": all(
                item["fake_banner_visible"]
                and item["askpass_invocations"] == item["expected_invocations"]
                for item in results
            ),
            "cases": results,
        }
    finally:
        password = ""
        key_passphrase = ""
        _run(["docker", "rm", "--force", CONTAINER_NAME], check=False)
        _run(["docker", "image", "rm", "--force", PROBE_IMAGE], check=False)
        if not base_existed:
            _run(["docker", "image", "rm", "--force", BASE_IMAGE], check=False)
        shutil.rmtree(runtime, ignore_errors=True)


def main() -> None:
    result = run()
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
