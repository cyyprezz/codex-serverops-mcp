from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from codex_serverops_mcp.config import (
    Authentication,
    ConnectionType,
    ElevationMode,
    ServerOpsConfig,
    ServerProfile,
    TomlProfileRepository,
)
from codex_serverops_mcp.ssh.target import ResolvedSshTarget
from codex_serverops_mcp.worker.result import ExecutionResult
from codex_serverops_mcp.worker.state import SessionState, SessionStateMachine


class FakeSession:
    def __init__(self) -> None:
        self.state = SessionStateMachine()
        self.open_arguments: list[str] = []
        self.open_allows_sudo = False
        self.execute_allows_sudo: list[bool] = []
        self.closed = False

    def open(self, arguments, *, timeout: float, allow_sudo_prompt: bool = False) -> None:
        del timeout
        self.open_arguments = list(arguments)
        self.open_allows_sudo = allow_sudo_prompt
        self.state.transition(SessionState.STARTING)
        self.state.transition(SessionState.READY)

    def execute(
        self,
        command: str,
        *,
        timeout: float,
        allow_sudo_prompt: bool = False,
    ) -> ExecutionResult:
        self.state.require(SessionState.READY)
        self.execute_allows_sudo.append(allow_sudo_prompt)
        return ExecutionResult(
            output="0" if command == "id -u" else f"ran:{command}",
            exit_code=0,
            cwd="/opt/app",
            truncated=False,
            duration_ms=5,
        )

    def close(self) -> None:
        self.closed = True
        if self.state.state is not SessionState.CLOSED:
            self.state.begin_close()
            self.state.transition(SessionState.CLOSED)


@unittest.skipUnless(os.name == "nt", "worker service secures Windows local paths")
class WorkerSessionServiceTests(unittest.TestCase):
    def test_profile_drives_ssh_arguments_auth_context_and_execution(self) -> None:
        from codex_serverops_mcp.ipc.security import inspect_path_security
        from codex_serverops_mcp.worker.service import WorkerSessionService

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = TomlProfileRepository(root / "config.toml")
            profile = ServerProfile(
                display_name="Production",
                connection_type=ConnectionType.DIRECT,
                authentication=Authentication.OPENSSH,
                host="192.0.2.20",
                port=22,
                user="deploy",
                environment="production",
                elevation_mode=ElevationMode.INTERACTIVE,
            )
            repository.save(ServerOpsConfig(profiles={"prod": profile}))
            sessions: list[FakeSession] = []
            auth_targets: list[object] = []

            def session_factory(_profile, auth_target):
                session = FakeSession()
                sessions.append(session)
                auth_targets.append(auth_target)
                return session

            known_hosts = root / "known_hosts"
            service = WorkerSessionService(
                "prod",
                repository=repository,
                ssh_finder=lambda: Path("C:/Windows/System32/OpenSSH/ssh.exe"),
                target_resolver=lambda _profile, _ssh: ResolvedSshTarget(
                    "192.0.2.20", 22, "deploy"
                ),
                session_factory=session_factory,
                known_hosts_path=known_hosts,
            )

            opened = service.open()
            executed = service.execute("pwd")
            acquired = service.elevation("acquire", {})

            self.assertEqual(opened["state"], "ready")
            self.assertEqual(opened["ssh_user"], "deploy")
            self.assertEqual(opened["effective_user"], "deploy")
            self.assertEqual(executed["cwd"], "/opt/app")
            self.assertEqual(executed["output"], "ran:pwd")
            self.assertTrue(acquired["active"])
            self.assertIn(str(known_hosts.resolve()), " ".join(sessions[0].open_arguments))
            self.assertEqual(auth_targets[0].host, "192.0.2.20")
            self.assertEqual(sessions[0].execute_allows_sudo, [False, True])
            self.assertTrue(inspect_path_security(str(known_hosts)).current_user_only)
            service.close()
            self.assertTrue(sessions[0].closed)

    def test_root_worker_uses_separate_sudo_shell_and_disables_file_tools(self) -> None:
        from codex_serverops_mcp.files.errors import RemoteFileError
        from codex_serverops_mcp.worker.service import WorkerSessionService

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = TomlProfileRepository(root / "config.toml")
            profile = ServerProfile(
                display_name="Production root",
                connection_type=ConnectionType.DIRECT,
                authentication=Authentication.OPENSSH,
                host="192.0.2.20",
                port=22,
                user="deploy",
                elevation_mode=ElevationMode.NON_INTERACTIVE,
                allow_root_session=True,
            )
            repository.save(ServerOpsConfig(profiles={"prod": profile}))
            sessions: list[FakeSession] = []

            def session_factory(_profile, _auth_target):
                session = FakeSession()
                sessions.append(session)
                return session

            service = WorkerSessionService(
                "prod",
                repository=repository,
                ssh_finder=lambda: Path("C:/Windows/System32/OpenSSH/ssh.exe"),
                target_resolver=lambda _profile, _ssh: ResolvedSshTarget(
                    "192.0.2.20", 22, "deploy"
                ),
                session_factory=session_factory,
                known_hosts_path=root / "known_hosts",
                root_session=True,
            )

            opened = service.open()

            self.assertEqual(opened["effective_user"], "root")
            self.assertTrue(opened["root_session"])
            self.assertIn("sudo -n -i", " ".join(sessions[0].open_arguments))
            self.assertFalse(sessions[0].open_allows_sudo)
            with self.assertRaises(RemoteFileError) as captured:
                service.files("stat", {"path": "/opt/app"}, write=False)
            self.assertEqual(captured.exception.code, "root_session_file_access_disabled")
            service.close()


if __name__ == "__main__":
    unittest.main()
