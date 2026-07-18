from __future__ import annotations

import os
import subprocess
import threading
import time
import unittest

from codex_serverops_mcp.auth.errors import (
    AuthenticationCancelled,
    AuthenticationRejected,
    AuthenticationTimedOut,
)
from codex_serverops_mcp.auth.model import AuthTargetContext
from codex_serverops_mcp.auth.server import AuthLaunchDescriptor
from codex_serverops_mcp.auth.wire import AuthResponseKind
from codex_serverops_mcp.ssh.prompts import PromptEvent, PromptKind
from codex_serverops_mcp.worker.authentication import SecretInputSink


class FakeAuthProcess:
    def __init__(self, finished: threading.Event) -> None:
        self.finished = finished
        self.terminated = False

    def wait(self, timeout: float | None = None) -> int:
        if not self.finished.wait(timeout):
            raise subprocess.TimeoutExpired("fake-auth", timeout)
        return 0

    def terminate(self) -> None:
        self.terminated = True
        self.finished.set()

    def kill(self) -> None:
        self.terminate()


class FakeAuthLauncher:
    def __init__(self, response_kind: AuthResponseKind) -> None:
        self.response_kind = response_kind
        self.descriptors: list[AuthLaunchDescriptor] = []
        self.secret_buffers: list[bytearray] = []
        self.errors: list[BaseException] = []

    def launch(self, descriptor: AuthLaunchDescriptor) -> FakeAuthProcess:
        from codex_serverops_mcp.auth.client import DirectAuthClient

        self.descriptors.append(descriptor)
        finished = threading.Event()

        def answer() -> None:
            try:
                with DirectAuthClient(
                    descriptor.pipe,
                    descriptor.request_id,
                    descriptor.token,
                ) as client:
                    client.open()
                    if self.response_kind is AuthResponseKind.SECRET:
                        secret = bytearray(b"disposable-test-value")
                        self.secret_buffers.append(secret)
                        client.submit_secret(secret)
                    elif self.response_kind is AuthResponseKind.CONFIRM:
                        client.confirm()
                    elif self.response_kind is AuthResponseKind.REJECT:
                        client.reject()
                    elif self.response_kind is AuthResponseKind.CANCEL:
                        client.cancel()
                    else:
                        client.report_timeout()
            except BaseException as error:
                self.errors.append(error)
            finally:
                finished.set()

        threading.Thread(target=answer, daemon=True).start()
        return FakeAuthProcess(finished)


class SilentAuthLauncher:
    def __init__(self) -> None:
        self.process: ImmediateTimeoutProcess | None = None

    def launch(self, descriptor: AuthLaunchDescriptor) -> ImmediateTimeoutProcess:
        del descriptor
        process = ImmediateTimeoutProcess()
        self.process = process
        return process


class ImmediateTimeoutProcess:
    def __init__(self) -> None:
        self.terminated = False

    def wait(self, timeout: float | None = None) -> int:
        if not self.terminated:
            raise subprocess.TimeoutExpired("silent-auth", timeout)
        return 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True


@unittest.skipUnless(os.name == "nt", "visible auth coordination uses Windows named pipes")
class VisibleAuthenticationCoordinatorTests(unittest.TestCase):
    target = AuthTargetContext("prod", "Production", "example.test", 22, "deploy")

    def test_secret_prompts_flow_directly_from_auth_client_to_worker_sink(self) -> None:
        from codex_serverops_mcp.worker.visible_auth import VisibleAuthenticationCoordinator

        for kind in (
            PromptKind.PASSWORD,
            PromptKind.KEY_PASSPHRASE,
            PromptKind.SUDO_PASSWORD,
        ):
            with self.subTest(kind=kind):
                launcher = FakeAuthLauncher(AuthResponseKind.SECRET)
                writes: list[bytes] = []
                sink = SecretInputSink(writes.append, newline=b"\r\n")
                coordinator = VisibleAuthenticationCoordinator(self.target, launcher=launcher)

                coordinator.respond(PromptEvent(kind, f"{kind.value} prompt:"), sink)

                self.assertEqual(writes, [b"disposable-test-value\r\n"])
                self.assertEqual(launcher.errors, [])
                self.assertTrue(all(not any(buffer) for buffer in launcher.secret_buffers))
                self.assertEqual(len(launcher.descriptors), 1)

    def test_host_key_requires_explicit_confirmation(self) -> None:
        from codex_serverops_mcp.worker.visible_auth import VisibleAuthenticationCoordinator

        launcher = FakeAuthLauncher(AuthResponseKind.CONFIRM)
        writes: list[bytes] = []
        coordinator = VisibleAuthenticationCoordinator(self.target, launcher=launcher)

        coordinator.respond(
            PromptEvent(PromptKind.HOST_KEY, "Are you sure you want to continue connecting?"),
            SecretInputSink(writes.append, newline=b"\r\n"),
        )

        self.assertEqual(writes, [b"yes\r\n"])
        self.assertEqual(launcher.errors, [])

    def test_window_cancellation_is_a_controlled_failure(self) -> None:
        from codex_serverops_mcp.worker.visible_auth import VisibleAuthenticationCoordinator

        launcher = FakeAuthLauncher(AuthResponseKind.CANCEL)
        coordinator = VisibleAuthenticationCoordinator(self.target, launcher=launcher)

        with self.assertRaises(AuthenticationCancelled):
            coordinator.respond(
                PromptEvent(PromptKind.SUDO_PASSWORD, "[sudo] password for deploy:"),
                SecretInputSink(lambda _data: None, newline=b"\r\n"),
            )
        self.assertEqual(launcher.errors, [])

    def test_host_key_rejection_is_a_controlled_failure(self) -> None:
        from codex_serverops_mcp.worker.visible_auth import VisibleAuthenticationCoordinator

        coordinator = VisibleAuthenticationCoordinator(
            self.target,
            launcher=FakeAuthLauncher(AuthResponseKind.REJECT),
        )
        with self.assertRaises(AuthenticationRejected):
            coordinator.respond(
                PromptEvent(PromptKind.HOST_KEY, "Unknown host key"),
                SecretInputSink(lambda _data: None, newline=b"\r\n"),
            )

    def test_unresponsive_window_times_out_and_is_terminated(self) -> None:
        from codex_serverops_mcp.worker.visible_auth import VisibleAuthenticationCoordinator

        launcher = SilentAuthLauncher()
        coordinator = VisibleAuthenticationCoordinator(
            self.target,
            launcher=launcher,
            timeout=0.15,
        )
        with self.assertRaises(AuthenticationTimedOut):
            coordinator.respond(
                PromptEvent(PromptKind.PASSWORD, "password:"),
                SecretInputSink(lambda _data: None, newline=b"\r\n"),
            )
        self.assertIsNotNone(launcher.process)
        assert launcher.process is not None
        self.assertTrue(launcher.process.terminated)

    def test_active_window_can_be_cancelled_from_the_owning_relay(self) -> None:
        from codex_serverops_mcp.worker.visible_auth import VisibleAuthenticationCoordinator

        launcher = SilentAuthLauncher()
        coordinator = VisibleAuthenticationCoordinator(
            self.target,
            launcher=launcher,
            timeout=10,
        )
        errors: list[BaseException] = []

        def respond() -> None:
            try:
                coordinator.respond(
                    PromptEvent(PromptKind.PASSWORD, "password:"),
                    SecretInputSink(lambda _data: None, newline=b"\r\n"),
                )
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=respond)
        thread.start()
        deadline = time.monotonic() + 3
        while launcher.process is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNotNone(launcher.process)

        coordinator.cancel_active()
        thread.join(timeout=3)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], AuthenticationCancelled)
        assert launcher.process is not None
        self.assertTrue(launcher.process.terminated)


if __name__ == "__main__":
    unittest.main()
