from __future__ import annotations

import base64
import re
import secrets
from dataclasses import dataclass
from enum import StrEnum

from codex_serverops_mcp.broker.errors import BrokerOutcomeUnknown
from codex_serverops_mcp.errors import ServerOpsError

from .keys import validate_public_key_line

TOKEN = re.compile(r"^[0-9a-f]{32}$")
REMOTE_KEY_WARNING = (
    "The public key may already be present in the remote authorized_keys file.\n"
    "Review the remote account before retrying or removing the key."
)
ROLLED_BACK_WARNING = "The local profile switch was rolled back.\n\n" + REMOTE_KEY_WARNING


class LocalRollbackStatus(StrEnum):
    ROLLED_BACK = "rolled_back"
    SKIPPED_CONCURRENT_CHANGE = "skipped_concurrent_change"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PublicKeyInstallResult:
    was_new: bool


@dataclass(frozen=True, slots=True)
class PublicKeyInstallPlan:
    command: str
    marker_prefix: str
    key_identity: str

    def parse(self, output: object) -> PublicKeyInstallResult:
        if not isinstance(output, str):
            raise PublicKeyInstallOutcomeUnknown(
                "the remote key-install command returned no verifiable marker"
            )
        markers = [
            line.strip()
            for line in output.splitlines()
            if line.strip().startswith(self.marker_prefix)
        ]
        expected = {
            f"{self.marker_prefix}key_added": True,
            f"{self.marker_prefix}key_already_present": False,
        }
        if len(markers) != 1 or markers[0] not in expected:
            raise PublicKeyInstallOutcomeUnknown(
                "the remote key-install result was missing or ambiguous"
            )
        return PublicKeyInstallResult(was_new=expected[markers[0]])


class PublicKeyInstallOutcomeUnknown(BrokerOutcomeUnknown):
    def __init__(
        self,
        message: str,
        *,
        rollback_status: LocalRollbackStatus | None = None,
    ) -> None:
        self.local_profile_rollback_status = (
            None if rollback_status is None else rollback_status.value
        )
        self.local_profile_rolled_back = rollback_status is LocalRollbackStatus.ROLLED_BACK
        self.public_key_installed = None
        self.public_key_was_new = None
        detail = message
        if rollback_status is not None:
            detail = f"{message}\n\n{_transition_warning(rollback_status)}"
        super().__init__("outcome_unknown", detail)


class PublicKeyTransitionError(ServerOpsError):
    code = "public_key_transition_failed"

    def __init__(
        self,
        rollback_status: LocalRollbackStatus,
        *,
        public_key_installed: bool | None,
        public_key_was_new: bool | None,
    ) -> None:
        self.local_profile_rollback_status = rollback_status.value
        self.local_profile_rolled_back = rollback_status is LocalRollbackStatus.ROLLED_BACK
        self.public_key_installed = public_key_installed
        self.public_key_was_new = public_key_was_new
        super().__init__(_transition_warning(rollback_status))


def build_public_key_install_plan(
    public_key: str,
    *,
    token: str | None = None,
) -> PublicKeyInstallPlan:
    line = validate_public_key_line(public_key)
    parts = line.split()
    identity = f"{parts[0]} {parts[1]}"
    correlation = token or secrets.token_hex(16)
    if not TOKEN.fullmatch(correlation):
        raise ValueError("public-key install token is invalid")
    marker = f"__SERVEROPS_PUBLIC_KEY_{correlation}__:"
    encoded_line = _encoded(line)
    encoded_algorithm = _encoded(parts[0])
    encoded_blob = _encoded(parts[1])
    command = "\n".join(
        (
            "set -eu",
            "builtin umask 077",
            'command mkdir -p -- "$HOME/.ssh"',
            'command chmod 700 -- "$HOME/.ssh"',
            'command touch -- "$HOME/.ssh/authorized_keys"',
            'command chmod 600 -- "$HOME/.ssh/authorized_keys"',
            f"_serverops_key=$(builtin printf '%s' '{encoded_line}' | command base64 -d)",
            f"_serverops_alg=$(builtin printf '%s' '{encoded_algorithm}' | command base64 -d)",
            f"_serverops_blob=$(builtin printf '%s' '{encoded_blob}' | command base64 -d)",
            'if command awk -v alg="$_serverops_alg" -v blob="$_serverops_blob" '
            "'{ for (i = 1; i < NF; i++) if ($i == alg && $(i + 1) == blob) found = 1 } "
            "END { exit(found ? 0 : 1) }' \"$HOME/.ssh/authorized_keys\"; then",
            f"  builtin printf '%s\\n' '{marker}key_already_present'",
            "else",
            '  if [ -s "$HOME/.ssh/authorized_keys" ] && '
            '     [ "$(command tail -c 1 "$HOME/.ssh/authorized_keys" | '
            'command wc -l)" -eq 0 ]; then',
            '    builtin printf \'\\n\' >> "$HOME/.ssh/authorized_keys"',
            "  fi",
            '  builtin printf \'%s\\n\' "$_serverops_key" '
            '>> "$HOME/.ssh/authorized_keys"',
            '  command sync "$HOME/.ssh/authorized_keys" 2>/dev/null || true',
            f"  builtin printf '%s\\n' '{marker}key_added'",
            "fi",
            "builtin unset _serverops_key _serverops_alg _serverops_blob",
        )
    )
    return PublicKeyInstallPlan(command, marker, identity)


def _encoded(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _transition_warning(status: LocalRollbackStatus) -> str:
    if status is LocalRollbackStatus.ROLLED_BACK:
        return ROLLED_BACK_WARNING
    if status is LocalRollbackStatus.SKIPPED_CONCURRENT_CHANGE:
        first = (
            "The local profile switch was not rolled back because the local configuration "
            "changed concurrently."
        )
    else:
        first = "The local profile switch rollback could not be completed."
    return f"{first}\n\n{REMOTE_KEY_WARNING}"
