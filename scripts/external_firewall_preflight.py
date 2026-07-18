from __future__ import annotations

import argparse
import json
from contextlib import suppress

from codex_serverops_mcp.application import ApplicationServices

if __package__:
    from ._external_runtime import isolated_external_services
else:
    from _external_runtime import isolated_external_services

TOOLS = ("ufw", "iptables", "nft", "systemd-run")
PREFLIGHT_COMMAND = """for name in ufw iptables nft systemd-run; do
  path=$(command -v -- "$name" 2>/dev/null || true)
  printf '%s=%s\\n' "$name" "$path"
done
"""


def parse_tool_paths(output: str) -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    for line in output.splitlines():
        if not line:
            continue
        name, separator, path = line.partition("=")
        if not separator or name not in TOOLS or name in found:
            raise ValueError("firewall preflight returned an invalid tool row")
        if path and not path.startswith("/"):
            raise ValueError("firewall preflight returned a non-absolute tool path")
        found[name] = path or None
    if set(found) != set(TOOLS):
        raise ValueError("firewall preflight did not return every expected tool")
    return found


def run(profile_name: str) -> dict[str, object]:
    if not profile_name.endswith("-test"):
        raise ValueError("firewall preflight requires an explicit test profile")
    with isolated_external_services() as services:
        return _run(profile_name, services)


def _run(profile_name: str, services: ApplicationServices) -> dict[str, object]:
    session_id: str | None = None
    try:
        opened = services.server_connection("open", profile_name=profile_name)
        session_id = str(opened["session_id"])
        result = services.server_exec(session_id, PREFLIGHT_COMMAND)
        if result.get("status") != "completed" or result.get("exit_code") != 0:
            raise RuntimeError("read-only firewall preflight command did not complete")
        tools = parse_tool_paths(str(result.get("output", "")))
        return {
            "status": "passed",
            "profile": profile_name,
            "tools": tools,
            "mutated_remote_state": False,
            "used_sudo": False,
        }
    finally:
        if session_id is not None:
            with suppress(Exception):
                services.server_connection("close", session_id=session_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.profile), indent=2))


if __name__ == "__main__":
    main()
