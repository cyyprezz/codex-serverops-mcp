# ADR 017: Versioned Windows multiprocess package

Status: Proposed for 0.1.2

## Context

The current exact `uvx` package is checkout-free but requires Python/uv provisioning and cold
dependency resolution. ServerOps also has six process roles, pywin32/pywinpty/native dependencies,
visible authentication windows, a persistent broker, and upgrade/uninstall requirements that a
single opaque executable cannot model safely.

## Options

1. A thin bootstrapper downloading an exactly pinned ServerOps runtime is small, but makes first
   use network-dependent and complicates provenance, rollback, antivirus reputation, and partial
   download recovery.
2. A single self-contained runtime removes Python/uv but makes onefile extraction, process-role
   identity, native DLL loading, startup time, signing surface, and rollback harder to reason about.
3. A classic per-user installer with a bundled onedir runtime and separate role executables is
   larger, but gives explicit process identity, deterministic native dependencies, versioned
   directories, atomic activation, repair, rollback, and uninstall.

## Decision

Choose option 3 for 0.1.2. Build a signed x64 onedir runtime containing separate MCP, broker,
session-worker, setup, auth, and installer executables. Install versions below
`%LOCALAPPDATA%\Programs\ServerOps\versions\<version>` and switch a small stable active-version
record atomically only after offline smoke checks. Preserve `%LOCALAPPDATA%\codex-serverops-mcp`
as user state. Prefer Inno Setup after the packaging spike; sign the installer and every executable.

Builds run on pinned Windows CI from a clean source archive with locked Python dependencies,
PyInstaller, and installer tooling. Do not use onefile or UPX. Auth/setup remain GUI executables;
MCP, broker, worker, and installer remain console/background roles. The runtime resolver must launch
adjacent signed role binaries instead of relying on `sys.executable -m`.

## Consequences

Runtime use needs neither Python nor uv. Disk usage is higher and signing/reputation work becomes a
release prerequisite. SmartScreen reputation cannot be guaranteed by signing alone, so publisher
identity, stable certificates, timestamping, submission/false-positive procedures, and clean-VM
E2E evidence are required.

## Upgrade, rollback, and uninstall

Install a new immutable version beside the active one, validate all role starts, then atomically
activate it. Keep the previous version for rollback; never migrate user state destructively before
activation. Uninstall removes managed binaries and tasks but preserves profiles/audit by default.

## Verification

Windows E2E must cover a machine without Python/uv, pywin32/pywinpty loading, MCP initialization,
broker/worker IPC, visible auth UI, setup UI, restart persistence, upgrade, failed-upgrade rollback,
uninstall, signature verification, Defender scanning, and client integration.
