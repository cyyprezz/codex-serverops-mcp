from __future__ import annotations

import unittest

from codex_serverops_mcp.ssh.prompts import PromptDetector, PromptKind


class PromptDetectorTests(unittest.TestCase):
    def test_prompts_are_classified_once_across_chunk_boundaries(self) -> None:
        detector = PromptDetector()
        pieces = (
            "Are you sure you want to continue con",
            "necting (yes/no/[fingerprint])?",
            "\nserverops@host's password:",
            "\nEnter passphrase for key 'id_ed25519':",
            "\n[sudo] password for serverops:",
        )

        events = [event for piece in pieces for event in detector.feed(piece)]

        self.assertEqual(
            [event.kind for event in events],
            [
                PromptKind.HOST_KEY,
                PromptKind.PASSWORD,
                PromptKind.KEY_PASSPHRASE,
                PromptKind.SUDO_PASSWORD,
            ],
        )
        self.assertEqual(detector.feed(""), [])

    def test_sudo_prompt_is_not_duplicated_as_a_generic_password(self) -> None:
        detector = PromptDetector()
        events = detector.feed("\n[sudo] password for deploy:")
        self.assertEqual([event.kind for event in events], [PromptKind.SUDO_PASSWORD])

    def test_ready_prompt_is_detected_without_exposing_a_full_transcript(self) -> None:
        detector = PromptDetector(history_characters=1_024)
        detector.feed("noise\nbash-5.2$ ")
        self.assertTrue(detector.ready)


if __name__ == "__main__":
    unittest.main()
