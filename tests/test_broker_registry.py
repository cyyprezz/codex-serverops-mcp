from __future__ import annotations

import unittest

from codex_serverops_mcp.broker.errors import BrokerRequestError, SessionNotFound
from codex_serverops_mcp.broker.model import SessionRecord
from codex_serverops_mcp.broker.registry import SessionRegistry


def _record(session_id: str, *, created_at: float) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        profile_name="test-profile",
        worker_pid=1234,
        worker_pipe=r"\\.\pipe\codex-serverops-test",
        state="created",
        created_at=created_at,
        last_activity=created_at,
    )


class SessionRegistryTests(unittest.TestCase):
    def test_registry_adds_lists_replaces_and_removes_records(self) -> None:
        registry = SessionRegistry()
        later = _record("sess-0000000000000002", created_at=2)
        earlier = _record("sess-0000000000000001", created_at=1)

        registry.add(later)
        registry.add(earlier)
        self.assertEqual(registry.list(), (earlier, later))

        lost = earlier.with_state("lost", at=3)
        registry.replace(lost)
        self.assertEqual(registry.get(earlier.session_id), lost)
        self.assertEqual(registry.remove(earlier.session_id), lost)
        self.assertEqual(registry.list(), (later,))

    def test_registry_rejects_duplicates_and_unknown_sessions(self) -> None:
        registry = SessionRegistry()
        record = _record("sess-0000000000000001", created_at=1)
        registry.add(record)

        with self.assertRaises(BrokerRequestError):
            registry.add(record)
        with self.assertRaises(SessionNotFound):
            registry.get("sess-0000000000000002")
        with self.assertRaises(SessionNotFound):
            registry.replace(_record("sess-0000000000000002", created_at=2))
        with self.assertRaises(SessionNotFound):
            registry.remove("sess-0000000000000002")


if __name__ == "__main__":
    unittest.main()
