from __future__ import annotations

import os
import threading
import time
import unittest
import uuid


@unittest.skipUnless(os.name == "nt", "secured named pipes are Windows-only")
class NamedPipeTests(unittest.TestCase):
    @staticmethod
    def _pipe_path() -> str:
        from codex_serverops_mcp.ipc.security import pipe_name_for_current_user

        return pipe_name_for_current_user(f"test-{uuid.uuid4().hex[:12]}")

    def test_pipe_dacl_allows_only_the_current_user_sid(self) -> None:
        from codex_serverops_mcp.ipc.named_pipe import NamedPipeListener

        with NamedPipeListener(self._pipe_path()) as listener:
            report = listener.security_report

        self.assertTrue(report.current_user_only)
        self.assertEqual(report.denied_sids, ())

    def test_versioned_handshake_and_message_cross_the_pipe(self) -> None:
        from codex_serverops_mcp.ipc.handshake import client_handshake, server_handshake
        from codex_serverops_mcp.ipc.messages import Envelope
        from codex_serverops_mcp.ipc.named_pipe import NamedPipeListener, connect_named_pipe

        listener = NamedPipeListener(self._pipe_path())
        token = uuid.uuid4().hex
        errors: list[BaseException] = []

        def serve() -> None:
            try:
                with listener.accept() as connection:
                    server_handshake(connection, token)
                    request = connection.receive()
                    connection.send(
                        Envelope.create(
                            "ping.result",
                            {"value": request.payload["value"]},
                            message_id=request.message_id,
                        )
                    )
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=serve)
        thread.start()
        client_error: BaseException | None = None
        try:
            try:
                with connect_named_pipe(listener.path) as client:
                    client_handshake(client, token)
                    request = Envelope.create("ping", {"value": "ok"})
                    client.send(request)
                    response = client.receive()
            except BaseException as error:
                client_error = error
        finally:
            thread.join(timeout=5)
            listener.close()
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        if client_error is not None:
            raise client_error
        self.assertEqual(response.message_id, request.message_id)
        self.assertEqual(response.payload["value"], "ok")

    def test_wrong_instance_token_fails_closed(self) -> None:
        from codex_serverops_mcp.ipc.errors import IpcAuthenticationError, IpcClosed
        from codex_serverops_mcp.ipc.handshake import client_handshake, server_handshake
        from codex_serverops_mcp.ipc.named_pipe import NamedPipeListener, connect_named_pipe

        listener = NamedPipeListener(self._pipe_path())
        errors: list[BaseException] = []

        def serve() -> None:
            try:
                with listener.accept() as connection:
                    server_handshake(connection, "expected-token")
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            with (
                connect_named_pipe(listener.path) as client,
                self.assertRaises(IpcAuthenticationError),
            ):
                client_handshake(client, "wrong-token")
        finally:
            thread.join(timeout=5)
            listener.close()
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], IpcClosed)

    def test_receive_deadline_invalidates_the_stream(self) -> None:
        from codex_serverops_mcp.ipc.errors import IpcClosed, IpcTimeout
        from codex_serverops_mcp.ipc.handshake import client_handshake, server_handshake
        from codex_serverops_mcp.ipc.named_pipe import NamedPipeListener, connect_named_pipe

        listener = NamedPipeListener(self._pipe_path())
        errors: list[BaseException] = []

        def serve() -> None:
            try:
                with listener.accept() as connection:
                    server_handshake(connection, "deadline-token")
                    with self.assertRaises(IpcTimeout):
                        connection.receive(timeout=0.1)
                    with self.assertRaises(IpcClosed):
                        connection.receive(timeout=1)
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=serve)
        thread.start()
        with connect_named_pipe(listener.path) as client:
            client_handshake(client, "deadline-token")
            time.sleep(0.15)
        thread.join(timeout=3)
        listener.close()

        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_connection_close_is_safe_from_multiple_threads(self) -> None:
        from codex_serverops_mcp.ipc.named_pipe import (
            NamedPipeListener,
            connect_named_pipe,
        )

        listener = NamedPipeListener(self._pipe_path())
        accepted: list[object] = []
        accept_errors: list[BaseException] = []

        def accept() -> None:
            try:
                accepted.append(listener.accept())
            except BaseException as error:
                accept_errors.append(error)

        accept_thread = threading.Thread(target=accept)
        accept_thread.start()
        client = connect_named_pipe(listener.path)
        accept_thread.join(timeout=3)
        self.assertFalse(accept_thread.is_alive())
        self.assertEqual(accept_errors, [])
        self.assertEqual(len(accepted), 1)

        errors: list[BaseException] = []
        barrier = threading.Barrier(8)

        def close_client() -> None:
            try:
                barrier.wait(timeout=3)
                client.close()
            except BaseException as error:
                errors.append(error)

        threads = [threading.Thread(target=close_client) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)

        accepted[0].close()
        listener.close()
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])

    def test_frame_deadline_allows_idle_but_rejects_a_partial_frame(self) -> None:
        import win32file

        from codex_serverops_mcp.ipc.errors import IpcTimeout
        from codex_serverops_mcp.ipc.messages import Envelope
        from codex_serverops_mcp.ipc.named_pipe import NamedPipeListener, connect_named_pipe

        listener = NamedPipeListener(self._pipe_path())
        received: list[Envelope] = []
        errors: list[BaseException] = []

        def serve_complete() -> None:
            try:
                with listener.accept() as connection:
                    received.append(connection.receive(frame_timeout=0.1))
            except BaseException as error:
                errors.append(error)

        complete_thread = threading.Thread(target=serve_complete)
        complete_thread.start()
        with connect_named_pipe(listener.path) as client:
            time.sleep(0.15)
            client.send(Envelope.create("idle.complete", {}))
        complete_thread.join(timeout=3)

        def serve_partial() -> None:
            try:
                with listener.accept() as connection:
                    connection.receive(frame_timeout=0.1)
            except BaseException as error:
                errors.append(error)

        partial_thread = threading.Thread(target=serve_partial)
        partial_thread.start()
        with connect_named_pipe(listener.path) as client:
            win32file.WriteFile(client._handle, b"\0")  # noqa: SLF001
            partial_thread.join(timeout=3)
        listener.close()

        self.assertFalse(complete_thread.is_alive())
        self.assertFalse(partial_thread.is_alive())
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].message_type, "idle.complete")
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], IpcTimeout)

    def test_untrusted_server_never_receives_the_instance_token(self) -> None:
        from codex_serverops_mcp import BROKER_PROTOCOL_VERSION
        from codex_serverops_mcp.ipc.errors import IpcAuthenticationError
        from codex_serverops_mcp.ipc.handshake import client_handshake
        from codex_serverops_mcp.ipc.messages import Envelope
        from codex_serverops_mcp.ipc.named_pipe import NamedPipeListener, connect_named_pipe

        listener = NamedPipeListener(self._pipe_path())
        received_payloads: list[dict[str, object]] = []

        def serve() -> None:
            with listener.accept() as connection:
                challenge = connection.receive()
                received_payloads.append(dict(challenge.payload))
                connection.send(
                    Envelope.create(
                        "hello.challenge.ack",
                        {
                            "protocol_version": BROKER_PROTOCOL_VERSION,
                            "server_nonce": "0" * 64,
                            "server_proof": "0" * 64,
                        },
                        message_id=challenge.message_id,
                    )
                )

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            with (
                connect_named_pipe(listener.path) as client,
                self.assertRaises(IpcAuthenticationError),
            ):
                client_handshake(client, "must-never-cross-the-pipe")
        finally:
            thread.join(timeout=3)
            listener.close()

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(received_payloads), 1)
        self.assertNotIn("instance_token", received_payloads[0])
        self.assertNotIn("must-never-cross-the-pipe", repr(received_payloads))

    def test_client_validates_pipe_security_before_handshake(self) -> None:
        from unittest.mock import patch

        from codex_serverops_mcp.ipc.errors import PipeSecurityError
        from codex_serverops_mcp.ipc.named_pipe import NamedPipeListener, connect_named_pipe

        listener = NamedPipeListener(self._pipe_path())
        try:
            with (
                patch(
                    "codex_serverops_mcp.ipc.named_pipe.require_current_user_only",
                    side_effect=PipeSecurityError("spoofed owner"),
                ),
                self.assertRaises(PipeSecurityError),
            ):
                connect_named_pipe(listener.path)
        finally:
            listener.close()


if __name__ == "__main__":
    unittest.main()
