from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from codex_serverops_mcp.application import ApplicationServices


def register_elevation_tool(server: FastMCP, services: ApplicationServices) -> None:
    @server.tool(
        name="server_elevation",
        description=(
            "Acquire, inspect or release guided sudo, run one elevated command, or manage a "
            "separate root session. elevation_mode is not a server-side sudo restriction."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
        structured_output=True,
    )
    def server_elevation(
        action: Literal[
            "acquire",
            "status",
            "release",
            "exec",
            "open_root_session",
            "close_root_session",
        ],
        session_id: str,
        command: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        return services.server_elevation(
            action,
            session_id,
            command=command,
            timeout=timeout,
        )
