from __future__ import annotations

import base64
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from codex_serverops_mcp.broker.client import BrokerClient
from codex_serverops_mcp.broker.errors import BrokerOutcomeUnknown
from codex_serverops_mcp.broker.manager import BrokerManager
from codex_serverops_mcp.config import ServerOpsConfig, ServerProfile, TomlProfileRepository
from codex_serverops_mcp.config.model import Authentication, validate_profile_name
from codex_serverops_mcp.config.presentation import profile_details
from codex_serverops_mcp.errors import ConfigConflictError, ConfigurationError
from codex_serverops_mcp.identifiers import validate_session_id
from codex_serverops_mcp.security import AuditLogger, ProfileAudit, SetupAuditStatus

from .keys import (
    Ed25519KeyGenerator,
    GeneratedKey,
    SecretSource,
    validate_public_key_line,
)


class BrokerProvider(Protocol):
    def connect(self) -> BrokerClient: ...


@dataclass(slots=True)
class ProfileSetupOperations:
    repository: TomlProfileRepository
    broker: BrokerProvider
    audit: ProfileAudit = field(default_factory=ProfileAudit)

    @classmethod
    def create(cls) -> ProfileSetupOperations:
        return cls(TomlProfileRepository(), BrokerManager(), ProfileAudit(AuditLogger()))

    def add(self, profile_name: str, profile: ServerProfile) -> dict[str, object]:
        validate_profile_name(profile_name)

        def add_only(config: ServerOpsConfig) -> ServerOpsConfig:
            if profile_name in config.profiles:
                raise ConfigurationError(f"profile already exists: {profile_name}")
            return config.with_profile(profile_name, profile)

        snapshot = self.repository.update(add_only)
        status = self.audit.record("profile_created", profile_name, profile=profile)
        return status.attach(
            {"profile": profile_details(profile_name, snapshot.config.profiles[profile_name])}
        )

    def edit(self, profile_name: str, profile: ServerProfile) -> dict[str, object]:
        validate_profile_name(profile_name)

        def replace_only(config: ServerOpsConfig) -> ServerOpsConfig:
            if profile_name not in config.profiles:
                raise ConfigurationError(f"profile does not exist: {profile_name}")
            return config.with_profile(profile_name, profile)

        snapshot = self.repository.update(replace_only)
        status = self.audit.record("profile_updated", profile_name, profile=profile)
        return status.attach(
            {"profile": profile_details(profile_name, snapshot.config.profiles[profile_name])}
        )

    def remove(self, profile_name: str) -> dict[str, object]:
        validate_profile_name(profile_name)
        original = self.repository.load()
        try:
            profile = original.config.profiles[profile_name]
        except KeyError as error:
            raise ConfigurationError(f"profile does not exist: {profile_name}") from error
        self.repository.remove_profile(profile_name, expected_hash=original.content_hash)
        status = self.audit.record("profile_removed", profile_name, profile=profile)
        return status.attach({"profile_name": profile_name})

    def test(self, profile_name: str) -> dict[str, object]:
        profile = self._require_profile(profile_name)
        started = self.audit.record(
            "profile_test_started", profile_name, profile=profile, result_status="started"
        )
        session_id: str | None = None
        try:
            opened = self._request("session.open", {"profile_name": profile_name})
            opened_session_id = opened.get("session_id")
            if not isinstance(opened_session_id, str):
                raise RuntimeError("broker returned no valid setup test session")
            validate_session_id(opened_session_id)
            session_id = opened_session_id
            result = {
                "profile_name": profile_name,
                "connection": "ready",
                "effective_user": opened.get("effective_user"),
            }
        except BaseException:
            self.audit.record(
                "profile_test_failed", profile_name, profile=profile, result_status="failed"
            )
            raise
        finally:
            if session_id is not None:
                self._close_session(session_id)
        completed = self.audit.record("profile_test_completed", profile_name, profile=profile)
        return SetupAuditStatus.combine(started, completed).attach(result)

    def generate_key(
        self,
        generator: Ed25519KeyGenerator,
        profile_name: str,
        secret_source: SecretSource,
        *,
        destination: Path | None = None,
    ) -> tuple[GeneratedKey, SetupAuditStatus]:
        validate_profile_name(profile_name)
        started = self.audit.record(
            "key_generation_started", profile_name, result_status="started"
        )
        try:
            generated = generator.generate(
                profile_name,
                secret_source,
                destination=destination,
            )
        except BaseException:
            self.audit.record(
                "key_generation_failed", profile_name, result_status="failed"
            )
            raise
        completed = self.audit.record("key_generation_completed", profile_name)
        return generated, SetupAuditStatus.combine(started, completed)

    def install_public_key_and_switch(
        self,
        profile_name: str,
        password_profile: ServerProfile,
        key_profile: ServerProfile,
        public_key: str,
        *,
        replace_existing: bool,
    ) -> dict[str, object]:
        self._validate_key_transition(password_profile, key_profile)
        original = self.repository.load()
        exists = profile_name in original.config.profiles
        if replace_existing != exists:
            expectation = "exist" if replace_existing else "not exist"
            raise ConfigConflictError(f"profile was expected to {expectation}: {profile_name}")
        staging_config = original.config.with_profile(profile_name, password_profile)
        staging = self.repository.save(staging_config, expected_hash=original.content_hash)
        owned_hash = staging.content_hash
        try:
            install_audit = self._install_public_key(
                profile_name,
                password_profile,
                public_key,
            )

            key_config = staging.config.with_profile(profile_name, key_profile)
            switched = self.repository.save(key_config, expected_hash=owned_hash)
            owned_hash = switched.content_hash
            tested = self.test(profile_name)
            mutation = self.audit.record(
                "profile_updated" if replace_existing else "profile_created",
                profile_name,
                profile=key_profile,
            )
            return SetupAuditStatus.combine(
                install_audit,
                SetupAuditStatus.from_result(tested),
                mutation,
            ).attach(
                {
                    "profile": profile_details(profile_name, key_profile),
                    "public_key_installed": True,
                    "key_login_tested": True,
                }
            )
        except BaseException:
            current = self.repository.load()
            if current.content_hash == owned_hash:
                self.repository.save(original.config, expected_hash=owned_hash)
            raise

    def _install_public_key(
        self,
        profile_name: str,
        profile: ServerProfile,
        public_key: str,
    ) -> SetupAuditStatus:
        started = self.audit.record(
            "public_key_install_started",
            profile_name,
            profile=profile,
            result_status="started",
        )
        session_id: str | None = None
        try:
            opened = self._request("session.open", {"profile_name": profile_name})
            session_id = self._session_id(opened)
            command = build_public_key_install_command(public_key)
            installed = self._request(
                "session.exec",
                {"session_id": session_id, "command": command, "timeout": 30.0},
            )
            if _is_outcome_unknown(installed.get("status")):
                raise BrokerOutcomeUnknown(
                    "outcome_unknown",
                    "the public SSH key installation outcome is unknown",
                )
            if installed.get("status") != "completed" or installed.get("exit_code") != 0:
                raise RuntimeError("the public SSH key could not be installed remotely")
        except BaseException as error:
            action = (
                "public_key_install_outcome_unknown"
                if _is_outcome_unknown(getattr(error, "code", None))
                else "public_key_install_failed"
            )
            self.audit.record(
                action,
                profile_name,
                profile=profile,
                result_status=(
                    "outcome_unknown" if action.endswith("outcome_unknown") else "failed"
                ),
            )
            raise
        finally:
            if session_id is not None:
                self._close_session(session_id)
        completed = self.audit.record(
            "public_key_install_completed", profile_name, profile=profile
        )
        return SetupAuditStatus.combine(started, completed)

    def _require_profile(self, profile_name: str) -> ServerProfile:
        validate_profile_name(profile_name)
        try:
            return self.repository.load().config.profiles[profile_name]
        except KeyError as error:
            raise ConfigurationError(f"profile does not exist: {profile_name}") from error

    def _request(
        self,
        message_type: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        with self.broker.connect() as client:
            return client.request(message_type, payload)

    def _close_session(self, session_id: str) -> None:
        with suppress(Exception):
            self._request("session.close", {"session_id": session_id})

    @staticmethod
    def _session_id(opened: dict[str, object]) -> str:
        session_id = opened.get("session_id")
        if not isinstance(session_id, str):
            raise RuntimeError("broker returned no valid setup session")
        validate_session_id(session_id)
        return session_id

    @staticmethod
    def _validate_key_transition(
        password_profile: ServerProfile,
        key_profile: ServerProfile,
    ) -> None:
        if password_profile.authentication is not Authentication.INTERACTIVE_PASSWORD:
            raise ValueError("public-key installation requires an interactive password profile")
        if key_profile.authentication is not Authentication.OPENSSH:
            raise ValueError("the resulting profile must use OpenSSH authentication")
        if key_profile.identity_file is None:
            raise ValueError("the resulting profile must select a private key file")
        target_fields = ("connection_type", "ssh_host", "host", "port", "user")
        if any(
            getattr(password_profile, field) != getattr(key_profile, field)
            for field in target_fields
        ):
            raise ValueError("password and key profiles must refer to the same SSH target")


def build_public_key_install_command(public_key: str) -> str:
    encoded = base64.b64encode(validate_public_key_line(public_key).encode("utf-8")).decode(
        "ascii"
    )
    return "\n".join(
        (
            "set -eu",
            "umask 077",
            'mkdir -p -- "$HOME/.ssh"',
            'chmod 700 -- "$HOME/.ssh"',
            'touch -- "$HOME/.ssh/authorized_keys"',
            'chmod 600 -- "$HOME/.ssh/authorized_keys"',
            f"_serverops_key=$(printf '%s' '{encoded}' | base64 -d)",
            'if ! grep -qxF -- "$_serverops_key" "$HOME/.ssh/authorized_keys"; then',
            '  if [ -s "$HOME/.ssh/authorized_keys" ] && '
            '     [ "$(tail -c 1 "$HOME/.ssh/authorized_keys" | wc -l)" -eq 0 ]; then',
            '    printf \'\\n\' >> "$HOME/.ssh/authorized_keys"',
            "  fi",
            '  printf \'%s\\n\' "$_serverops_key" >> "$HOME/.ssh/authorized_keys"',
            "fi",
            "unset _serverops_key",
        )
    )


def _is_outcome_unknown(value: object) -> bool:
    return isinstance(value, str) and value.endswith("outcome_unknown")
