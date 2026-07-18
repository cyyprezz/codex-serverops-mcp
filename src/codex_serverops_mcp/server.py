from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from codex_serverops_mcp.application import ApplicationServices
from codex_serverops_mcp.tools.core import register_core_tools
from codex_serverops_mcp.tools.elevation import register_elevation_tool
from codex_serverops_mcp.tools.files import register_file_tools

SERVER_INSTRUCTIONS = (
    "ServerOps MCP operates deliberately configured Linux servers through held SSH shells. "
    "Shell and terminal operations run with the selected SSH user's privileges and may mutate "
    "the remote system. Local warnings do not replace backups, restricted accounts, file "
    "permissions or server-side sudoers policy."
)


def build_server(services: ApplicationServices | None = None) -> FastMCP:
    server = FastMCP("codex-serverops-mcp", instructions=SERVER_INSTRUCTIONS)
    application = services or ApplicationServices.create()
    register_core_tools(server, application)
    register_file_tools(server, application)
    register_elevation_tool(server, application)
    return server


def main() -> None:
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
