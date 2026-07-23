from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass

from codex_serverops_mcp import (
    BROKER_PROTOCOL_VERSION,
    CONFIG_SCHEMA_VERSION,
    PACKAGE_VERSION,
    WORKER_PROTOCOL_VERSION,
)
from codex_serverops_mcp.broker.manager import BrokerManager
from codex_serverops_mcp.config import TomlProfileRepository
from codex_serverops_mcp.ssh.target import find_windows_ssh

from .codex_config import inspect_managed_version, parse_codex_config
from .model import CheckReport, CheckResult, failed, passed, warning
from .paths import InstallPaths


@dataclass(slots=True)
class LocalChecker:
    paths: InstallPaths
    broker: BrokerManager | None = None

    def run(self, *, include_broker: bool, client: str = "codex") -> CheckReport:
        if client not in {"core", "codex", "claude", "all"}:
            raise ValueError(f"unsupported client check: {client}")
        checks = [
            self._platform(),
            self._python(),
            self._uvx(),
            self._ssh(),
            self._package_contract(),
            self._profiles(),
            self._local_security(),
        ]
        if client in {"codex", "all"}:
            checks.append(self._codex_config())
        if client in {"claude", "all"}:
            checks.append(self._claude_code())
        if include_broker:
            checks.extend(self._broker())
        return CheckReport(tuple(checks))

    @staticmethod
    def _claude_code() -> CheckResult:
        executable = shutil.which("claude")
        if executable:
            return passed("claude_code", f"Claude Code CLI found at {executable}")
        return failed(
            "claude_code_missing",
            "Claude Code CLI was not found on PATH; plugin state is owned by Claude Code",
        )

    @staticmethod
    def _platform() -> CheckResult:
        if os.name == "nt":
            return passed("windows", "Windows runtime detected")
        return failed("windows_required", "Version 0.1 supports Windows 10 and 11 only")

    @staticmethod
    def _python() -> CheckResult:
        version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        if sys.version_info[:2] == (3, 12):
            return passed("python", f"Python {version} matches the 3.12 contract")
        return failed("python_unsupported", f"Python {version} is not the required 3.12 runtime")

    @staticmethod
    def _uvx() -> CheckResult:
        executable = shutil.which("uvx")
        if executable:
            return passed("uvx", "uvx is available for checkout-free MCP startup")
        return failed("uvx_missing", "uvx was not found on PATH")

    @staticmethod
    def _ssh() -> CheckResult:
        try:
            path = find_windows_ssh()
        except Exception as error:
            return failed("ssh_missing", str(error))
        return passed("ssh", f"Windows OpenSSH client found at {path}")

    @staticmethod
    def _package_contract() -> CheckResult:
        versions = (
            f"package={PACKAGE_VERSION}, broker={BROKER_PROTOCOL_VERSION}, "
            f"worker={WORKER_PROTOCOL_VERSION}, config={CONFIG_SCHEMA_VERSION}"
        )
        return passed("version_contract", versions)

    def _profiles(self) -> CheckResult:
        try:
            snapshot = TomlProfileRepository(self.paths.config_file).load()
        except Exception as error:
            return failed("profiles_invalid", f"Server profile configuration is invalid: {error}")
        return passed(
            "profiles",
            f"Server profile configuration is valid ({len(snapshot.config.profiles)} profiles)",
        )

    def _codex_config(self) -> CheckResult:
        path = self.paths.codex_config_file
        if not path.exists():
            return warning("codex_config_missing", "Codex config.toml does not exist yet")
        try:
            content = path.read_text(encoding="utf-8")
            parsed = parse_codex_config(content)
            pinned = inspect_managed_version(path)
        except Exception as error:
            return failed("codex_config_invalid", f"Codex configuration is invalid: {error}")
        servers = parsed.get("mcp_servers")
        if pinned is None:
            if isinstance(servers, dict) and "serverops" in servers:
                return warning(
                    "codex_config_unmanaged",
                    "An unmarked ServerOps MCP entry exists and will not be overwritten",
                )
            return warning(
                "codex_config_not_installed",
                "The installer-managed ServerOps MCP block is not configured",
            )
        if pinned != PACKAGE_VERSION:
            return warning(
                "codex_config_version_mismatch",
                f"Codex pins {pinned}, while this installer is {PACKAGE_VERSION}",
            )
        return passed("codex_config", f"Codex MCP block is exactly pinned to {pinned}")

    def _local_security(self) -> CheckResult:
        if not self.paths.app_dir.exists():
            return warning("local_data_missing", "Local application data has not been prepared")
        if os.name != "nt":
            return failed("local_acl_unsupported", "Current-user DACL checks require Windows")
        try:
            from codex_serverops_mcp.ipc.security import inspect_path_security

            report = inspect_path_security(str(self.paths.app_dir))
        except Exception as error:
            return failed("local_acl_invalid", f"Local application data ACL check failed: {error}")
        if not report.current_user_only:
            return failed("local_acl_shared", "Local application data is not current-user-only")
        return passed("local_acl", "Local application data is restricted to the current user")

    def _broker(self) -> tuple[CheckResult, ...]:
        manager = self.broker or BrokerManager(self.paths.runtime_dir)
        try:
            with manager.connect() as client:
                ping = client.request("broker.ping")
            checks = [
                passed("broker", f"Broker is reachable (PID {ping.get('pid')})"),
            ]
            if ping.get("protocol_version") != BROKER_PROTOCOL_VERSION:
                checks.append(failed("broker_protocol", "Broker protocol version is incompatible"))
            else:
                checks.append(passed("broker_protocol", "Broker protocol handshake is compatible"))
            if ping.get("ipc_current_user_only") is True:
                checks.append(passed("broker_acl", "Broker IPC is restricted to the current user"))
            else:
                checks.append(failed("broker_acl", "Broker IPC ACL could not be verified"))
            return tuple(checks)
        except Exception as error:
            return (failed("broker_unavailable", f"Broker could not start or respond: {error}"),)
        finally:
            manager.shutdown_launched_broker()
