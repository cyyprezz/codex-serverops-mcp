from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import shutil
import sys
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from codex_serverops_mcp.application import ApplicationServices
from codex_serverops_mcp.broker.client import BrokerClient
from codex_serverops_mcp.broker.errors import BrokerUnavailable


def verify_restart_state(
    session_id: str,
    listed: dict[str, object],
    status: dict[str, object],
    pwd: dict[str, object],
    rediscovery: dict[str, object],
    expected_cwd: str,
) -> None:
    sessions = listed.get("sessions")
    if not isinstance(sessions, list):
        raise AssertionError("restarted MCP returned no session list")
    matching = [
        item
        for item in sessions
        if isinstance(item, dict) and item.get("session_id") == session_id
    ]
    if len(matching) != 1:
        raise AssertionError("restarted MCP did not rediscover exactly one held session")
    if status.get("session_id") != session_id or status.get("state") != "ready":
        raise AssertionError("rediscovered session was not ready")
    if str(pwd.get("output", "")).strip() != expected_cwd:
        raise AssertionError("held Bash cwd did not survive MCP restart")
    if (
        rediscovery.get("rediscovered") is not True
        or rediscovery.get("command_retried") is not False
    ):
        raise AssertionError("MCP restart rediscovery did not preserve the no-retry contract")


async def run_check(wheel: Path, profile_name: str, expected_cwd: str) -> dict[str, object]:
    wheel = wheel.resolve()
    if not wheel.is_file():
        raise RuntimeError("wheel does not exist")
    uvx = shutil.which("uvx")
    if uvx is None:
        raise RuntimeError("uvx is unavailable")
    _shutdown_idle_broker()
    session_id: str | None = None
    closed = False
    with tempfile.TemporaryDirectory() as directory:
        parameters = _parameters(uvx, wheel, Path(directory))
        try:
            async with _mcp_session(parameters) as first:
                opened = await _call(
                    first,
                    "server_connection",
                    {"action": "open", "profile_name": profile_name},
                )
                session_id = _required_text(opened, "session_id")
                changed = await _call(
                    first,
                    "server_exec",
                    {
                        "session_id": session_id,
                        "command": f"cd -- {shlex.quote(expected_cwd)}",
                    },
                )
                if changed.get("status") != "completed" or changed.get("exit_code") != 0:
                    raise AssertionError("first MCP could not establish the held cwd")
                marker = await _call(
                    first,
                    "server_exec",
                    {"session_id": session_id, "command": "printf before-mcp-restart"},
                )
                if marker.get("output") != "before-mcp-restart":
                    raise AssertionError("first MCP command did not complete exactly once")

            async with _mcp_session(parameters) as second:
                listed = await _call(second, "server_connection", {"action": "list"})
                status = await _call(
                    second,
                    "server_connection",
                    {"action": "status", "session_id": session_id},
                )
                pwd = await _call(
                    second,
                    "server_exec",
                    {"session_id": session_id, "command": "pwd"},
                )
                rediscovery = await _call(
                    second,
                    "server_connection",
                    {"action": "rediscover", "session_id": session_id},
                )
                verify_restart_state(session_id, listed, status, pwd, rediscovery, expected_cwd)
                await _call(
                    second,
                    "server_connection",
                    {"action": "close", "session_id": session_id},
                )
                closed = True
        finally:
            if session_id is not None and not closed:
                with suppress(Exception):
                    ApplicationServices.create().server_connection("close", session_id=session_id)
            _shutdown_idle_broker()
    return {
        "status": "passed",
        "profile": profile_name,
        "checks": [
            "first_checkout_free_mcp_opened_session",
            "mcp_process_restarted",
            "broker_session_rediscovered",
            "held_bash_state_survived",
            "command_retried_false",
            "session_and_broker_cleanup",
        ],
    }


def _parameters(uvx: str, wheel: Path, directory: Path) -> StdioServerParameters:
    environment = dict(os.environ)
    environment["UV_PYTHON"] = sys.executable
    environment["UV_TOOL_DIR"] = str(directory / "uv-tools")
    environment["UV_TOOL_BIN_DIR"] = str(directory / "uv-bin")
    environment["UV_CACHE_DIR"] = str(wheel.parents[1] / ".uv-cache")
    return StdioServerParameters(
        command=uvx,
        args=["--offline", "--from", str(wheel), "codex-serverops-mcp"],
        cwd=str(directory),
        env=environment,
    )


@asynccontextmanager
async def _mcp_session(
    parameters: StdioServerParameters,
) -> AsyncIterator[ClientSession]:
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        yield session


async def _call(
    session: ClientSession,
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    result = await session.call_tool(name, arguments)
    if result.isError:
        message = " ".join(
            str(getattr(content, "text", "")) for content in result.content
        ).strip()
        raise RuntimeError(f"MCP tool {name} failed: {message or 'controlled tool error'}")
    structured = result.structuredContent
    if not isinstance(structured, dict):
        raise RuntimeError(f"MCP tool {name} returned no structured object")
    return structured


def _required_text(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"MCP result has no valid {field}")
    return value


def _shutdown_idle_broker() -> None:
    try:
        with BrokerClient() as client:
            sessions = client.request("session.list").get("sessions")
            if sessions:
                raise RuntimeError("refusing to stop a broker with active sessions")
            client.request("broker.shutdown")
    except BrokerUnavailable:
        return
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with BrokerClient():
                time.sleep(0.05)
        except BrokerUnavailable:
            return
    raise RuntimeError("broker did not stop after the shutdown request")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--expected-cwd", required=True)
    args = parser.parse_args()
    result = asyncio.run(run_check(args.wheel, args.profile, args.expected_cwd))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
