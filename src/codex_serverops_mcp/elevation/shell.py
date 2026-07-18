from __future__ import annotations

import base64
import secrets
import shlex
from dataclasses import dataclass

from codex_serverops_mcp.ssh.prompts import operation_sudo_prompt


@dataclass(frozen=True, slots=True)
class ElevatedShellCommand:
    command: str
    begin_marker: str
    end_marker: str


def build_elevated_shell_command(
    command: str,
    *,
    non_interactive: bool,
    sudo_prompt_token: str | None = None,
) -> ElevatedShellCommand:
    if non_interactive != (sudo_prompt_token is None):
        raise ValueError("interactive sudo requires one operation-bound prompt token")
    token = secrets.token_hex(16)
    begin = f"__SERVEROPS_ELEVATED_BEGIN_{token}__"
    end = f"__SERVEROPS_ELEVATED_END_{token}__"
    encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
    arguments = " \\\n".join(
        f"  '{encoded[index : index + 512]}'"
        for index in range(0, len(encoded), 512)
    )
    root_wrapper = (
        f"/usr/bin/printf '%s\\n' '{begin}'; "
        "/usr/bin/env -u BASH_ENV -u ENV -u SHELLOPTS -u BASHOPTS "
        "/bin/bash --noprofile --norc -s; _serverops_root_exit=$?; "
        f"/usr/bin/printf '\\n%s:%s\\n' '{end}' \"$_serverops_root_exit\"; "
        "exit \"$_serverops_root_exit\""
    )
    non_interactive_flag = "-n " if non_interactive else ""
    prompt_flag = (
        ""
        if sudo_prompt_token is None
        else f"-p {shlex.quote(operation_sudo_prompt('elevation', sudo_prompt_token))} "
    )
    shell = (
        "builtin printf '%s' \\\n"
        f"{arguments} |\n"
        "  /bin/base64 -d |\n"
        f"  /usr/bin/sudo {non_interactive_flag}{prompt_flag}-- \\\n"
        "  /usr/bin/env -u BASH_ENV -u ENV -u SHELLOPTS -u BASHOPTS \\\n"
        f"/bin/bash --noprofile --norc -c {shlex.quote(root_wrapper)}"
    )
    return ElevatedShellCommand(shell, begin, end)
