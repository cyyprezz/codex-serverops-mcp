from __future__ import annotations

import asyncio
import json
import unittest

from codex_serverops_mcp.server import build_server


class FakeApplicationServices:
    def server_profiles(self, action: str, profile_name: str | None = None):
        return {"action": action, "profile_name": profile_name}

    def server_connection(self, action: str, **parameters: object):
        return {"action": action, **parameters}

    def server_profile_setup(self, action: str, **parameters: object):
        return {"action": action, **parameters}

    def server_exec(self, session_id: str, command: str, *, timeout: float | None = None):
        return {"session_id": session_id, "command": command, "timeout": timeout}

    def server_terminal(self, action: str, session_id: str, **parameters: object):
        return {"action": action, "session_id": session_id, **parameters}

    def server_files(self, action: str, session_id: str, **parameters: object):
        return {"action": action, "session_id": session_id, **parameters}

    def server_file_edit(self, action: str, session_id: str, **parameters: object):
        return {"action": action, "session_id": session_id, **parameters}

    def server_elevation(self, action: str, session_id: str, **parameters: object):
        return {"action": action, "session_id": session_id, **parameters}


class CoreToolSurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = build_server(FakeApplicationServices())
        self.tools = {
            tool.name: tool for tool in asyncio.run(self.server.list_tools())
        }

    def test_phase_nine_surface_is_exactly_eight_coherent_tools(self) -> None:
        self.assertEqual(
            set(self.tools),
            {
                "server_profiles",
                "server_profile_setup",
                "server_connection",
                "server_exec",
                "server_terminal",
                "server_files",
                "server_file_edit",
                "server_elevation",
            },
        )
        schemas = json.dumps(
            {name: tool.inputSchema for name, tool in self.tools.items()},
            sort_keys=True,
        ).lower()
        for forbidden in ("password", "passphrase", "private_key_content", "sudo_password"):
            self.assertNotIn(forbidden, schemas)

    def test_annotations_are_conservative_for_remote_reads_and_writes(self) -> None:
        profile_annotations = self.tools["server_profiles"].annotations
        self.assertTrue(profile_annotations.readOnlyHint)
        self.assertFalse(profile_annotations.destructiveHint)
        file_read_annotations = self.tools["server_files"].annotations
        self.assertTrue(file_read_annotations.readOnlyHint)
        self.assertFalse(file_read_annotations.destructiveHint)
        self.assertTrue(file_read_annotations.openWorldHint)
        for name in (
            "server_profile_setup",
            "server_connection",
            "server_exec",
            "server_terminal",
            "server_file_edit",
            "server_elevation",
        ):
            annotations = self.tools[name].annotations
            self.assertFalse(annotations.readOnlyHint)
            self.assertTrue(annotations.destructiveHint)
            self.assertTrue(annotations.openWorldHint)

    def test_action_enums_and_required_fields_are_fixed_in_schema(self) -> None:
        self.assertEqual(
            self.tools["server_profile_setup"].inputSchema["properties"]["action"]["enum"],
            ["add", "edit", "remove", "test", "status", "wait"],
        )
        self.assertEqual(
            self.tools["server_connection"].inputSchema["properties"]["action"]["enum"],
            ["open", "status", "list", "rediscover", "close"],
        )
        self.assertEqual(
            self.tools["server_terminal"].inputSchema["properties"]["action"]["enum"],
            ["start", "read", "write", "interrupt", "resize", "status", "close"],
        )
        self.assertEqual(
            self.tools["server_files"].inputSchema["properties"]["action"]["enum"],
            ["list", "stat", "read_text", "search_text", "hash"],
        )
        self.assertEqual(
            self.tools["server_file_edit"].inputSchema["properties"]["action"]["enum"],
            ["write_text", "apply_patch", "mkdir", "rename", "remove"],
        )
        self.assertEqual(
            self.tools["server_elevation"].inputSchema["properties"]["action"]["enum"],
            [
                "acquire",
                "status",
                "release",
                "exec",
                "open_root_session",
                "close_root_session",
            ],
        )
        self.assertEqual(
            self.tools["server_exec"].inputSchema["required"],
            ["session_id", "command"],
        )

    def test_fastmcp_dispatches_to_thin_application_adapter(self) -> None:
        result = asyncio.run(
            self.server.call_tool(
                "server_exec",
                {
                    "session_id": "sess-0123456789abcdef",
                    "command": "pwd",
                    "timeout": 5,
                },
            )
        )

        _content, structured = result
        self.assertEqual(structured["command"], "pwd")
        self.assertEqual(structured["timeout"], 5)


if __name__ == "__main__":
    unittest.main()
