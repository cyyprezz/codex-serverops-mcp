from __future__ import annotations

import json
import shutil
from pathlib import Path

from codex_serverops_mcp.setup.keys import Ed25519KeyGenerator, OneShotSecretSource


def run(project_root: Path) -> dict[str, object]:
    runtime = (project_root / ".setup-keygen-smoke").resolve()
    if runtime.name != ".setup-keygen-smoke":
        raise RuntimeError("unexpected setup key smoke path")
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir()
    try:
        destination = runtime / "smoke_ed25519"
        generated = Ed25519KeyGenerator().generate(
            "setup-smoke",
            OneShotSecretSource(bytearray()),
            destination=destination,
        )
        if not generated.private_key_path.is_file() or not generated.public_key_path.is_file():
            raise AssertionError("setup key generation did not produce both key files")
        if not generated.public_key.startswith("ssh-ed25519 "):
            raise AssertionError("setup key generation did not produce an Ed25519 public key")
        return {
            "status": "passed",
            "checks": [
                "conpty_passphrase_prompts",
                "no_passphrase_process_argument",
                "ed25519_key_pair",
            ],
        }
    finally:
        shutil.rmtree(runtime, ignore_errors=True)


def main() -> None:
    print(json.dumps(run(Path(__file__).resolve().parents[1]), sort_keys=True))


if __name__ == "__main__":
    main()
