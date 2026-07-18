from __future__ import annotations

import os
import time
import unittest


@unittest.skipUnless(os.name == "nt", "ConPTY is Windows-only")
class ConPtyTests(unittest.TestCase):
    def test_cmd_output_and_input_flow_through_conpty(self) -> None:
        from codex_serverops_mcp.terminal.conpty import ConPtyProcess

        process = ConPtyProcess()
        try:
            process.start([os.environ["COMSPEC"], "/Q", "/K"])
            process.write(b"echo __SERVEROPS_CONPTY_OK__\r\nexit\r\n")
            self.assertEqual(process.wait(5), 0)
            time.sleep(0.1)
            output = process.read(0).data.decode("utf-8", errors="replace")
            self.assertIn("__SERVEROPS_CONPTY_OK__", output)
        finally:
            process.close()


if __name__ == "__main__":
    unittest.main()

