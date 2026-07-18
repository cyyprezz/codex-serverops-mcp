from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {
    "server_profiles",
    "server_profile_setup",
    "server_connection",
    "server_exec",
    "server_terminal",
    "server_files",
    "server_file_edit",
    "server_elevation",
}


async def smoke(wheel: Path, *, offline: bool) -> None:
    uvx = shutil.which("uvx")
    if uvx is None:
        raise RuntimeError("uvx is unavailable")
    with tempfile.TemporaryDirectory() as directory:
        arguments = ["--from", str(wheel.resolve()), "codex-serverops-mcp"]
        if offline:
            arguments.insert(0, "--offline")
        environment = dict(os.environ)
        environment["UV_PYTHON"] = sys.executable
        environment["UV_TOOL_DIR"] = str(Path(directory) / "uv-tools")
        environment["UV_TOOL_BIN_DIR"] = str(Path(directory) / "uv-bin")
        environment["UV_CACHE_DIR"] = str(wheel.resolve().parents[1] / ".uv-cache")
        parameters = StdioServerParameters(
            command=uvx,
            args=arguments,
            cwd=directory,
            env=environment,
        )
        async with (
            stdio_client(parameters) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
    names = {tool.name for tool in tools.tools}
    if names != EXPECTED_TOOLS:
        raise RuntimeError(
            f"Core tool surface mismatch: expected {sorted(EXPECTED_TOOLS)}, got {sorted(names)}"
        )
    print("Local wheel STDIO smoke: exact 8-tool Phase-9 surface")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    asyncio.run(smoke(args.wheel, offline=args.offline))


if __name__ == "__main__":
    main()
