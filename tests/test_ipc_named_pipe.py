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
