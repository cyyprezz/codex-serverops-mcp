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
    "spoofed_remote_prompt_rejected",
    "shell_state_corruption_detected",
    "failed_key_transition_reports_remote_key_state",
    "profile_mutations_audited",
}
REQUIRED_EVIDENCE_ENVIRONMENT = {
    "windows_version",
    "python_version",
    "uv_version",
    "windows_openssh_version",
    "ubuntu_version",
    "remote_openssh_version",
    "sudo_version",
    "bash_version",
}
REQUIRED_EXTERNAL_SCENARIOS = {
    "direct_connection",
    "ssh_alias",
    "password_login",
    "existing_key",
    "passphrase_protected_key",
    "new_ed25519_key",
    "public_key_install",
    "fresh_new_key_login",
    "host_key_confirmation",
    "auth_cancel",
    "auth_timeout",
    "persistent_cwd",
    "persistent_virtual_environment",
    "persistent_shell_variables",
    "completed_command_exit_code",
    "large_output_truncation",
    "raw_terminal_start",
    "raw_terminal_read",
    "raw_terminal_write",
    "ctrl_c",
    "timeout_recovery",
    "ssh_disconnect",
    "outcome_unknown",
    "no_automatic_retry",
    "mcp_restart",
    "broker_session_rediscovery",
    "structured_file_list",
    "structured_text_read",
    "structured_search",
    "structured_hash",
    "structured_write_text",
    "structured_apply_patch",
    "structured_hash_conflict",
    "structured_symlink_escape",
    "structured_outside_allowed_roots",
    "sudo_status",
    "sudo_acquire",
    "sudo_server_cache",
    "sudo_exec",
    "sudo_release",
    "root_session",
    "separate_normal_root_sessions",
    "doctor_real_profile",
}
EVIDENCE_SCENARIO_STATUSES = {
    "automated",
    "manually_verified",
    "not_tested",
    "not_applicable",
}
VERIFIED_SCENARIO_STATUSES = {"automated", "manually_verified"}


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
        "CHANGELOG.md",
        "SECURITY.md",
        "docs/artifact-plan.md",
        "docs/installation.md",
        "docs/getting-started.md",
        "docs/manual-release-gates.md",
        "docs/migration-rollback-evidence.md",
        "docs/release-candidate-checklist.md",
        "docs/release-checklist.md",
        "docs/release-notes-0.1.1.md",
        "docs/security.md",
        "docs/tool-reference.md",
        "docs/troubleshooting.md",
        "docs/windows-test-plan.md",
        "scripts/artifact_checksums.py",
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
    )
    missing = [path for path in required_paths if not (repo_root / path).is_file()]
    if missing:
        raise ReleaseContractError(f"Release documentation/workflows are missing: {missing}")
    _verify_workflow(repo_root / ".github" / "workflows" / "release.yml")
    _verify_version_sync(repo_root, project, version)
    if tag is not None:
        if not STABLE_VERSION.fullmatch(version) or tag != f"v{version}":
            raise ReleaseContractError("Release tag must exactly match a stable package version")
        evidence = evidence_path or repo_root / "docs" / "release-evidence.json"
        _verify_evidence(repo_root, evidence, version)
    return version


def _verify_version_sync(
    repo_root: Path,
    project: dict[str, object],
    version: str,
) -> None:
    _verify_server_json(repo_root, version)
    lock = tomllib.loads((repo_root / "uv.lock").read_text(encoding="utf-8"))
    local_packages = [
        package
        for package in lock.get("package", [])
        if package.get("name") == project["project"]["name"]
    ]
    if len(local_packages) != 1 or local_packages[0].get("version") != version:
        raise ReleaseContractError("uv.lock project version is not synchronized")

    codex_root = repo_root / "plugins" / "codex-serverops-mcp"
    claude_root = repo_root / "plugins" / "claude-serverops-mcp"
    codex_manifest = json.loads(
        (codex_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    codex_mcp = json.loads((codex_root / ".mcp.json").read_text(encoding="utf-8"))
    claude_marketplace = json.loads(
        (repo_root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    claude_manifest = json.loads(
        (claude_root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    claude_mcp = json.loads((claude_root / ".mcp.json").read_text(encoding="utf-8"))
    capabilities = json.loads(
        (repo_root / "docs" / "capabilities.json").read_text(encoding="utf-8")
    )
    expected_args = ["--from", f"codex-serverops-mcp=={version}", "codex-serverops-mcp"]
    claude_plugins = claude_marketplace.get("plugins")
    synchronized = (
        codex_manifest.get("version") == version
        and codex_mcp.get("mcpServers", {}).get("serverops", {}).get("args")
        == expected_args
        and isinstance(claude_plugins, list)
        and len(claude_plugins) == 1
        and isinstance(claude_plugins[0], dict)
        and claude_plugins[0].get("version") == version
        and claude_manifest.get("version") == version
        and claude_mcp.get("mcpServers", {}).get("serverops", {}).get("args")
        == expected_args
        and capabilities.get("published_version") == version
    )
    if not synchronized:
        raise ReleaseContractError("package, plugin, marketplace, or capability versions differ")

    for name in ("serverops-control", "serverops-diagnose"):
        codex_skill = (codex_root / "skills" / name / "SKILL.md").read_bytes()
        claude_skill = (claude_root / "skills" / name / "SKILL.md").read_bytes()
        if codex_skill != claude_skill:
            raise ReleaseContractError(f"client-neutral skill copies differ: {name}")


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
    if evidence.get("schema_version") != 2 or evidence.get("package_version") != version:
        raise ReleaseContractError("Release evidence schema/version is invalid")
    checks = evidence.get("checks")
    if not isinstance(checks, dict) or set(checks) != REQUIRED_MANUAL_CHECKS:
        raise ReleaseContractError("Release evidence check set is incomplete")
    if any(value is not True for value in checks.values()):
        raise ReleaseContractError("Every manual release gate must be explicitly passed")
    environment = evidence.get("environment")
    if not isinstance(environment, dict) or set(environment) != REQUIRED_EVIDENCE_ENVIRONMENT:
        raise ReleaseContractError("Release evidence environment metadata is incomplete")
    if any(
        not isinstance(value, str) or not value.strip() or len(value) > 512
        for value in environment.values()
    ):
        raise ReleaseContractError("Release evidence environment metadata is invalid")
    scenarios = evidence.get("external_scenarios")
    if not isinstance(scenarios, dict) or set(scenarios) != REQUIRED_EXTERNAL_SCENARIOS:
        raise ReleaseContractError("External Ubuntu scenario evidence is incomplete")
    if any(status not in EVIDENCE_SCENARIO_STATUSES for status in scenarios.values()):
        raise ReleaseContractError("External Ubuntu scenario evidence has an invalid status")
    unverified = sorted(
        name for name, status in scenarios.items() if status not in VERIFIED_SCENARIO_STATUSES
    )
    if unverified:
        raise ReleaseContractError(
            f"Stable release has unverified external Ubuntu scenarios: {unverified}"
        )
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
    if ancestor.returncode != 0:
        raise ReleaseContractError("Manual release evidence revision is not an ancestor of HEAD")
    follow_up_count = subprocess.run(
        ["git", "rev-list", "--count", f"{revision}..HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if follow_up_count != "1":
        raise ReleaseContractError(
            "Manual release evidence must be HEAD or exactly one evidence-only follow-up commit"
        )
    changed = subprocess.run(
        [
            "git",
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            "--no-renames",
            "HEAD",
            "--",
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if changed != ["docs/release-evidence.json"]:
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
        "--evidence docs/release-evidence.json",
        "@anthropic-ai/claude-code@2.1.206 plugin validate",
        "scripts/artifact_checksums.py create",
        "scripts/artifact_checksums.py verify",
        "plugins/codex-serverops-mcp/.mcp.json --repeat 2",
        "plugins/claude-serverops-mcp/.mcp.json --repeat 2",
        "id-token: write",
        "pypa/gh-action-pypi-publish@",
        "attestations: true",
        "needs: publish-pypi",
        "gh release create",
        "--notes-file docs/release-notes-0.1.1.md",
    )
    missing = [fragment for fragment in required if fragment not in workflow]
    if missing:
        raise ReleaseContractError(f"Release workflow safety contracts are missing: {missing}")
    forbidden = (
        "workflow_dispatch:",
        "PYPI_TOKEN",
        "password:",
        "skip-existing",
        "--automated-gates-only",
    )
    present = [fragment for fragment in forbidden if fragment in workflow]
    if present:
        raise ReleaseContractError(f"Release workflow has forbidden publishing config: {present}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    version = verify_release(
        tag=args.tag,
        evidence_path=args.evidence,
    )
    gate = "stable release" if args.tag else "development"
    print(f"{gate} contract OK for {version}")


if __name__ == "__main__":
    main()
