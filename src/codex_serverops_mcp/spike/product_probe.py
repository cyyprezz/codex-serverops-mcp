from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

from codex_serverops_mcp.auth.model import AuthTargetContext
from codex_serverops_mcp.config import Authentication, ConnectionType, ServerProfile
from codex_serverops_mcp.ssh.auth_policy import ConnectionPromptPolicy
from codex_serverops_mcp.ssh.prompts import PromptEvent, PromptKind, operation_sudo_prompt
from codex_serverops_mcp.worker.askpass import OpenSshAskpassRelay
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

    def cancel_active(self) -> None:
        return


def _target_from_arguments(arguments: Sequence[str]) -> AuthTargetContext:
    try:
        port = int(arguments[arguments.index("-p") + 1])
        user = arguments[arguments.index("-l") + 1]
        host = arguments[arguments.index("--") + 1]
    except (ValueError, IndexError) as error:
        raise ValueError("product spike requires direct OpenSSH arguments") from error
    return AuthTargetContext(
        "local-product-spike",
        "Local product spike",
        host,
        port,
        user,
    )


def _profile_for_target(
    target: AuthTargetContext,
    authentication: Authentication,
) -> ServerProfile:
    return ServerProfile(
        display_name=target.display_name,
        connection_type=ConnectionType.DIRECT,
        authentication=authentication,
        host=target.host,
        port=target.port,
        user=target.user,
    )


def _open_with_askpass(
    session: StatefulSshSession,
    arguments: Sequence[str],
    profile: ServerProfile,
    target: AuthTargetContext,
    coordinator: FixtureAuthenticationCoordinator,
) -> None:
    relay = OpenSshAskpassRelay(
        target,
        ConnectionPromptPolicy.from_profile(profile),
        coordinator,
        timeout=20,
    )
    relay.start()
    try:
        session.open(
            arguments,
            timeout=20,
            environment=relay.environment,
            failure_check=relay.check,
        )
        relay.check()
    finally:
        relay.close()


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
    password_target = _target_from_arguments(password_arguments)
    key_target = _target_from_arguments(key_arguments)
    password_session = StatefulSshSession(authenticator=coordinator)
    try:
        _open_with_askpass(
            password_session,
            password_arguments,
            _profile_for_target(
                password_target,
                Authentication.INTERACTIVE_PASSWORD,
            ),
            password_target,
            coordinator,
        )
        changed = password_session.execute("cd /opt/app")
        current = password_session.execute("pwd")
        if changed.cwd != "/opt/app" or current.output.strip() != "/opt/app":
            raise AssertionError("product session did not preserve its working directory")
        sudo_token = "a" * 32
        elevated = password_session.execute(
            "/usr/bin/sudo -k; "
            f"/usr/bin/sudo -p '{operation_sudo_prompt('elevation', sudo_token)}' -v; "
            "/usr/bin/sudo -n id -u",
            allow_sudo_prompt=True,
            sudo_prompt_token=sudo_token,
        )
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
        _open_with_askpass(
            key_session,
            key_arguments,
            _profile_for_target(key_target, Authentication.OPENSSH),
            key_target,
            coordinator,
        )
        result = key_session.execute("printf 'product-session-ok'")
        if result.exit_code != 0 or "product-session-ok" not in result.output:
            raise AssertionError("product protected-key session failed")
    finally:
        key_session.close()
    return set(coordinator.events)
