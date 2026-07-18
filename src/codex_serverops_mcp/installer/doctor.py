from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from codex_serverops_mcp.application import ApplicationServices
from codex_serverops_mcp.broker.manager import BrokerManager
from codex_serverops_mcp.config import ElevationMode, TomlProfileRepository
from codex_serverops_mcp.config.model import validate_profile_name
from codex_serverops_mcp.security import AuditLogger
from codex_serverops_mcp.ssh.target import find_windows_ssh, resolve_ssh_target

from .checks import LocalChecker
from .model import CheckReport, CheckResult, failed, passed, warning
from .paths import InstallPaths

REQUIRED_REMOTE_COMMANDS = (
    "bash",
    "realpath",
    "base64",
    "stat",
    "sha256sum",
    "find",
    "grep",
    "od",
    "sed",
    "head",
    "wc",
    "mktemp",
    "mv",
    "chmod",
    "chgrp",
    "sync",
)


@dataclass(slots=True)
class Doctor:
    paths: InstallPaths
    broker: BrokerManager | None = None

    def run(self, profile_name: str | None = None) -> CheckReport:
        manager = self.broker or BrokerManager(self.paths.runtime_dir)
        local = LocalChecker(self.paths, manager).run(include_broker=True)
        checks = list(local.checks)
        if profile_name is None:
            checks.append(
                warning(
                    "remote_not_checked",
                    "No profile was selected; connection and remote preflight were not run",
                )
            )
            return CheckReport(tuple(checks))
        checks.extend(self._remote(profile_name, manager))
        manager.shutdown_launched_broker()
        return CheckReport(tuple(checks))

    def _remote(self, profile_name: str, manager: BrokerManager) -> tuple[CheckResult, ...]:
        checks: list[CheckResult] = []
        repository = TomlProfileRepository(self.paths.config_file)
        try:
            validate_profile_name(profile_name)
            profile = repository.load().config.profiles[profile_name]
            target = resolve_ssh_target(profile, find_windows_ssh())
            checks.append(
                passed(
                    "profile_resolved",
                    f"Profile resolves to {target.user}@{target.host}:{target.port}",
                )
            )
            if profile.identity_file is not None and not Path(profile.identity_file).is_file():
                checks.append(
                    failed("identity_file_missing", "Configured identity file is missing")
                )
                return tuple(checks)
        except KeyError:
            return (failed("profile_missing", f"Profile does not exist: {profile_name}"),)
        except Exception as error:
            return (failed("profile_unresolved", f"Profile could not be resolved: {error}"),)

        services = ApplicationServices(
            repository,
            manager,
            audit=AuditLogger(self.paths.audit_dir),
        )
        session_id: str | None = None
        try:
            opened = services.server_connection("open", profile_name=profile_name)
            session_id = str(opened["session_id"])
            checks.append(passed("connection", "SSH connection reached a held Bash session"))
            ssh_user = opened.get("ssh_user")
            effective_user = opened.get("effective_user")
            checks.append(
                passed(
                    "effective_user",
                    f"SSH user is {ssh_user}; effective user is {effective_user}",
                )
            )
            if ssh_user == "root":
                checks.append(
                    warning(
                        "root_login",
                        "The profile logs in directly as root; use a restricted account "
                        "when possible",
                    )
                )
            checks.extend(self._bash_and_commands(services, session_id))
            checks.extend(self._allowed_roots(services, session_id, profile.allowed_roots))
            checks.extend(self._sudo(services, session_id, profile.elevation_mode))
        except Exception as error:
            checks.append(failed("remote_preflight_failed", f"Remote preflight failed: {error}"))
        finally:
            if session_id is not None:
                try:
                    services.server_connection("close", session_id=session_id)
                except Exception:
                    checks.append(
                        warning("session_cleanup", "Doctor could not confirm session cleanup")
                    )
        return tuple(checks)

    @staticmethod
    def _bash_and_commands(
        services: ApplicationServices,
        session_id: str,
    ) -> tuple[CheckResult, ...]:
        bash = services.server_exec(session_id, "printf '%s' \"${BASH_VERSION-}\"")
        checks: list[CheckResult] = []
        if bash.get("exit_code") == 0 and str(bash.get("output", "")).strip():
            checks.append(passed("bash", "Remote interactive shell is Bash"))
        else:
            checks.append(failed("bash_missing", "Remote shell did not expose BASH_VERSION"))
        names = " ".join(REQUIRED_REMOTE_COMMANDS)
        command = (
            f"for _serverops_cmd in {names}; do "
            "command -v \"$_serverops_cmd\" >/dev/null 2>&1 || "
            "printf '%s\\n' \"$_serverops_cmd\"; done"
        )
        result = services.server_exec(session_id, command)
        missing = tuple(line for line in str(result.get("output", "")).splitlines() if line)
        if missing:
            checks.append(
                failed(
                    "remote_commands_missing",
                    f"Required commands missing: {', '.join(missing)}",
                )
            )
        else:
            checks.append(passed("remote_commands", "Required remote commands are available"))
        return tuple(checks)

    @staticmethod
    def _allowed_roots(
        services: ApplicationServices,
        session_id: str,
        roots: tuple[str, ...],
    ) -> tuple[CheckResult, ...]:
        if not roots:
            return (passed("allowed_roots", "No structured file roots are configured"),)
        checks: list[CheckResult] = []
        for root in roots:
            encoded = base64.b64encode(root.encode("utf-8")).decode("ascii")
            command = (
                f"_serverops_root=$(printf '%s' '{encoded}' | base64 -d) && "
                "test -d \"$_serverops_root\" && realpath -e -- \"$_serverops_root\""
            )
            result = services.server_exec(session_id, command)
            if result.get("exit_code") == 0:
                checks.append(passed("allowed_root", f"Allowed root is canonicalizable: {root}"))
            else:
                checks.append(
                    failed("allowed_root_invalid", f"Allowed root is unavailable: {root}")
                )
        return tuple(checks)

    @staticmethod
    def _sudo(
        services: ApplicationServices,
        session_id: str,
        elevation_mode: ElevationMode,
    ) -> tuple[CheckResult, ...]:
        checks: list[CheckResult] = []
        if elevation_mode is ElevationMode.DISABLED:
            checks.append(passed("guided_sudo_disabled", "Guided elevation is disabled"))
        else:
            status = services.server_elevation("status", session_id)
            if status.get("active") is True:
                checks.append(
                    warning(
                        "sudo_noninteractive_active",
                        "sudo currently succeeds without a prompt; this may be cached or NOPASSWD",
                    )
                )
            else:
                checks.append(passed("sudo_prompt_required", "sudo -n does not currently elevate"))
        listing = services.server_exec(session_id, "sudo -n -l")
        output = str(listing.get("output", ""))
        if listing.get("exit_code") == 0:
            checks.append(
                warning(
                    "sudo_noninteractive_available",
                    "The SSH user can inspect or use sudo non-interactively",
                )
            )
        if "NOPASSWD:" in output and "ALL" in output:
            checks.append(
                warning(
                    "sudo_broad_nopasswd",
                    "sudo output suggests a broad NOPASSWD rule; review sudoers manually",
                )
            )
        return tuple(checks)
