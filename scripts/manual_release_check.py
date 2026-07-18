from __future__ import annotations

import argparse
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from verify_release import (
    REQUIRED_EXTERNAL_SCENARIOS,
    REQUIRED_MANUAL_CHECKS,
    VERIFIED_SCENARIO_STATUSES,
)

from codex_serverops_mcp import PACKAGE_VERSION

PROMPTS = {
    "password_window": "Password auth succeeded only through the separate masked window",
    "key_passphrase_window": "Encrypted-key login succeeded through the passphrase window",
    "host_key_window": "Unknown host key required an explicit separate-window decision",
    "sudo_window_and_cache": "sudo window, cache reuse and sudo -k behaved as documented",
    "auth_cancel_and_timeout": "Auth close/cancel/timeout returned controlled non-secret states",
    "setup_direct_and_alias_profiles": "Setup UI added and tested direct and SSH-alias profiles",
    "setup_existing_and_generated_keys": "Existing and new Ed25519 key workflows passed",
    "public_key_install_and_fresh_login": "Only public key was installed and fresh login passed",
    "mcp_restart_and_session_rediscovery": "Broker session survived and was rediscovered",
    "interrupt_disconnect_and_no_retry": (
        "Interrupt, disconnect, outcome_unknown and no retry passed"
    ),
    "spoofed_remote_prompt_rejected": (
        "Remote prompt-like output could not open an unauthorized local auth window"
    ),
    "shell_state_corruption_detected": (
        "Corrupting shell states completed safely or produced controlled session loss"
    ),
    "failed_key_transition_reports_remote_key_state": (
        "Failed key transitions reported possible remote key presence and local rollback state"
    ),
    "profile_mutations_audited": (
        "Profile, key-generation and key-installation events produced non-secret audit evidence"
    ),
}
REMOTE_ENVIRONMENT_PROMPTS = {
    "ubuntu_version": "Ubuntu version (for example 24.04.4 LTS)",
    "remote_openssh_version": "Remote OpenSSH version",
    "sudo_version": "Remote sudo version",
    "bash_version": "Remote Bash version",
}
STATUS_CHOICES = {
    "a": "automated",
    "m": "manually_verified",
    "n": "not_tested",
    "x": "not_applicable",
}


def run(output: Path) -> bool:
    if set(PROMPTS) != REQUIRED_MANUAL_CHECKS:
        raise RuntimeError("manual checklist differs from the release contract")
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    environment = {
        "windows_version": platform.platform(),
        "python_version": platform.python_version(),
        "uv_version": _command_version(["uv", "--version"]),
        "windows_openssh_version": _command_version(["ssh", "-V"]),
    }
    print("Record neutral version strings only; never enter a host, account or credential.")
    for code, prompt in REMOTE_ENVIRONMENT_PROMPTS.items():
        environment[code] = _required_answer(prompt)
    checks: dict[str, bool] = {}
    print("Use only a disposable server/account. Never paste a secret into this program.")
    for code, prompt in PROMPTS.items():
        answer = input(f"PASS {prompt}? [y/N] ")
        checks[code] = answer.strip().casefold() in {"y", "yes"}
    scenarios: dict[str, str] = {}
    print("Scenario status: [a]utomated [m]anually verified [n]ot tested not [x]applicable")
    for code in sorted(REQUIRED_EXTERNAL_SCENARIOS):
        answer = input(f"STATUS {code.replace('_', ' ')}? [a/m/n/x] ")
        scenarios[code] = STATUS_CHOICES.get(answer.strip().casefold(), "not_tested")
    document = {
        "schema_version": 2,
        "package_version": PACKAGE_VERSION,
        "source_revision": revision,
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "environment": environment,
        "checks": checks,
        "external_scenarios": scenarios,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return all(checks.values()) and all(
        status in VERIFIED_SCENARIO_STATUSES for status in scenarios.values()
    )


def _command_version(arguments: list[str]) -> str:
    completed = subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    value = (completed.stdout or completed.stderr).strip().splitlines()
    if completed.returncode != 0 or not value:
        raise RuntimeError(f"could not capture version from {arguments[0]}")
    return value[0][:512]


def _required_answer(prompt: str) -> str:
    value = input(f"{prompt}: ").strip()
    if not value or len(value) > 512 or any(ord(character) < 32 for character in value):
        raise ValueError(f"{prompt} is required and must be a single bounded line")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/release-evidence.json"),
    )
    args = parser.parse_args()
    passed = run(args.output)
    print(f"Release evidence written to {args.output}")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
