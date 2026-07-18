from __future__ import annotations

import argparse
import configparser
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

PACKAGE_PREFIX = "codex_serverops_mcp/"
EXPECTED_COMMANDS = {
    "codex-serverops-mcp",
    "serverops-install",
    "serverops-setup",
    "serverops-auth",
    "serverops-broker",
    "serverops-session-worker",
}


def wheel_payload(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {
            name: archive.read(name)
            for name in archive.namelist()
            if name.startswith(PACKAGE_PREFIX) and not name.endswith("/")
        }


def verify_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        required = {
            "codex_serverops_mcp/server.py",
            "codex_serverops_mcp/application.py",
            "codex_serverops_mcp/installer/cli.py",
            "codex_serverops_mcp/security/audit.py",
            "codex_serverops_mcp/worker/process.py",
        }
        missing = sorted(required - names)
        if missing:
            raise RuntimeError(f"Wheel is missing product payload: {missing}")
        forbidden = sorted(
            name
            for name in names
            if "__pycache__" in name
            or name.endswith((".pyc", ".pyo"))
            or name.startswith("codex_serverops_mcp/spike/")
            or any(part in f"/{name}" for part in ("/tests/", "/scripts/", "/docs/"))
        )
        if forbidden:
            raise RuntimeError(f"Wheel contains development/runtime material: {forbidden}")
        entry_points = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        metadata_files = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(entry_points) != 1 or len(metadata_files) != 1:
            raise RuntimeError("Wheel must contain exactly one entry point and metadata file")
        scripts = configparser.ConfigParser()
        scripts.read_string(archive.read(entry_points[0]).decode("utf-8"))
        commands = set(scripts["console_scripts"])
        if commands != EXPECTED_COMMANDS:
            raise RuntimeError(
                f"Wheel command surface mismatch: expected={sorted(EXPECTED_COMMANDS)}, "
                f"actual={sorted(commands)}"
            )
        metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
        if metadata["Name"] != "codex-serverops-mcp":
            raise RuntimeError("Wheel has the wrong package name")
        if metadata["Requires-Python"] not in {">=3.12,<3.13", "<3.13,>=3.12"}:
            raise RuntimeError("Wheel must require exactly the supported Python 3.12 line")
        _reject_local_home(archive)


def verify_sdist(path: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
        required_suffixes = {
            "/README.md",
            "/SECURITY.md",
            "/LICENSE",
            "/pyproject.toml",
            "/uv.lock",
            "/docs/installation.md",
            "/docs/security.md",
            "/docs/troubleshooting.md",
            "/scripts/verify_distribution.py",
            "/scripts/verify_release.py",
            "/src/codex_serverops_mcp/installer/cli.py",
            "/tests/test_tool_surface.py",
            "/.github/workflows/ci.yml",
            "/.github/workflows/release.yml",
        }
        missing = sorted(
            suffix
            for suffix in required_suffixes
            if not any(name.endswith(suffix) for name in names)
        )
        if missing:
            raise RuntimeError(f"Source distribution is missing: {missing}")
        forbidden = sorted(
            name
            for name in names
            if "__pycache__" in name
            or name.endswith((".pyc", ".pyo", ".token"))
            or any(
                part in f"/{name}/"
                for part in (
                    "/.venv/",
                    "/.git/",
                    "/.uv-cache/",
                    "/.product-smoke-runtime/",
                    "/.installer-smoke-runtime/",
                )
            )
        )
        if forbidden:
            raise RuntimeError(f"Source distribution contains runtime material: {forbidden}")
        _reject_local_home(archive)


def compare_wheel_payloads(first: Path, second: Path) -> None:
    left = wheel_payload(first)
    right = wheel_payload(second)
    if left.keys() != right.keys():
        raise RuntimeError("Rebuilt wheel has a different Python payload file set")
    changed = sorted(name for name, content in left.items() if right[name] != content)
    if changed:
        raise RuntimeError(f"Rebuilt wheel changed Python payload bytes: {changed}")


def _reject_local_home(archive: zipfile.ZipFile | tarfile.TarFile) -> None:
    markers = {
        str(Path.home()).encode("utf-8"),
        str(Path.home()).replace("\\", "/").encode("utf-8"),
    }
    leaked: list[str] = []
    if isinstance(archive, zipfile.ZipFile):
        for name in archive.namelist():
            if not name.endswith("/") and any(marker in archive.read(name) for marker in markers):
                leaked.append(name)
    else:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            content = b"" if stream is None else stream.read()
            if any(marker in content for marker in markers):
                leaked.append(member.name)
    if leaked:
        raise RuntimeError(f"Distribution contains a local user-home path: {leaked}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()
    wheels: list[Path] = []
    for path in args.artifacts:
        if path.suffix == ".whl":
            verify_wheel(path)
            wheels.append(path)
        elif path.name.endswith(".tar.gz"):
            verify_sdist(path)
        else:
            raise RuntimeError(f"Unsupported distribution artifact: {path.name}")
        print(f"Verified distribution artifact: {path.name}")
    for rebuilt in wheels[1:]:
        compare_wheel_payloads(wheels[0], rebuilt)
        print(f"Verified byte-identical Python payload: {rebuilt.name}")


if __name__ == "__main__":
    main()
