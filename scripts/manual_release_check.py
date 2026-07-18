from __future__ import annotations

import argparse
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from verify_release import REQUIRED_MANUAL_CHECKS

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
    checks: dict[str, bool] = {}
    print("Use only a disposable server/account. Never paste a secret into this program.")
    for code, prompt in PROMPTS.items():
        answer = input(f"PASS {prompt}? [y/N] ")
        checks[code] = answer.strip().casefold() in {"y", "yes"}
    document = {
        "schema_version": 1,
        "package_version": PACKAGE_VERSION,
        "source_revision": revision,
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "windows_version": platform.platform(),
        "python_version": platform.python_version(),
        "checks": checks,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return all(checks.values())


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
