from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

from codex_serverops_mcp.ssh.prompts import PromptEvent, PromptKind
from codex_serverops_mcp.worker.authentication import SecretInputSink
from codex_serverops_mcp.worker.session import StatefulSshSession


class FixtureAuthenticationCoordinator:
    """Disposable spike-only coordinator used to exercise the product worker core."""

    def __init__(self, responses: Mapping[PromptKind, str]) -> None:
        self._responses = responses
        self.events: list[PromptKind] = []

    def respond(self, event: PromptEvent, sink: SecretInputSink) -> None:
        try:
            response = self._responses[event.kind]
        except KeyError as error:
            raise RuntimeError(f"unexpected product prompt: {event.kind.value}") from error
        self.events.append(event.kind)
        sink.submit(bytearray(response, encoding="utf-8"))


def probe_product_session_core(
    password_arguments: Sequence[str],
    key_arguments: Sequence[str],
    *,
    password: str,
    key_passphrase: str,
) -> set[PromptKind]:
    coordinator = FixtureAuthenticationCoordinator(
        {
            PromptKind.HOST_KEY: "yes",
            PromptKind.PASSWORD: password,
            PromptKind.SUDO_PASSWORD: password,
            PromptKind.KEY_PASSPHRASE: key_passphrase,
        }
    )
    password_session = StatefulSshSession(authenticator=coordinator)
    try:
        password_session.open(password_arguments)
        changed = password_session.execute("cd /opt/app")
        current = password_session.execute("pwd")
        if changed.cwd != "/opt/app" or current.output.strip() != "/opt/app":
            raise AssertionError("product session did not preserve its working directory")
        elevated = password_session.execute("sudo -k; sudo -v; sudo -n id -u")
        if elevated.exit_code != 0 or not elevated.output.strip().endswith("0"):
            raise AssertionError("product session sudo probe failed")
        interactive = password_session.interactive.start("cat")
        password_session.interactive.write("product-raw-terminal-ok\r\n")
        cursor = interactive.output_cursor
        output_parts: list[str] = []
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            terminal_output = password_session.interactive.read(
                cursor,
                timeout=min(0.25, deadline - time.monotonic()),
            )
            cursor = terminal_output.next_cursor
            output_parts.append(terminal_output.output)
            if "product-raw-terminal-ok" in "".join(output_parts):
                break
        combined_output = "".join(output_parts)
        if "product-raw-terminal-ok" not in combined_output:
            raise AssertionError(
                "product raw terminal did not return live output: "
                f"{combined_output[-500:]!r}"
            )
        password_session.interactive.close()
    finally:
        password_session.close()

    key_session = StatefulSshSession(authenticator=coordinator)
    try:
        key_session.open(key_arguments)
        result = key_session.execute("printf 'product-session-ok'")
        if result.exit_code != 0 or "product-session-ok" not in result.output:
            raise AssertionError("product protected-key session failed")
    finally:
        key_session.close()
    return set(coordinator.events)
