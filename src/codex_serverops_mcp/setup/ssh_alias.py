from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from codex_serverops_mcp.ipc.security import secure_path_for_current_user

BEGIN_MARKER = "# >>> codex-serverops-mcp managed ssh alias >>>"
END_MARKER = "# <<< codex-serverops-mcp managed ssh alias <<<"
SAFE_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SAFE_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
SAFE_USER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
AliasValidator = Callable[[Path, "SshAliasSpec"], None]


@dataclass(frozen=True, slots=True)
class SshAliasSpec:
    alias: str
    hostname: str
    user: str
    port: int
    identity_file: Path

    def validated(self) -> SshAliasSpec:
        if not SAFE_ALIAS.fullmatch(self.alias):
            raise ValueError("SSH alias contains unsupported characters")
        if not SAFE_HOST.fullmatch(self.hostname):
            raise ValueError("SSH hostname contains unsupported characters")
        if not SAFE_USER.fullmatch(self.user):
            raise ValueError("SSH user contains unsupported characters")
        if isinstance(self.port, bool) or not 1 <= self.port <= 65_535:
            raise ValueError("SSH port is outside the valid range")
        identity = self.identity_file.expanduser().resolve()
        if not identity.is_file():
            raise ValueError("SSH identity file does not exist")
        if any(character in str(identity) for character in ('\n', '\r', '"')):
            raise ValueError("SSH identity path contains unsupported characters")
        return SshAliasSpec(self.alias, self.hostname, self.user, self.port, identity)


@dataclass(frozen=True, slots=True)
class SshAliasChange:
    previous_exists: bool
    previous: bytes
    updated: bytes
    spec: SshAliasSpec
    preview: str


@dataclass(frozen=True, slots=True)
class SshAliasApplyResult:
    config_path: Path
    backup_path: Path | None


def managed_alias_block(spec: SshAliasSpec) -> str:
    checked = spec.validated()
    identity = checked.identity_file.as_posix()
    return "\n".join(
        (
            BEGIN_MARKER,
            f"Host {checked.alias}",
            f"    HostName {checked.hostname}",
            f"    User {checked.user}",
            f"    Port {checked.port}",
            f'    IdentityFile "{identity}"',
            "    IdentitiesOnly yes",
            END_MARKER,
        )
    )


def plan_ssh_alias_change(path: Path, spec: SshAliasSpec) -> SshAliasChange:
    checked = spec.validated()
    previous_exists = path.is_file()
    previous = path.read_bytes() if previous_exists else b""
    text, encoding = _decode(previous)
    newline = "\r\n" if "\r\n" in text else "\n"
    span = _managed_span(text)
    block = managed_alias_block(checked).replace("\n", newline)
    if span is None:
        if _has_exact_alias(text, checked.alias):
            raise ValueError("an unmanaged SSH block already uses the requested alias")
        separator = "" if not text else newline if text.startswith(("\r", "\n")) else newline * 2
        updated_text = block + separator + text
    else:
        begin, end = span
        updated_text = text[:begin] + block + text[end:]
    return SshAliasChange(
        previous_exists,
        previous,
        updated_text.encode(encoding),
        checked,
        block,
    )


def apply_ssh_alias_change(
    path: Path,
    change: SshAliasChange,
    *,
    validator: AliasValidator | None = None,
    now: Callable[[], datetime] | None = None,
) -> SshAliasApplyResult:
    validate = validator or validate_ssh_alias
    _assert_current(path, change)
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = (now or (lambda: datetime.now(UTC)))().strftime("%Y%m%dT%H%M%SZ")
    backup = (
        path.with_name(f"{path.name}.serverops-backup-{timestamp}")
        if change.previous_exists
        else None
    )
    if backup is not None and backup.exists():
        backup = path.with_name(f"{backup.name}-{uuid4().hex[:8]}")
    stage = path.with_name(f".{path.name}.serverops-stage-{uuid4().hex}")
    restored = False
    replaced = False
    try:
        if backup is not None:
            _write_fsynced(backup, change.previous)
            secure_path_for_current_user(str(backup))
        _write_fsynced(stage, change.updated)
        validate(stage, change.spec)
        _assert_current(path, change)
        os.replace(stage, path)
        replaced = True
        validate(path, change.spec)
        if path.read_bytes() != change.updated:
            raise RuntimeError("SSH config changed during post-write validation")
        return SshAliasApplyResult(path, backup)
    except Exception as error:
        with suppress(OSError):
            stage.unlink()
        if replaced:
            try:
                if change.previous_exists:
                    restore = path.with_name(f".{path.name}.serverops-restore-{uuid4().hex}")
                    _write_fsynced(restore, change.previous)
                    os.replace(restore, path)
                else:
                    path.unlink(missing_ok=True)
                restored = True
            except OSError as rollback_error:
                raise RuntimeError(
                    "SSH config update failed and rollback was incomplete"
                ) from rollback_error
        status = " and was rolled back" if restored else " before replacement"
        raise RuntimeError(f"SSH config update failed{status}") from error


def validate_ssh_alias(path: Path, spec: SshAliasSpec) -> None:
    completed = subprocess.run(
        ["ssh", "-G", "-F", str(path), spec.alias],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError("OpenSSH rejected the proposed SSH config")
    values: dict[str, list[str]] = {}
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition(" ")
        if separator:
            values.setdefault(key.casefold(), []).append(value.strip())
    expected_identity = spec.identity_file.resolve()
    identities = {
        Path(value).expanduser().resolve()
        for value in values.get("identityfile", [])
        if value.casefold() != "none"
    }
    if (
        values.get("hostname", [None])[0] != spec.hostname
        or values.get("user", [None])[0] != spec.user
        or values.get("port", [None])[0] != str(spec.port)
        or values.get("identitiesonly", [None])[0] != "yes"
        or expected_identity not in identities
    ):
        raise RuntimeError("OpenSSH resolved different alias fields than requested")


def _managed_span(content: str) -> tuple[int, int] | None:
    begin_count = content.count(BEGIN_MARKER)
    end_count = content.count(END_MARKER)
    if begin_count == 0 and end_count == 0:
        return None
    if begin_count != 1 or end_count != 1:
        raise ValueError("managed SSH alias markers are ambiguous")
    begin = content.index(BEGIN_MARKER)
    end = content.index(END_MARKER, begin) + len(END_MARKER)
    return begin, end


def _has_exact_alias(content: str, alias: str) -> bool:
    expected = alias.casefold()
    for line in content.splitlines():
        stripped = line.lstrip()
        fields = stripped.split(None, 1)
        if len(fields) == 2 and fields[0].casefold() == "host":
            patterns = fields[1].split("#", 1)[0].split()
            if any(pattern.casefold() == expected for pattern in patterns):
                return True
    return False


def _decode(content: bytes) -> tuple[str, str]:
    if b"\0" in content:
        raise ValueError("SSH config contains NUL bytes")
    encoding = "utf-8-sig" if content.startswith(b"\xef\xbb\xbf") else "utf-8"
    try:
        return content.decode(encoding), encoding
    except UnicodeDecodeError as error:
        raise ValueError("SSH config must be UTF-8 text") from error


def _assert_current(path: Path, change: SshAliasChange) -> None:
    if path.is_file() != change.previous_exists:
        raise RuntimeError("SSH config changed after preview")
    if path.is_file() and path.read_bytes() != change.previous:
        raise RuntimeError("SSH config changed after preview")


def _write_fsynced(path: Path, data: bytes) -> None:
    with path.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
