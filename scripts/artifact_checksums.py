from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  ([^/\\\r\n]+)$")


def create_manifest(artifacts: list[Path], output: Path) -> None:
    files = _validate_artifacts(artifacts)
    if output.resolve() in {path.resolve() for path in files}:
        raise ValueError("checksum manifest cannot be one of its own artifacts")
    lines = [f"{_sha256(path)}  {path.name}" for path in files]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")


def verify_manifest(manifest: Path, artifact_dir: Path) -> tuple[str, ...]:
    lines = manifest.read_text(encoding="ascii").splitlines()
    if len(lines) != 2:
        raise ValueError("checksum manifest must list exactly one wheel and one source archive")
    names: list[str] = []
    for line in lines:
        match = CHECKSUM_LINE.fullmatch(line)
        if match is None:
            raise ValueError("checksum manifest has an invalid line")
        expected, name = match.groups()
        if name in names:
            raise ValueError("checksum manifest contains a duplicate artifact")
        path = artifact_dir / name
        if not path.is_file() or _sha256(path) != expected:
            raise ValueError(f"artifact checksum mismatch: {name}")
        names.append(name)
    _validate_artifacts([artifact_dir / name for name in names])
    return tuple(names)


def _validate_artifacts(artifacts: list[Path]) -> list[Path]:
    files = sorted((path.resolve() for path in artifacts), key=lambda path: path.name)
    if len(files) != 2 or len({path.name for path in files}) != 2:
        raise ValueError("exactly one wheel and one source archive are required")
    if not all(path.is_file() for path in files):
        raise ValueError("every release artifact must be a file")
    if sum(path.suffix == ".whl" for path in files) != 1:
        raise ValueError("release artifacts require exactly one wheel")
    if sum(path.name.endswith(".tar.gz") for path in files) != 1:
        raise ValueError("release artifacts require exactly one .tar.gz source archive")
    if any(any(character.isspace() for character in path.name) for path in files):
        raise ValueError("release artifact names must not contain whitespace")
    return files


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("output", type=Path)
    create.add_argument("artifacts", nargs="+", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("manifest", type=Path)
    verify.add_argument("artifact_dir", type=Path)
    args = parser.parse_args()
    if args.command == "create":
        create_manifest(args.artifacts, args.output)
        print(f"Wrote SHA-256 manifest: {args.output}")
    else:
        names = verify_manifest(args.manifest, args.artifact_dir)
        print(f"Verified SHA-256 artifacts: {', '.join(names)}")


if __name__ == "__main__":
    main()
