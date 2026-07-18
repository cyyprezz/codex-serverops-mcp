from __future__ import annotations

import re
from pathlib import Path
from time import monotonic

from codex_serverops_mcp.ssh.framing import ANSI_ESCAPE
from codex_serverops_mcp.terminal.conpty import ConPtyProcess

PASSPHRASE_PROMPT = re.compile(r"Enter passphrase.*?:", re.I)
CONFIRM_PROMPT = re.compile(r"Enter same passphrase again:", re.I)


def generate_protected_ed25519_key(
    ssh_keygen: Path, destination: Path, passphrase: str, *, timeout: float = 15
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    terminal = ConPtyProcess()
    terminal.start([str(ssh_keygen), "-q", "-t", "ed25519", "-f", str(destination)])
    cursor = 0
    history = ""
    sent_first = False
    sent_second = False
    deadline = monotonic() + timeout
    try:
        while monotonic() < deadline:
            result = terminal.wait_for_data(cursor, min(0.25, deadline - monotonic()))
            cursor = result.next_cursor
            history += result.data.decode("utf-8", errors="replace")
            plain = ANSI_ESCAPE.sub("", history).replace("\r", "")
            if not sent_first and PASSPHRASE_PROMPT.search(plain):
                terminal.write((passphrase + "\r\n").encode("utf-8"))
                sent_first = True
            if sent_first and not sent_second and CONFIRM_PROMPT.search(plain):
                terminal.write((passphrase + "\r\n").encode("utf-8"))
                sent_second = True
            code = terminal.wait(0)
            if code is not None:
                if code != 0:
                    raise RuntimeError(f"ssh-keygen exited with status {code}")
                if not destination.exists() or not destination.with_suffix(".pub").exists():
                    raise RuntimeError("ssh-keygen did not create both key files")
                return
        raise TimeoutError("ssh-keygen did not finish")
    finally:
        terminal.close()

