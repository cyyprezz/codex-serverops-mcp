from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_serverops_mcp.setup.keys import Ed25519KeyGenerator, OneShotSecretSource
from codex_serverops_mcp.terminal.buffer import BufferRead

PUBLIC_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHXdDb8Re7YltiXmQ3K7ZCbkGqYwRoyJSR+7JNn6sSoN "
    "serverops:test"
)


class FakeKeygenTerminal:
    def __init__(self) -> None:
        self.arguments: list[str] = []
        self.writes: list[bytes] = []
        self.prompt_index = 0
        self.running = True
        self.closed = False

    def start(self, arguments: list[str]) -> None:
        self.arguments = arguments

    def wait_for_data(self, cursor: int, timeout: float) -> BufferRead:
        del cursor, timeout
        prompts = (b"Enter passphrase", b"Enter same passphrase")
        value = prompts[self.prompt_index]
        self.prompt_index += 1
        return BufferRead(value, self.prompt_index, False)

    def write(self, value: bytes | bytearray) -> None:
        self.writes.append(bytes(value))

    def wait(self, timeout: float) -> int:
        del timeout
        target = Path(self.arguments[self.arguments.index("-f") + 1])
        target.write_text("PRIVATE TEST FIXTURE", encoding="utf-8")
        target.with_name(f"{target.name}.pub").write_text(PUBLIC_KEY, encoding="utf-8")
        self.running = False
        return 0

    def terminate(self) -> None:
        self.running = False

    def close(self) -> None:
        self.closed = True


class SetupKeyTests(unittest.TestCase):
    def test_passphrase_uses_conpty_not_arguments_and_mutable_source_is_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            terminal = FakeKeygenTerminal()
            secret = bytearray(b"local-only-secret")
            generator = Ed25519KeyGenerator(
                executable_finder=lambda: Path("ssh-keygen.exe"),
                terminal_factory=lambda: terminal,  # type: ignore[arg-type]
                user_profile=Path(temporary),
            )

            generated = generator.generate("prod", OneShotSecretSource(secret))

            self.assertEqual(generated.public_key, PUBLIC_KEY)
            self.assertEqual(terminal.writes[0], b"local-only-secret")
            self.assertEqual(terminal.writes[2], b"local-only-secret")
            self.assertNotIn("local-only-secret", repr(terminal.arguments))
            self.assertNotIn("-N", terminal.arguments)
            self.assertEqual(secret, bytearray())
            self.assertTrue(terminal.closed)

    def test_existing_destination_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "existing"
            destination.write_text("owned", encoding="utf-8")
            generator = Ed25519KeyGenerator(
                executable_finder=lambda: Path("ssh-keygen.exe"),
                terminal_factory=FakeKeygenTerminal,  # type: ignore[arg-type]
            )

            with self.assertRaises(FileExistsError):
                generator.generate(
                    "prod",
                    OneShotSecretSource(bytearray()),
                    destination=destination,
                )

            self.assertEqual(destination.read_text(encoding="utf-8"), "owned")


if __name__ == "__main__":
    unittest.main()
