from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
import zipfile
from email.parser import BytesParser
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


def wheel_version(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_files = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise RuntimeError("Candidate wheel must contain exactly one METADATA file")
        metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
    if metadata["Name"] != "codex-serverops-mcp" or not metadata["Version"]:
        raise RuntimeError("Candidate wheel has the wrong package identity")
    return str(metadata["Version"])


def manifest_arguments(manifest: Path, wheel: Path) -> list[str]:
    document = json.loads(manifest.read_text(encoding="utf-8"))
    server = document.get("mcpServers", {}).get("serverops", {})
    expected = ["--from", f"codex-serverops-mcp=={wheel_version(wheel)}", "codex-serverops-mcp"]
    if server.get("command") != "uvx" or server.get("args") != expected:
        raise RuntimeError(f"Manifest does not launch the exact candidate pin: {manifest}")
    return expected


async def smoke(
    wheel: Path,
    *,
    offline: bool,
    cache_dir: Path | None = None,
    manifest: Path | None = None,
    repeat: int = 1,
) -> None:
    uvx = shutil.which("uvx")
    if uvx is None:
        raise RuntimeError("uvx is unavailable")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        arguments = (
            ["--from", str(wheel.resolve()), "codex-serverops-mcp"]
            if manifest is None
            else manifest_arguments(manifest, wheel)
        )
        if offline and manifest is None:
            arguments.insert(0, "--offline")
        environment = dict(os.environ)
        environment["UV_PYTHON"] = sys.executable
        environment["UV_TOOL_DIR"] = str(root / "uv-tools")
        environment["UV_TOOL_BIN_DIR"] = str(root / "uv-bin")
        environment["LOCALAPPDATA"] = str(root / "local")
        environment["USERPROFILE"] = str(root / "user")
        cache_directory = cache_dir or wheel.resolve().parents[1] / ".uv-cache"
        environment["UV_CACHE_DIR"] = str(cache_directory.resolve())
        if manifest is not None:
            environment["UV_FIND_LINKS"] = str(wheel.resolve().parent)
        if offline:
            environment["UV_OFFLINE"] = "1"
        parameters = StdioServerParameters(
            command=uvx,
            args=arguments,
            cwd=directory,
            env=environment,
        )
        snapshots: list[tuple[bytes, int, bytes, int]] = []
        tools = None
        for _ in range(repeat):
            async with (
                stdio_client(parameters) as (read_stream, write_stream),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                tools = await session.list_tools()
            config = root / "local" / "codex-serverops-mcp" / "config.toml"
            state = root / "local" / "codex-serverops-mcp" / "state.json"
            snapshots.append(
                (
                    config.read_bytes(),
                    config.stat().st_mtime_ns,
                    state.read_bytes(),
                    state.stat().st_mtime_ns,
                )
            )
        app_dir = root / "local" / "codex-serverops-mcp"
        expected = {
            ".bootstrap.lock",
            "audit",
            "config.toml",
            "config.toml.lock",
            "migrations",
            "runtime",
            "state.json",
        }
        actual = {path.name for path in app_dir.iterdir()}
        if actual != expected:
            raise RuntimeError(
                f"Automatic bootstrap mismatch: expected {sorted(expected)}, got {sorted(actual)}"
            )
        if (root / "user" / ".codex").exists() or (root / "user" / ".claude").exists():
            raise RuntimeError("Automatic bootstrap changed AI-client configuration")
        if any(snapshot != snapshots[0] for snapshot in snapshots[1:]):
            raise RuntimeError("Repeated plugin start rewrote current bootstrap state")
    assert tools is not None
    names = {tool.name for tool in tools.tools}
    if names != EXPECTED_TOOLS:
        raise RuntimeError(
            f"Core tool surface mismatch: expected {sorted(EXPECTED_TOOLS)}, got {sorted(names)}"
        )
    source = "manifest pin" if manifest is not None else "local wheel"
    print(f"{source} STDIO smoke: automatic bootstrap and exact 8-tool surface")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    asyncio.run(
        smoke(
            args.wheel,
            offline=args.offline,
            cache_dir=args.cache_dir,
            manifest=args.manifest,
            repeat=args.repeat,
        )
    )


if __name__ == "__main__":
    main()
