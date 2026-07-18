from __future__ import annotations

import base64
import secrets
import shlex
from dataclasses import dataclass

from codex_serverops_mcp.ssh.prompts import SUDO_PROMPT_TEXT


@dataclass(frozen=True, slots=True)
class ElevatedShellCommand:
    command: str
    begin_marker: str
    end_marker: str


def build_elevated_shell_command(
    command: str,
    *,
    non_interactive: bool,
) -> ElevatedShellCommand:
    token = secrets.token_hex(16)
    begin = f"__SERVEROPS_ELEVATED_BEGIN_{token}__"
    end = f"__SERVEROPS_ELEVATED_END_{token}__"
    encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
    arguments = " \\\n".join(
        f"  '{encoded[index : index + 512]}'"
        for index in range(0, len(encoded), 512)
    )
    root_wrapper = (
        f"printf '%s\\n' '{begin}'; "
        "bash --noprofile --norc -s; _serverops_root_exit=$?; "
        f"printf '\\n%s:%s\\n' '{end}' \"$_serverops_root_exit\"; "
        "exit \"$_serverops_root_exit\""
    )
    non_interactive_flag = "-n " if non_interactive else ""
    prompt_flag = "" if non_interactive else f"-p {shlex.quote(SUDO_PROMPT_TEXT)} "
    shell = (
        "printf '%s' \\\n"
        f"{arguments} | base64 -d | sudo {non_interactive_flag}{prompt_flag}-- "
        f"bash --noprofile --norc -c {shlex.quote(root_wrapper)}"
    )
    return ElevatedShellCommand(shell, begin, end)
