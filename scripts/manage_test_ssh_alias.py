from __future__ import annotations

import argparse
import os
from pathlib import Path

from codex_serverops_mcp.setup.ssh_alias import (
    SshAliasSpec,
    apply_ssh_alias_change,
    plan_ssh_alias_change,
    validate_ssh_alias,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely add the disposable ServerOps SSH alias.")
    parser.add_argument("--alias", required=True)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--identity-file", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    user_profile = os.environ.get("USERPROFILE")
    if not user_profile:
        raise RuntimeError("USERPROFILE is unavailable")
    path = Path(user_profile) / ".ssh" / "config"
    spec = SshAliasSpec(
        args.alias,
        args.hostname,
        args.user,
        args.port,
        args.identity_file,
    )
    change = plan_ssh_alias_change(path, spec)
    print(change.preview)
    if not args.apply:
        print("Preview only; SSH config was not changed.")
        return
    result = apply_ssh_alias_change(path, change)
    validate_ssh_alias(result.config_path, change.spec)
    print(f"SSH alias applied to {result.config_path}")
    print(f"Byte-exact backup: {result.backup_path}")


if __name__ == "__main__":
    main()
