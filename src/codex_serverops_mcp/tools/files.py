from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from codex_serverops_mcp.application import ApplicationServices


def register_file_tools(server: FastMCP, services: ApplicationServices) -> None:
    @server.tool(
        name="server_files",
        description=(
            "Read structured UTF-8 file data inside a profile's allowed_roots. These roots do "
            "not restrict arbitrary shell or terminal commands."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
        structured_output=True,
    )
    def server_files(
        action: Literal["list", "stat", "read_text", "search_text", "hash"],
        session_id: str,
        path: str,
        query: str | None = None,
        byte_limit: int | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        max_results: int | None = None,
    ) -> dict[str, object]:
        return services.server_files(
            action,
            session_id,
            path=path,
            query=query,
            byte_limit=byte_limit,
            start_line=start_line,
            end_line=end_line,
            max_results=max_results,
        )

    @server.tool(
        name="server_file_edit",
        description=(
            "Write, patch, create, rename or remove paths inside allowed_roots as the normal SSH "
            "user. Foreign-owned path edits are rejected."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
        structured_output=True,
    )
    def server_file_edit(
        action: Literal["write_text", "apply_patch", "mkdir", "rename", "remove"],
        session_id: str,
        path: str,
        content: str | None = None,
        patch: str | None = None,
        expected_sha256: str | None = None,
        destination_path: str | None = None,
        recursive: bool | None = None,
    ) -> dict[str, object]:
        return services.server_file_edit(
            action,
            session_id,
            path=path,
            content=content,
            patch=patch,
            expected_sha256=expected_sha256,
            destination_path=destination_path,
            recursive=recursive,
        )
