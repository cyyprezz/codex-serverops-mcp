from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from codex_serverops_mcp.application import ApplicationServices


def register_core_tools(server: FastMCP, services: ApplicationServices) -> None:
    @server.tool(
        name="server_profiles",
        description="List or inspect non-secret local ServerOps profiles.",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    def server_profiles(
        action: Literal["list", "inspect"],
        profile_name: str | None = None,
    ) -> dict[str, object]:
        return services.server_profiles(action, profile_name)

    @server.tool(
        name="server_profile_setup",
        description=(
            "Open or poll the separate local server-profile setup assistant. Authentication "
            "secrets remain outside MCP; add, edit, remove and test require local interaction."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
        structured_output=True,
    )
    def server_profile_setup(
        action: Literal["add", "edit", "remove", "test", "status", "wait"],
        profile_name: str | None = None,
        suggested_host: str | None = None,
        suggested_user: str | None = None,
        request_id: str | None = None,
        wait_timeout: float | None = None,
    ) -> dict[str, object]:
        return services.server_profile_setup(
            action,
            profile_name=profile_name,
            suggested_host=suggested_host,
            suggested_user=suggested_user,
            request_id=request_id,
            wait_timeout=wait_timeout,
        )

    @server.tool(
        name="server_connection",
        description="Open, rediscover, inspect, list or close broker-owned SSH sessions.",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
        structured_output=True,
    )
    def server_connection(
        action: Literal["open", "status", "list", "reconnect", "close"],
        profile_name: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        return services.server_connection(
            action,
            profile_name=profile_name,
            session_id=session_id,
        )

    @server.tool(
        name="server_exec",
        description=(
            "Run one completed Bash command in a held SSH shell. This may change the remote "
            "server and an outcome_unknown result is never retried automatically."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
        structured_output=True,
    )
    def server_exec(
        session_id: str,
        command: str,
        timeout: float | None = None,
    ) -> dict[str, object]:
        return services.server_exec(session_id, command, timeout=timeout)

    @server.tool(
        name="server_terminal",
        description=(
            "Control an interactive command in a held SSH shell. Input is arbitrary and may "
            "change the remote server."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
        structured_output=True,
    )
    def server_terminal(
        action: Literal["start", "read", "write", "interrupt", "resize", "status", "close"],
        session_id: str,
        command: str | None = None,
        cursor: int | None = None,
        text: str | None = None,
        columns: int | None = None,
        rows: int | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        return services.server_terminal(
            action,
            session_id,
            command=command,
            cursor=cursor,
            text=text,
            columns=columns,
            rows=rows,
            timeout=timeout,
        )
