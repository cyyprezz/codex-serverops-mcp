from __future__ import annotations

import argparse
import json
import re
import secrets
import shlex
import time
from contextlib import suppress

from codex_serverops_mcp.application import ApplicationServices
from codex_serverops_mcp.broker.client import BrokerClient
from codex_serverops_mcp.broker.errors import BrokerRemoteError, BrokerUnavailable

TOKEN = re.compile(r"^[a-f0-9]{12}$")
UNIT = re.compile(r"^serverops-cut-[a-f0-9]{12}$")
INTERRUPT_MARKER = "serverops-interrupt-started"
AFTER_INTERRUPT_MARKER = "serverops-after-interrupt"
NETWORK_COMMAND = (
    "i=0; while [ \"$i\" -lt 60 ]; do "
    "printf 'serverops-network-probe-%s\\n' \"$i\"; "
    "i=$((i + 1)); sleep 1; done"
)


def build_firewall_schedule_command(token: str) -> str:
    if not TOKEN.fullmatch(token):
        raise ValueError("firewall test token must be twelve lowercase hex characters")
    root_script = (
        "cleanup() { /usr/sbin/iptables -D INPUT -p tcp "
        '-s "$1" --sport "$2" -d "$3" --dport "$4" '
        "-j REJECT --reject-with tcp-reset >/dev/null 2>&1 || true; }\n"
        "trap cleanup EXIT TERM INT\n"
        "/usr/sbin/iptables -I INPUT 1 -p tcp "
        '-s "$1" --sport "$2" -d "$3" --dport "$4" '
        "-j REJECT --reject-with tcp-reset\n"
        "sleep 10\n"
    )
    return (
        "set -- $SSH_CONNECTION; "
        "test \"$#\" -eq 4; "
        "case \"$1$3\" in ''|*[!0-9.]*) exit 91;; esac; "
        "case \"$2$4\" in ''|*[!0-9]*) exit 92;; esac; "
        "sudo -n systemd-run --quiet --no-block --collect "
        f"--unit=serverops-cut-{token} --on-active=5s "
        "--timer-property=AccuracySec=100ms --property=RuntimeMaxSec=25s -- "
        f"/bin/bash -c {shlex.quote(root_script)} serverops-cut "
        '"$1" "$2" "$3" "$4"; '
        "printf 'scheduled'"
    )


def run(profile_name: str) -> dict[str, object]:
    if not profile_name.endswith("-test"):
        raise ValueError("interrupt/disconnect check requires an explicit test profile")
    services = ApplicationServices.create()
    session_id: str | None = None
    checks: list[str] = []
    try:
        opened = services.server_connection("open", profile_name=profile_name)
        session_id = str(opened["session_id"])
        _check_real_interrupt(services, session_id)
        checks.append("real_ctrl_c_and_same_shell_recovery")

        acquired = ensure_elevation(services, session_id)
        _expect(acquired.get("active") is True, "sudo elevation was not acquired")
        ufw = services.server_elevation(
            "exec",
            session_id,
            command="LC_ALL=C /usr/sbin/ufw status | sed -n '1p'",
        )
        ufw_line = str(ufw.get("output", "")).strip().casefold()
        _expect(ufw_line in {"status: active", "status: inactive"}, "UFW status was invalid")
        checks.append(f"ufw_{ufw_line.removeprefix('status: ')}")

        token = secrets.token_hex(6)
        unit = f"serverops-cut-{token}"
        scheduled = services.server_exec(
            session_id,
            build_firewall_schedule_command(token),
        )
        _expect(
            scheduled.get("status") == "completed"
            and scheduled.get("exit_code") == 0
            and str(scheduled.get("output", "")).strip() == "scheduled",
            "self-reverting connection-specific firewall unit was not scheduled",
        )
        checks.append("connection_specific_self_reverting_rule_scheduled")

        try:
            services.server_exec(session_id, NETWORK_COMMAND, timeout=30)
        except BrokerRemoteError as error:
            _expect(error.code == "outcome_unknown", "disconnect returned the wrong error code")
        else:
            raise AssertionError("network command completed despite the scheduled connection reset")
        rediscovery = services.server_connection("rediscover", session_id=session_id)
        _expect(
            rediscovery.get("state") == "lost"
            and rediscovery.get("rediscovered") is True
            and rediscovery.get("command_retried") is False,
            "lost-session rediscovery did not preserve the no-retry contract",
        )
        checks.append("outcome_unknown_lost_and_command_not_retried")
        services.server_connection("close", session_id=session_id)
        session_id = None
        time.sleep(12)
        _verify_firewall_cleanup(services, profile_name, unit)
        checks.append("firewall_cleanup_confirmed")
        return {
            "status": "passed",
            "profile": profile_name,
            "checks": checks,
            "persistent_ufw_configuration_changed": False,
        }
    finally:
        if session_id is not None:
            with suppress(Exception):
                services.server_elevation("release", session_id)
            with suppress(Exception):
                services.server_connection("close", session_id=session_id)
        _shutdown_idle_broker()


def diagnose_unit(profile_name: str, unit: str) -> dict[str, object]:
    if not profile_name.endswith("-test") or not UNIT.fullmatch(unit):
        raise ValueError("unit diagnosis requires an exact test profile and unit name")
    services = ApplicationServices.create()
    session_id: str | None = None
    try:
        opened = services.server_connection("open", profile_name=profile_name)
        session_id = str(opened["session_id"])
        ensure_elevation(services, session_id)
        command = (
            f"systemctl show {shlex.quote(unit)}.service --no-pager "
            "-p LoadState -p ActiveState -p SubState -p Result "
            "-p ExecMainCode -p ExecMainStatus || true; "
            "printf '\\n[journal]\\n'; "
            f"journalctl -u {shlex.quote(unit)}.service -n 20 --no-pager -o cat || true"
        )
        result = services.server_elevation("exec", session_id, command=command)
        return {
            "status": "diagnosed",
            "profile": profile_name,
            "unit": unit,
            "output": result.get("output", ""),
            "mutated_remote_state": False,
        }
    finally:
        if session_id is not None:
            with suppress(Exception):
                services.server_elevation("release", session_id)
            with suppress(Exception):
                services.server_connection("close", session_id=session_id)
        _shutdown_idle_broker()


def ensure_elevation(
    services: ApplicationServices,
    session_id: str,
) -> dict[str, object]:
    status = services.server_elevation("status", session_id)
    if status.get("active") is True:
        return status
    return services.server_elevation("acquire", session_id)


def _verify_firewall_cleanup(
    services: ApplicationServices,
    profile_name: str,
    unit: str,
) -> None:
    if not UNIT.fullmatch(unit):
        raise ValueError("firewall cleanup requires an exact test unit name")
    session_id: str | None = None
    try:
        opened = services.server_connection("open", profile_name=profile_name)
        session_id = str(opened["session_id"])
        quoted = shlex.quote(unit)
        result = services.server_exec(
            session_id,
            (
                f"systemctl list-units {quoted}.service {quoted}.timer "
                "--all --no-legend --no-pager; "
                f"systemctl list-timers {quoted}.timer --all --no-legend --no-pager"
            ),
        )
        _expect(
            result.get("exit_code") == 0 and not str(result.get("output", "")).strip(),
            "self-reverting firewall unit or timer remained after cleanup",
        )
    finally:
        if session_id is not None:
            with suppress(Exception):
                services.server_connection("close", session_id=session_id)


def _check_real_interrupt(services: ApplicationServices, session_id: str) -> None:
    started = services.server_terminal(
        "start",
        session_id,
        command=f"printf '{INTERRUPT_MARKER}\\n'; sleep 30",
    )
    cursor = int(started["output_cursor"])
    output = ""
    deadline = time.monotonic() + 5
    while INTERRUPT_MARKER not in output and time.monotonic() < deadline:
        read = services.server_terminal("read", session_id, cursor=cursor, timeout=0.5)
        output += str(read["output"])
        cursor = int(read["next_cursor"])
    _expect(INTERRUPT_MARKER in output, "interactive command did not start")
    services.server_terminal("interrupt", session_id)
    closed = services.server_terminal("close", session_id, timeout=5)
    _expect(closed.get("state") == "ready", "Ctrl+C did not restore the ready shell")
    after = services.server_exec(session_id, f"printf '{AFTER_INTERRUPT_MARKER}'")
    _expect(
        _output_matches_marker(after, AFTER_INTERRUPT_MARKER),
        "same shell did not execute after Ctrl+C",
    )


def _output_matches_marker(result: dict[str, object], marker: str) -> bool:
    return result.get("exit_code") == 0 and str(result.get("output", "")).strip() == marker


def _shutdown_idle_broker() -> None:
    try:
        with BrokerClient() as client:
            if client.request("session.list").get("sessions"):
                return
            client.request("broker.shutdown")
    except BrokerUnavailable:
        pass


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--diagnose-unit")
    args = parser.parse_args()
    result = (
        diagnose_unit(args.profile, args.diagnose_unit)
        if args.diagnose_unit
        else run(args.profile)
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
