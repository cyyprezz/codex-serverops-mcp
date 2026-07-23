from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from codex_serverops_mcp import PACKAGE_VERSION
from codex_serverops_mcp.broker.client import BrokerClient
from codex_serverops_mcp.broker.errors import BrokerUnavailable
from codex_serverops_mcp.broker.task_model import (
    BrokerTaskSpec,
    production_broker_task_spec,
)
from codex_serverops_mcp.broker.task_scheduler import (
    BrokerTaskController,
    BrokerTaskError,
)

from .checks import LocalChecker
from .codex_config import apply_codex_config_change, plan_codex_config_change
from .doctor import Doctor
from .errors import InstallerError
from .model import CheckLevel, CheckReport
from .paths import InstallPaths
from .setup import prepare_local_install, remove_local_data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="serverops-install",
        description="Prepare, configure and diagnose ServerOps on Windows.",
    )
    parser.add_argument("--version", action="version", version=PACKAGE_VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser(
        "setup",
        help="Prepare current-user state and optionally the persistent broker task.",
    )
    setup.add_argument("--broker-task", action="store_true")
    setup.add_argument("--apply", action="store_true")
    setup.add_argument("--yes", action="store_true")
    check = commands.add_parser("check", help="Check local installation prerequisites.")
    check.add_argument("--client", choices=("core", "codex", "claude", "all"), default="codex")
    check.add_argument("--json", action="store_true")
    doctor = commands.add_parser("doctor", help="Run local and optional remote diagnostics.")
    doctor.add_argument("--profile")
    doctor.add_argument(
        "--client", choices=("core", "codex", "claude", "all"), default="codex"
    )
    doctor.add_argument("--json", action="store_true")
    codex = commands.add_parser(
        "codex-config",
        help="Preview or explicitly apply the user-wide Codex MCP block.",
    )
    codex.add_argument("--apply", action="store_true")
    codex.add_argument("--yes", action="store_true")
    codex.add_argument("--remove", action="store_true")
    codex.add_argument(
        "--development-wheel",
        type=Path,
        help="Temporarily pin Codex to an exact local development wheel in offline mode.",
    )
    codex.add_argument(
        "--development-python",
        type=Path,
        help="Exact Python 3.12 executable used with --development-wheel.",
    )
    commands.add_parser("update", help="Migrate local state for this exact package version.")
    uninstall = commands.add_parser(
        "uninstall",
        help="Preview or remove the managed Codex block; local data is preserved by default.",
    )
    uninstall.add_argument("--apply", action="store_true")
    uninstall.add_argument("--yes", action="store_true")
    uninstall.add_argument("--remove-data", action="store_true")
    return parser


def run(arguments: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(arguments)
    try:
        paths = InstallPaths.from_environment()
        if args.command == "setup":
            if (args.apply or args.yes) and not args.broker_task:
                raise InstallerError("--apply and --yes require --broker-task for setup")
            _validate_confirmation_flags(args.apply, args.yes)
            result = prepare_local_install(paths)
            print(f"Local ServerOps state prepared at {paths.app_dir}")
            if result["config_migrated"]:
                print("Profile configuration was migrated atomically.")
            if args.broker_task:
                _configure_broker_task(apply=args.apply, assume_yes=args.yes)
            print("AI client configuration was not changed.")
            print("For direct Codex setup, run: serverops-install codex-config")
            return 0
        if args.command == "check":
            prepare_local_install(paths)
            return _report(
                LocalChecker(paths).run(include_broker=False, client=args.client),
                as_json=args.json,
            )
        if args.command == "doctor":
            prepare_local_install(paths)
            return _report(
                Doctor(paths).run(args.profile, client=args.client), as_json=args.json
            )
        if args.command == "codex-config":
            _validate_confirmation_flags(args.apply, args.yes)
            change = plan_codex_config_change(
                paths.codex_config_file,
                PACKAGE_VERSION,
                remove=args.remove,
                development_wheel=args.development_wheel,
                development_python=args.development_python,
            )
            _print_preview(change.preview)
            if not args.apply:
                print("Preview only; Codex configuration was not changed.")
                return 0
            _confirm_or_raise(args.yes)
            apply_codex_config_change(paths.codex_config_file, change)
            print("Codex configuration updated atomically. Restart Codex to load the change.")
            return 0
        if args.command == "update":
            result = prepare_local_install(paths)
            print(f"Local state is compatible with package {PACKAGE_VERSION}.")
            if result["config_migrated"]:
                print("Profile configuration was migrated atomically.")
            print("AI client configuration was not changed.")
            return _report(
                LocalChecker(paths).run(include_broker=False, client="core"),
                as_json=False,
            )
        if args.command == "uninstall":
            _validate_confirmation_flags(args.apply, args.yes)
            change = plan_codex_config_change(
                paths.codex_config_file,
                PACKAGE_VERSION,
                remove=True,
            )
            _print_preview(change.preview)
            task_controller = BrokerTaskController.connect()
            task_status = task_controller.inspect()
            if task_status.exists and task_status.managed:
                print(f"Also remove managed current-user task: {task_status.name}")
            elif task_status.exists:
                raise InstallerError(
                    f"scheduled task is not managed by ServerOps: {task_status.name}"
                )
            if args.remove_data:
                print(f"Also remove local profiles, runtime and audit data at {paths.app_dir}")
            if not args.apply:
                print("Preview only; nothing was removed.")
                return 0
            _confirm_or_raise(args.yes)
            _shutdown_broker(paths)
            task_controller.remove()
            apply_codex_config_change(paths.codex_config_file, change)
            if args.remove_data:
                remove_local_data(paths)
            print("Managed Codex configuration removed. Restart Codex to finish uninstalling.")
            return 0
        raise InstallerError(f"unsupported installer command: {args.command}")
    except (BrokerTaskError, InstallerError, OSError, ValueError) as error:
        print(f"serverops-install: {error}", file=sys.stderr)
        return 1


def _report(report: CheckReport, *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        labels = {
            CheckLevel.PASS: "PASS",
            CheckLevel.WARNING: "WARN",
            CheckLevel.FAIL: "FAIL",
        }
        for check in report.checks:
            print(f"[{labels[check.level]}] {check.code}: {check.message}")
        print(f"Doctor status: {report.status}")
    return 0 if report.succeeded else 1


def _print_preview(preview: str) -> None:
    print("Proposed user-wide Codex configuration change:")
    print(preview)


def _validate_confirmation_flags(apply: bool, assume_yes: bool) -> None:
    if assume_yes and not apply:
        raise InstallerError("--yes is valid only together with --apply")


def _confirm_or_raise(assume_yes: bool) -> None:
    if assume_yes:
        return
    answer = input("Apply this user-wide change? [y/N] ")
    if answer.strip().casefold() not in {"y", "yes"}:
        raise InstallerError("the user-wide change was not applied")


def _shutdown_broker(paths: InstallPaths) -> None:
    try:
        with BrokerClient(paths.runtime_dir) as client:
            client.request("broker.shutdown")
    except BrokerUnavailable:
        return


def _configure_broker_task(*, apply: bool, assume_yes: bool) -> None:
    spec = production_broker_task_spec()
    controller = BrokerTaskController.connect()
    current = controller.inspect()
    action = _task_action(spec)
    print(f"Proposed current-user broker task: {controller.task_name}")
    print(f"Action: {action}")
    print("Logon: current interactive user; password stored: no; admin rights: no")
    if current.exists and not current.managed:
        raise InstallerError(
            f"scheduled task name is occupied by an unmanaged task: {current.name}"
        )
    if not apply:
        print("Preview only; Windows Task Scheduler was not changed.")
        return
    _confirm_or_raise(assume_yes)
    installed = controller.register(spec)
    if not installed.exists or not installed.managed:
        raise InstallerError("broker task registration could not be verified")
    print(f"Managed broker task installed: {installed.name}")


def _task_action(spec: BrokerTaskSpec) -> str:
    return f'"{spec.executable}" {spec.argument_line}'


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
