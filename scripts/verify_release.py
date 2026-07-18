from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STABLE_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
REGISTRY_SCHEMA = re.compile(
    r"^https://static\.modelcontextprotocol\.io/schemas/[0-9-]+/server\.schema\.json$"
)
REQUIRED_MANUAL_CHECKS = {
    "password_window",
    "key_passphrase_window",
    "host_key_window",
    "sudo_window_and_cache",
    "auth_cancel_and_timeout",
    "setup_direct_and_alias_profiles",
    "setup_existing_and_generated_keys",
    "public_key_install_and_fresh_login",
    "mcp_restart_and_session_rediscovery",
    "interrupt_disconnect_and_no_retry",
}


class ReleaseContractError(RuntimeError):
    pass


def verify_release(
    repo_root: Path = REPO_ROOT,
    *,
    tag: str | None = None,
    evidence_path: Path | None = None,
) -> str:
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(project["project"]["version"])
    source = (repo_root / "src" / "codex_serverops_mcp" / "__init__.py").read_text(
        encoding="utf-8"
    )
    if f'__version__ = "{version}"' not in source:
        raise ReleaseContractError("pyproject and package versions differ")
    if project["project"]["name"] != "codex-serverops-mcp":
        raise ReleaseContractError("PyPI project name changed unexpectedly")
    if project["project"]["requires-python"] != ">=3.12,<3.13":
        raise ReleaseContractError("Release must remain on the supported Python 3.12 line")
    scripts = set(project["project"]["scripts"])
    expected_scripts = {
        "codex-serverops-mcp",
        "serverops-install",
        "serverops-setup",
        "serverops-auth",
        "serverops-broker",
        "serverops-session-worker",
    }
    if scripts != expected_scripts:
        raise ReleaseContractError("Console command surface differs from the 0.1 contract")
    required_paths = (
        "README.md",
        "SECURITY.md",
        "docs/installation.md",
        "docs/getting-started.md",
        "docs/security.md",
        "docs/tool-reference.md",
        "docs/troubleshooting.md",
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
    )
    missing = [path for path in required_paths if not (repo_root / path).is_file()]
    if missing:
        raise ReleaseContractError(f"Release documentation/workflows are missing: {missing}")
    _verify_workflow(repo_root / ".github" / "workflows" / "release.yml")
    if tag is not None:
        if not STABLE_VERSION.fullmatch(version) or tag != f"v{version}":
            raise ReleaseContractError("Release tag must exactly match a stable package version")
        _verify_server_json(repo_root, version)
        evidence = evidence_path or repo_root / "docs" / "release-evidence.json"
        _verify_evidence(repo_root, evidence, version)
    return version


def _verify_server_json(repo_root: Path, version: str) -> None:
    path = repo_root / "server.json"
    if not path.is_file():
        raise ReleaseContractError("Stable release requires server.json")
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    includes = project["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    if "/server.json" not in includes:
        raise ReleaseContractError("Stable source distribution must include server.json")
    server = json.loads(path.read_text(encoding="utf-8"))
    schema = server.get("$schema")
    name = server.get("name")
    repository = server.get("repository")
    if not isinstance(schema, str) or not REGISTRY_SCHEMA.fullmatch(schema):
        raise ReleaseContractError("server.json uses an invalid registry schema URL")
    if not isinstance(name, str) or not name.startswith("io.github."):
        raise ReleaseContractError("server.json requires an owned io.github registry name")
    if not isinstance(repository, dict) or repository.get("source") != "github":
        raise ReleaseContractError("server.json requires GitHub repository ownership metadata")
    repository_url = repository.get("url")
    if not isinstance(repository_url, str) or not repository_url.startswith("https://github.com/"):
        raise ReleaseContractError("server.json repository URL is invalid")
    marker = f"mcp-name: {name}"
    if marker not in (repo_root / "README.md").read_text(encoding="utf-8"):
        raise ReleaseContractError("README is missing the matching MCP ownership marker")
    expected_package = {
        "registryType": "pypi",
        "identifier": "codex-serverops-mcp",
        "version": version,
        "runtimeHint": "uvx",
        "transport": {"type": "stdio"},
    }
    if server.get("version") != version or server.get("packages") != [expected_package]:
        raise ReleaseContractError("server.json package/version contract is inconsistent")


def _verify_evidence(repo_root: Path, path: Path, version: str) -> None:
    if not path.is_file():
        raise ReleaseContractError("Stable release requires committed manual release evidence")
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if evidence.get("schema_version") != 1 or evidence.get("package_version") != version:
        raise ReleaseContractError("Release evidence schema/version is invalid")
    checks = evidence.get("checks")
    if not isinstance(checks, dict) or set(checks) != REQUIRED_MANUAL_CHECKS:
        raise ReleaseContractError("Release evidence check set is incomplete")
    if any(value is not True for value in checks.values()):
        raise ReleaseContractError("Every manual release gate must be explicitly passed")
    revision = evidence.get("source_revision")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{7,40}", revision):
        raise ReleaseContractError("Release evidence has no valid source revision")
    completed_at = evidence.get("completed_at")
    if not isinstance(completed_at, str) or not completed_at.endswith("Z"):
        raise ReleaseContractError("Release evidence has no UTC completion timestamp")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if revision == head:
        return
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", revision, "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    changed = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", revision, "HEAD", "--"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if ancestor.returncode != 0 or changed != ["docs/release-evidence.json"]:
        raise ReleaseContractError(
            "Manual release evidence must match the release commit except for its own "
            "evidence-only commit"
        )


def _verify_workflow(path: Path) -> None:
    workflow = path.read_text(encoding="utf-8")
    required = (
        '"v[0-9]+.[0-9]+.[0-9]+"',
        "persist-credentials: false",
        "git merge-base --is-ancestor",
        "scripts/verify_release.py --tag",
        "id-token: write",
        "pypa/gh-action-pypi-publish@",
        "attestations: true",
        "needs: publish-pypi",
        "gh release create",
    )
    missing = [fragment for fragment in required if fragment not in workflow]
    if missing:
        raise ReleaseContractError(f"Release workflow safety contracts are missing: {missing}")
    forbidden = ("workflow_dispatch:", "PYPI_TOKEN", "password:", "skip-existing")
    present = [fragment for fragment in forbidden if fragment in workflow]
    if present:
        raise ReleaseContractError(f"Release workflow has forbidden publishing config: {present}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    version = verify_release(tag=args.tag, evidence_path=args.evidence)
    gate = "stable release" if args.tag else "development"
    print(f"{gate} contract OK for {version}")


if __name__ == "__main__":
    main()
