from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from codex_serverops_mcp.application import ApplicationServices
from codex_serverops_mcp.bootstrap import ensure_local_state
from codex_serverops_mcp.tools.core import register_core_tools
from codex_serverops_mcp.tools.elevation import register_elevation_tool
from codex_serverops_mcp.tools.files import register_file_tools

SERVER_INSTRUCTIONS = (
    "ServerOps operates explicitly configured Linux servers without installing a remote agent. "
    "Start with server_profiles, understand the selected profile, and use server_profile_setup "
    "when a profile must be created or changed; secrets and host-key decisions belong only in "
    "the visible local ServerOps windows. The broker can retain SSH sessions beyond an MCP "
    "client process, so reuse the returned session_id and verify its status before continuing. "
    "Use server_exec for completed commands, server_terminal only for interactive or stateful "
    "terminal work, and the structured file tools for bounded reads and hash-protected edits. "
    "Diagnose in stages: begin read-only, narrow hypotheses with evidence, and distinguish facts, "
    "uncertainties, and changes. Shell operations run with the SSH user's real permissions; "
    "elevate only when required. Never automatically retry outcome_unknown, file_outcome_unknown, "
    "elevation_outcome_unknown, or a timed-out mutation because the remote effect may have "
    "occurred."
)


def build_server(services: ApplicationServices | None = None) -> FastMCP:
    server = FastMCP("codex-serverops-mcp", instructions=SERVER_INSTRUCTIONS)
    application = services or ApplicationServices.create()
    register_core_tools(server, application)
    register_file_tools(server, application)
    register_elevation_tool(server, application)
    return server


def main() -> None:
    ensure_local_state()
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
