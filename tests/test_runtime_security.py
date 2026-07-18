from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "secured runtime paths are Windows-only")
class RuntimeSecurityTests(unittest.TestCase):
    def test_existing_owner_does_not_need_write_owner_to_harden_openssh_style_file(
        self,
    ) -> None:
        import ntsecuritycon
        import win32security

        from codex_serverops_mcp.ipc.security import (
            current_user_sid,
            inspect_path_security,
            secure_path_for_current_user,
        )

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "openssh-created-key"
            path.write_text("test fixture", encoding="utf-8")
            sid = current_user_sid()
            restricted = win32security.ACL()
            restricted.AddAccessAllowedAceEx(
                win32security.ACL_REVISION_DS,
                0,
                ntsecuritycon.FILE_GENERIC_READ | ntsecuritycon.FILE_GENERIC_WRITE,
                sid,
            )
            win32security.SetNamedSecurityInfo(
                str(path),
                win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION,
                None,
                None,
                restricted,
                None,
            )

            secure_path_for_current_user(str(path))

            self.assertTrue(inspect_path_security(str(path)).current_user_only)

    def test_runtime_directories_and_status_files_are_current_user_only(self) -> None:
        from codex_serverops_mcp.ipc.security import inspect_path_security
        from codex_serverops_mcp.runtime import RuntimeDirectory

        with tempfile.TemporaryDirectory() as temporary:
            runtime = RuntimeDirectory(Path(temporary) / "runtime")
            runtime.prepare()
            runtime.write_json(runtime.broker_status_path, {"status": "ok"})

            self.assertTrue(inspect_path_security(str(runtime.path)).current_user_only)
            self.assertTrue(inspect_path_security(str(runtime.workers_path)).current_user_only)
            self.assertTrue(
                inspect_path_security(str(runtime.broker_status_path)).current_user_only
            )
            self.assertEqual(runtime.read_json(runtime.broker_status_path), {"status": "ok"})

    def test_runtime_rejects_unsafe_session_ids_and_duplicate_fields(self) -> None:
        from codex_serverops_mcp.runtime import RuntimeDirectory

        with tempfile.TemporaryDirectory() as temporary:
            runtime = RuntimeDirectory(Path(temporary) / "runtime")
            runtime.prepare()
            with self.assertRaises(ValueError):
                runtime.worker_status_path("../outside")

            runtime.broker_status_path.write_text('{"pid":1,"pid":2}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate runtime status field"):
                runtime.read_json(runtime.broker_status_path)

    def test_stale_cleanup_removes_only_certainly_dead_process_records(self) -> None:
        from codex_serverops_mcp.runtime import RuntimeDirectory

        with tempfile.TemporaryDirectory() as temporary:
            runtime = RuntimeDirectory(Path(temporary) / "runtime")
            runtime.prepare()
            runtime.write_json(runtime.broker_status_path, {"pid": 111})
            dead = runtime.worker_status_path("sess-0000000000000001")
            live = runtime.worker_status_path("sess-0000000000000002")
            unreadable = runtime.worker_status_path("sess-0000000000000003")
            runtime.write_json(dead, {"pid": 111})
            runtime.write_json(live, {"pid": 222})
            runtime.write_json(unreadable, {"pid": "invalid"})

            cleanup = runtime.clean_stale_statuses(
                process_is_alive=lambda pid: pid == 222,
            )

            self.assertTrue(cleanup.broker_status_removed)
            self.assertEqual(cleanup.dead_worker_statuses_removed, (dead.name,))
            self.assertEqual(cleanup.live_worker_statuses_preserved, (live.name,))
            self.assertEqual(
                cleanup.unreadable_worker_statuses_preserved,
                (unreadable.name,),
            )
            self.assertFalse(runtime.broker_status_path.exists())
            self.assertFalse(dead.exists())
            self.assertTrue(live.exists())
            self.assertTrue(unreadable.exists())


if __name__ == "__main__":
    unittest.main()
