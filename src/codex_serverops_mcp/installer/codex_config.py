from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path
from uuid import uuid4

from .errors import InstallerError

BEGIN_MARKER = "# >>> codex-serverops-mcp managed block >>>"
END_MARKER = "# <<< codex-serverops-mcp managed block <<<"
SERVER_TABLE = "[mcp_servers.serverops]"
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]{0,63}$")
DEVELOPMENT_VERSION_PREFIX = "# Development wheel version: "


@dataclass(frozen=True, slots=True)
class CodexConfigChange:
    previous_exists: bool
    previous: str
    updated: str
    preview: str


def managed_block(
    distribution_version: str,
    *,
    development_wheel: Path | None = None,
    development_python: Path | None = None,
) -> str:
    if not VERSION.fullmatch(distribution_version):
        raise InstallerError("the distribution version is not safe for a pinned uvx command")
    if development_wheel is not None:
        return _development_wheel_block(
            distribution_version,
            development_wheel,
            development_python,
        )
    if development_python is not None:
        raise InstallerError("a development Python requires a development wheel")
    return "\n".join(
        (
            BEGIN_MARKER,
            SERVER_TABLE,
            'command = "uvx"',
            (
                'args = ["--from", "codex-serverops-mcp=='
                + distribution_version
                + '", "codex-serverops-mcp"]'
            ),
            "startup_timeout_sec = 60",
            "tool_timeout_sec = 3730",
            END_MARKER,
        )
    )


def parse_codex_config(content: str) -> dict[str, object]:
    if not content.strip():
        return {}
    try:
        return tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        raise InstallerError("the user Codex configuration is not valid TOML") from error


def plan_codex_config_change(
    path: Path,
    distribution_version: str,
    *,
    remove: bool = False,
    development_wheel: Path | None = None,
    development_python: Path | None = None,
) -> CodexConfigChange:
    if remove and (development_wheel is not None or development_python is not None):
        raise InstallerError("development runtime options cannot be combined with removal")
    previous_exists = path.exists()
    try:
        previous = path.read_text(encoding="utf-8") if previous_exists else ""
    except OSError as error:
        raise InstallerError("the user Codex configuration could not be read") from error
    parsed = parse_codex_config(previous)
    span = _managed_span(previous)
    if span is None:
        servers = parsed.get("mcp_servers")
        if isinstance(servers, dict) and "serverops" in servers:
            raise InstallerError(
                "an unmarked [mcp_servers.serverops] entry exists and was not changed"
            )
        if remove:
            raise InstallerError("no installer-managed Codex configuration block exists")
        block = managed_block(
            distribution_version,
            development_wheel=development_wheel,
            development_python=development_python,
        )
        separator = "" if not previous else "\n" if previous.endswith("\n") else "\n\n"
        updated = previous + separator + block + "\n"
        preview = block
    else:
        begin, end = span
        if remove:
            updated = (previous[:begin] + previous[end:]).strip("\n")
            if updated:
                updated += "\n"
            preview = "Remove the installer-managed [mcp_servers.serverops] block."
        else:
            block = managed_block(
                distribution_version,
                development_wheel=development_wheel,
                development_python=development_python,
            )
            updated = previous[:begin] + block + previous[end:]
            preview = block
    parse_codex_config(updated)
    return CodexConfigChange(previous_exists, previous, updated, preview)


def apply_codex_config_change(path: Path, change: CodexConfigChange) -> None:
    _assert_current(path, change)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(path.name + ".codex-serverops-mcp.backup")
    backup_stage = path.with_name(f".{path.name}.backup-{uuid4().hex}")
    stage = path.with_name(f".{path.name}.stage-{uuid4().hex}")
    had_previous = path.exists()
    replaced = False
    try:
        if had_previous:
            _write_fsynced(backup_stage, change.previous.encode("utf-8"))
            os.replace(backup_stage, backup)
        _write_fsynced(stage, change.updated.encode("utf-8"))
        parse_codex_config(stage.read_text(encoding="utf-8"))
        _assert_current(path, change)
        os.replace(stage, path)
        replaced = True
        parse_codex_config(path.read_text(encoding="utf-8"))
    except Exception as error:
        for temporary in (backup_stage, stage):
            with suppress(OSError):
                temporary.unlink()
        try:
            if replaced and had_previous and backup.exists():
                restore = path.with_name(f".{path.name}.restore-{uuid4().hex}")
                _write_fsynced(restore, backup.read_bytes())
                os.replace(restore, path)
            elif replaced and not had_previous:
                path.unlink(missing_ok=True)
        except OSError as rollback_error:
            raise InstallerError(
                "the Codex configuration update failed and rollback was incomplete"
            ) from rollback_error
        raise InstallerError("the Codex configuration update failed and was rolled back") from error


def inspect_managed_version(path: Path) -> str | None:
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    parse_codex_config(content)
    span = _managed_span(content)
    if span is None:
        return None
    block = content[slice(*span)]
    match = re.search(r'"codex-serverops-mcp==([^"\r\n]+)"', block)
    if match is not None:
        return match.group(1)
    development_match = re.search(
        rf"^{re.escape(DEVELOPMENT_VERSION_PREFIX)}([^\r\n]+)$",
        block,
        re.MULTILINE,
    )
    if development_match is not None and VERSION.fullmatch(development_match.group(1)):
        return development_match.group(1)
    raise InstallerError("the managed Codex block has no exact package pin")


def _development_wheel_block(
    distribution_version: str,
    wheel: Path,
    python: Path | None,
) -> str:
    resolved_wheel = wheel.expanduser().resolve()
    _validate_development_wheel(resolved_wheel, distribution_version)
    resolved_python = _validate_development_python(python)
    uvx = shutil.which("uvx")
    if uvx is None:
        raise InstallerError("uvx is required for a development-wheel MCP configuration")
    command = _toml_string(str(Path(uvx).resolve()))
    python_argument = _toml_string(str(resolved_python))
    wheel_argument = _toml_string(str(resolved_wheel))
    return "\n".join(
        (
            BEGIN_MARKER,
            DEVELOPMENT_VERSION_PREFIX + distribution_version,
            SERVER_TABLE,
            f"command = {command}",
            (
                f'args = ["--python", {python_argument}, "--offline", '
                f'"--from", {wheel_argument}, "codex-serverops-mcp"]'
            ),
            "startup_timeout_sec = 60",
            "tool_timeout_sec = 3730",
            END_MARKER,
        )
    )


def _validate_development_wheel(wheel: Path, distribution_version: str) -> None:
    if not wheel.is_file() or wheel.suffix.casefold() != ".whl":
        raise InstallerError("the development wheel must be an existing .whl file")
    try:
        with zipfile.ZipFile(wheel) as archive:
            metadata_names = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                raise InstallerError("the development wheel has ambiguous package metadata")
            metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise InstallerError("the development wheel could not be validated") from error
    if metadata.get("Name") != "codex-serverops-mcp":
        raise InstallerError("the development wheel has the wrong package name")
    if metadata.get("Version") != distribution_version:
        raise InstallerError("the development wheel version does not match this installer")


def _validate_development_python(python: Path | None) -> Path:
    if python is None:
        raise InstallerError("a development wheel requires an explicit Python 3.12 executable")
    resolved = python.expanduser().resolve()
    if not resolved.is_file():
        raise InstallerError("the development Python executable does not exist")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run(
            [
                str(resolved),
                "-I",
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise InstallerError("the development Python executable could not be verified") from error
    if result.stdout.strip() != "3.12":
        raise InstallerError("the development Python executable must be Python 3.12")
    return resolved


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _managed_span(content: str) -> tuple[int, int] | None:
    begin_count = content.count(BEGIN_MARKER)
    end_count = content.count(END_MARKER)
    if begin_count == 0 and end_count == 0:
        return None
    if begin_count != 1 or end_count != 1:
        raise InstallerError("the managed Codex configuration markers are ambiguous")
    begin = content.index(BEGIN_MARKER)
    end = content.index(END_MARKER, begin) + len(END_MARKER)
    if SERVER_TABLE not in content[begin:end]:
        raise InstallerError("the managed Codex configuration block is malformed")
    return begin, end


def _assert_current(path: Path, change: CodexConfigChange) -> None:
    if path.exists() != change.previous_exists:
        raise InstallerError("the Codex configuration changed after preview; generate it again")
    if path.exists() and path.read_text(encoding="utf-8") != change.previous:
        raise InstallerError("the Codex configuration changed after preview; generate it again")


def _write_fsynced(path: Path, data: bytes) -> None:
    with path.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
