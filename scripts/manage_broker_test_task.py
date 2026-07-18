from __future__ import annotations

import argparse
import json
from pathlib import Path

from codex_serverops_mcp.broker.task_model import (
    BrokerTaskSpec,
    BrokerTaskStatus,
    wheel_broker_task_spec,
)
from codex_serverops_mcp.broker.task_scheduler import BrokerTaskController


def status_matches_spec(status: BrokerTaskStatus, spec: BrokerTaskSpec) -> bool:
    if not status.exists or not status.managed:
        return False
    if status.executable is None:
        return False
    return (
        Path(status.executable).resolve() == spec.executable.resolve()
        and status.arguments == spec.argument_line
    )


def run(action: str, wheel: Path | None, *, confirmed: bool) -> dict[str, object]:
    controller = BrokerTaskController.connect()
    current = controller.inspect()
    if action == "inspect":
        return _document(current)
    if wheel is None:
        raise ValueError(f"{action} requires the exact development wheel path")
    spec = wheel_broker_task_spec(wheel)
    if action == "install":
        if not confirmed:
            raise ValueError("install requires --yes")
        if current.exists:
            raise ValueError("refusing to replace an existing scheduled task")
        installed = controller.register(spec)
        if not status_matches_spec(installed, spec):
            raise RuntimeError("installed task does not match the requested development wheel")
        return {**_document(installed), "result": "installed"}
    if not status_matches_spec(current, spec):
        raise ValueError("managed task does not match the exact development wheel")
    if action == "start":
        if not confirmed:
            raise ValueError("start requires --yes")
        controller.start_if_installed()
        return {**_document(controller.inspect()), "result": "started"}
    if action == "remove":
        if not confirmed:
            raise ValueError("remove requires --yes")
        controller.remove()
        return {**_document(controller.inspect()), "result": "removed"}
    raise ValueError(f"unsupported action: {action}")


def _document(status: BrokerTaskStatus) -> dict[str, object]:
    return {
        "name": status.name,
        "exists": status.exists,
        "managed": status.managed,
        "running": status.running,
        "executable": status.executable,
        "arguments": status.arguments,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Guarded lifecycle helper for the disposable broker restart test task."
    )
    parser.add_argument("action", choices=("inspect", "install", "start", "remove"))
    parser.add_argument("wheel", type=Path, nargs="?")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.action, args.wheel, confirmed=args.yes), indent=2))


if __name__ == "__main__":
    main()
