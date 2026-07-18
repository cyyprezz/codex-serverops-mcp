from __future__ import annotations

import base64
import binascii
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from codex_serverops_mcp.config.model import validate_profile_name
from codex_serverops_mcp.ipc.security import secure_path_for_current_user
from codex_serverops_mcp.terminal.conpty import ConPtyProcess

KEYGEN_TIMEOUT_SECONDS = 30


class SecretSource(Protocol):
    def take(self) -> bytearray: ...


class OneShotSecretSource:
    """Owns a mutable local-UI secret until a key generator consumes it once."""

    def __init__(self, value: bytearray) -> None:
        self._value = value

    def take(self) -> bytearray:
        value = self._value
        self._value = bytearray()
        return value


@dataclass(frozen=True, slots=True)
class GeneratedKey:
    private_key_path: Path
    public_key_path: Path
    public_key: str


class Ed25519KeyGenerator:
    def __init__(
        self,
        *,
        executable_finder: Callable[[], Path] | None = None,
        terminal_factory: Callable[[], ConPtyProcess] = ConPtyProcess,
        user_profile: Path | None = None,
    ) -> None:
        self.executable_finder = executable_finder or find_windows_ssh_keygen
        self.terminal_factory = terminal_factory
        self.user_profile = user_profile

    def generate(
        self,
        profile_name: str,
        secret_source: SecretSource,
        *,
        destination: Path | None = None,
    ) -> GeneratedKey:
        validate_profile_name(profile_name)
        target = (destination or self._default_path(profile_name)).resolve()
        public_path = target.with_name(f"{target.name}.pub")
        if target.exists() or public_path.exists():
            raise FileExistsError("the selected SSH key path already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        secure_path_for_current_user(str(target.parent), directory=True)
        secret = secret_source.take()
        terminal = self.terminal_factory()
        try:
            terminal.start(
                [
                    str(self.executable_finder()),
                    "-q",
                    "-t",
                    "ed25519",
                    "-f",
                    str(target),
                    "-C",
                    f"serverops:{profile_name}",
                ]
            )
            self._answer_prompt(terminal, b"Enter passphrase", secret)
            self._answer_prompt(terminal, b"Enter same passphrase", secret)
            exit_code = terminal.wait(timeout=KEYGEN_TIMEOUT_SECONDS)
            if exit_code is None:
                terminal.terminate()
                raise TimeoutError("ssh-keygen did not finish before the local timeout")
            if exit_code != 0:
                raise RuntimeError("ssh-keygen did not create the Ed25519 key")
            if not target.is_file() or not public_path.is_file():
                raise RuntimeError("ssh-keygen completed without both key files")
            secure_path_for_current_user(str(target))
            secure_path_for_current_user(str(public_path))
            public_key = read_public_key(public_path)
            return GeneratedKey(target, public_path, public_key)
        except BaseException:
            target.unlink(missing_ok=True)
            public_path.unlink(missing_ok=True)
            raise
        finally:
            secret[:] = b"\0" * len(secret)
            secret.clear()
            terminal.close()

    def _default_path(self, profile_name: str) -> Path:
        return default_private_key_path(profile_name, user_profile=self.user_profile)

    @staticmethod
    def _answer_prompt(terminal: ConPtyProcess, marker: bytes, secret: bytearray) -> None:
        deadline = time.monotonic() + KEYGEN_TIMEOUT_SECONDS
        cursor = 0
        observed = bytearray()
        while time.monotonic() < deadline:
            chunk = terminal.wait_for_data(cursor, timeout=0.1)
            cursor = chunk.next_cursor
            observed.extend(chunk.data)
            if len(observed) > 4_096:
                del observed[:-4_096]
            if marker in observed:
                terminal.write(secret)
                terminal.write(b"\r")
                return
            if not terminal.running:
                break
        raise RuntimeError("ssh-keygen ended before its local passphrase prompt")


def find_windows_ssh_keygen() -> Path:
    executable = shutil.which("ssh-keygen.exe") or shutil.which("ssh-keygen")
    if executable:
        return Path(executable).resolve()
    system_root = os.environ.get("SYSTEMROOT")
    if system_root:
        candidate = Path(system_root) / "System32" / "OpenSSH" / "ssh-keygen.exe"
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("Windows OpenSSH ssh-keygen.exe was not found")


def default_private_key_path(profile_name: str, *, user_profile: Path | None = None) -> Path:
    validate_profile_name(profile_name)
    root = user_profile
    if root is None:
        value = os.environ.get("USERPROFILE")
        if not value:
            raise RuntimeError("USERPROFILE is unavailable")
        root = Path(value)
    return root / ".ssh" / "serverops" / f"{profile_name}_ed25519"


def read_public_key(path: Path) -> str:
    content = path.read_bytes()
    if not content or len(content) > 16_384:
        raise ValueError("the public SSH key has an invalid size")
    try:
        text = content.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise ValueError("the public SSH key must be UTF-8 text") from error
    return validate_public_key_line(text)


def validate_public_key_line(text: str) -> str:
    if not text or len(text) > 16_384 or text != text.strip():
        raise ValueError("the public SSH key must be one trimmed line")
    if any(ord(character) < 32 for character in text):
        raise ValueError("the public SSH key contains a control character")
    parts = text.split()
    supported = {"ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256"}
    if len(parts) < 2 or parts[0] not in supported:
        raise ValueError("the selected file is not a supported OpenSSH public key")
    try:
        blob = base64.b64decode(parts[1].encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as error:
        raise ValueError("the OpenSSH public key payload is not valid base64") from error
    if len(blob) < 8 or len(blob) > 8_192:
        raise ValueError("the OpenSSH public key payload has an invalid size")
    algorithm_size = int.from_bytes(blob[:4], "big")
    algorithm = blob[4 : 4 + algorithm_size]
    if algorithm != parts[0].encode("ascii"):
        raise ValueError("the OpenSSH public key type does not match its payload")
    return text
