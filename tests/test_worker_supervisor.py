from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "worker processes use Windows named pipes")
class WorkerSupervisorTests(unittest.TestCase):
    def test_supervisor_owns_worker_process_lifecycle(self) -> None:
        from codex_serverops_mcp.broker.supervisor import WorkerSupervisor
        from codex_serverops_mcp.ipc.security import inspect_path_security
        from codex_serverops_mcp.runtime import RuntimeDirectory

        with tempfile.TemporaryDirectory() as temporary:
            runtime = RuntimeDirectory(Path(temporary) / "runtime")
            runtime.prepare()
            supervisor = WorkerSupervisor(runtime)
            try:
                record = supervisor.start("test-profile")
                status_path = runtime.worker_status_path(record.session_id)

                self.assertNotEqual(record.worker_pid, os.getpid())
                self.assertEqual(record.state, "created")
                self.assertEqual(supervisor.get(record.session_id), record)
                self.assertEqual(supervisor.list(), (record,))
                self.assertTrue(status_path.exists())
                self.assertTrue(inspect_path_security(str(status_path)).current_user_only)

                closed = supervisor.shutdown(record.session_id)
                self.assertEqual(closed.session_id, record.session_id)
                self.assertEqual(supervisor.list(), ())
                self.assertFalse(status_path.exists())
            finally:
                supervisor.close_all()


if __name__ == "__main__":
    unittest.main()
