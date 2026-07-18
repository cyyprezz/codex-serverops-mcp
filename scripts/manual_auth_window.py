from __future__ import annotations

import argparse
import json

from codex_serverops_mcp.auth.errors import AuthenticationError
from codex_serverops_mcp.auth.model import AuthTargetContext
from codex_serverops_mcp.ssh.prompts import PromptEvent, PromptKind
from codex_serverops_mcp.worker.authentication import SecretInputSink
from codex_serverops_mcp.worker.visible_auth import VisibleAuthenticationCoordinator

PROMPTS = {
    PromptKind.HOST_KEY: (
        "The authenticity of host 'manual.invalid' can't be established.\n"
        "ED25519 key fingerprint is SHA256:manual-release-check.\n"
        "Are you sure you want to continue connecting (yes/no/[fingerprint])?"
    ),
    PromptKind.PASSWORD: "operator@manual.invalid's password:",
    PromptKind.KEY_PASSPHRASE: "Enter passphrase for key 'manual-check':",
    PromptKind.SUDO_PASSWORD: "[sudo] password for operator:",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=[kind.value for kind in PromptKind], required=True)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    kind = PromptKind(args.kind)
    coordinator = VisibleAuthenticationCoordinator(
        AuthTargetContext(
            "manual-check",
            "Manual UI check",
            "manual.invalid",
            22,
            "operator",
        ),
        timeout=args.timeout,
    )
    try:
        coordinator.respond(
            PromptEvent(kind, PROMPTS[kind]),
            SecretInputSink(lambda _value: None, newline=b"\r\n"),
        )
        status = "confirmed" if kind is PromptKind.HOST_KEY else "submitted"
    except AuthenticationError as error:
        status = error.code
    print(json.dumps({"kind": kind.value, "status": status}))


if __name__ == "__main__":
    main()
