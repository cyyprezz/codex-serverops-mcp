from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.artifact_checksums import create_manifest, verify_manifest


class ArtifactChecksumTests(unittest.TestCase):
    def test_manifest_is_sorted_reproducible_and_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = root / "codex_serverops_mcp-0.1.1-py3-none-any.whl"
            source = root / "codex_serverops_mcp-0.1.1.tar.gz"
            manifest = root / "checksums" / "SHA256SUMS.txt"
            wheel.write_bytes(b"wheel")
            source.write_bytes(b"source")

            create_manifest([source, wheel], manifest)
            first = manifest.read_bytes()
            create_manifest([wheel, source], manifest)

            self.assertEqual(manifest.read_bytes(), first)
            self.assertEqual(
                set(verify_manifest(manifest, root)),
                {wheel.name, source.name},
            )
            wheel.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                verify_manifest(manifest, root)

    def test_manifest_rejects_wrong_artifact_set_and_unsafe_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = root / "candidate.whl"
            wheel.write_bytes(b"wheel")
            with self.assertRaisesRegex(ValueError, "one wheel and one source"):
                create_manifest([wheel], root / "SHA256SUMS.txt")

            source = root / "candidate source.tar.gz"
            source.write_bytes(b"source")
            with self.assertRaisesRegex(ValueError, "whitespace"):
                create_manifest([wheel, source], root / "SHA256SUMS.txt")


if __name__ == "__main__":
    unittest.main()
