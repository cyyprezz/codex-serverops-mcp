from __future__ import annotations

import argparse
from collections.abc import Callable

from .keys import Ed25519KeyGenerator
from .model import SetupRecord, SetupStatus
from .operations import ProfileSetupOperations
from .store import SetupRequestStore
from .window import SetupWindow

WindowFactory = Callable[
    [SetupRecord, ProfileSetupOperations, Ed25519KeyGenerator],
    SetupWindow,
]


def run_setup_app(
    request_id: str,
    *,
    store: SetupRequestStore | None = None,
    operations: ProfileSetupOperations | None = None,
    key_generator: Ed25519KeyGenerator | None = None,
    window_factory: WindowFactory = SetupWindow,
) -> int:
    request_store = store or SetupRequestStore()
    try:
        record = request_store.expire_if_needed(request_id)
        if record.status is not SetupStatus.PENDING:
            return 3
        running = request_store.update(request_id, SetupStatus.RUNNING)
        window = window_factory(
            running,
            operations or ProfileSetupOperations.create(),
            key_generator or Ed25519KeyGenerator(),
        )
        status, result, message = window.run()
        request_store.update(request_id, status, result=result, message=message)
        return 0 if status in {
            SetupStatus.CREATED,
            SetupStatus.UPDATED,
            SetupStatus.REMOVED,
            SetupStatus.TESTED,
        } else 2
    except Exception:
        try:
            current = request_store.load(request_id)
            if not current.status.terminal:
                request_store.update(
                    request_id,
                    SetupStatus.FAILED,
                    message="The local setup program failed before completion.",
                )
        except Exception:
            pass
        return 3


def main() -> None:
    from codex_serverops_mcp.bootstrap import ensure_local_state

    parser = argparse.ArgumentParser()
    parser.add_argument("--request-id", required=True)
    args = parser.parse_args()
    ensure_local_state()
    raise SystemExit(run_setup_app(args.request_id))


if __name__ == "__main__":
    main()
