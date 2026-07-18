from __future__ import annotations

import sys
import unittest
from pathlib import Path

from codex_serverops_mcp.broker.task_model import BrokerTaskSpec, BrokerTaskStatus
from scripts.manage_broker_test_task import status_matches_spec


class BrokerTestTaskTests(unittest.TestCase):
    def test_exact_action_match_is_required_for_guarded_cleanup(self) -> None:
        spec = BrokerTaskSpec(
            executable=Path(sys.executable),
            arguments=("--offline", "--from", "candidate.whl", "serverops-broker"),
            source="development-wheel:candidate.whl",
        )
        matching = BrokerTaskStatus(
            name="test",
            exists=True,
            managed=True,
            running=False,
            executable=str(Path(sys.executable)),
            arguments=spec.argument_line,
        )
        changed = BrokerTaskStatus(
            name="test",
            exists=True,
            managed=True,
            running=False,
            executable=str(Path(sys.executable)),
            arguments="different action",
        )

        self.assertTrue(status_matches_spec(matching, spec))
        self.assertFalse(status_matches_spec(changed, spec))


if __name__ == "__main__":
    unittest.main()
