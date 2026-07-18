# Windows installation and Doctor

ServerOps requires Windows 10 or 11, Windows OpenSSH Client, `uvx` and Python 3.12. Run the local
Doctor after installation and before adding a production profile.

## Published release

Once version 0.1 is published, it is distributed as a Python 3.12 wheel and started checkout-free
through `uvx`. Use one exact version for the installer and MCP process. The current development
package `0.0.0.dev1` is not yet that release.

```powershell
$Version = "0.1.0"
uvx --from "codex-serverops-mcp==$Version" serverops-install setup
uvx --from "codex-serverops-mcp==$Version" serverops-install check
```

`setup` prepares `%LOCALAPPDATA%\codex-serverops-mcp`, an empty schema-versioned profile file when
needed, current-user-only runtime/audit directories and migrations. It does not modify Codex
configuration or contact a server.

Preview the persistent current-user broker task separately:

```powershell
uvx --from "codex-serverops-mcp==$Version" serverops-install setup --broker-task
```

After reviewing its exact pinned action, apply it explicitly:

```powershell
uvx --from "codex-serverops-mcp==$Version" serverops-install setup --broker-task --apply
```

The task is visible in Windows Task Scheduler, runs only as the current interactive user, stores
no password and requests no administrator elevation. It starts at user logon or on demand and
keeps the broker outside Codex's disposable MCP process tree. An unrelated task with the same
SID-derived name is never replaced.

## Codex configuration

Preview the complete proposed user-wide block:

```powershell
uvx --from "codex-serverops-mcp==$Version" serverops-install codex-config
```

Apply only after review:

```powershell
uvx --from "codex-serverops-mcp==$Version" serverops-install codex-config --apply
```

The command asks for local confirmation; `--yes` is an explicit non-interactive confirmation. The
managed block uses only documented Codex STDIO fields:

```toml
# >>> codex-serverops-mcp managed block >>>
[mcp_servers.serverops]
command = "uvx"
args = ["--from", "codex-serverops-mcp==0.1.0", "codex-serverops-mcp"]
startup_timeout_sec = 60
tool_timeout_sec = 3730
# <<< codex-serverops-mcp managed block <<<
```

There is no checkout-dependent `cwd`. An existing unmarked `mcp_servers.serverops` table or
ambiguous marker is never overwritten. The installer validates the existing and proposed TOML,
rechecks immediately before replacement, writes an atomic backup, validates after replacement and
rolls back a failed write. Restart Codex after applying or removing the block.

## Pre-release integration from a local wheel

Before a version exists on the package index, the same installer can temporarily configure Codex
to start one exact locally built wheel in offline mode:

```powershell
uv sync --locked --all-groups --python 3.12
uv build

$Python = (Resolve-Path .\.venv\Scripts\python.exe).Path
$Wheel = (Get-ChildItem .\dist\*.whl | Select-Object -First 1).FullName

uvx --python $Python --from $Wheel serverops-install setup
uvx --python $Python --offline --from $Wheel serverops-install codex-config `
  --development-wheel $Wheel `
  --development-python $Python
uvx --python $Python --offline --from $Wheel serverops-install codex-config `
  --development-wheel $Wheel `
  --development-python $Python `
  --apply
```

The first command may download the wheel's dependencies. The later offline commands prove that
Codex will not need the package index for this exact local candidate.

The installer verifies the wheel's package name and exact version, verifies and pins the provided
Python 3.12 executable, resolves `uvx` to an absolute path and uses no checkout working directory.
The managed-block transaction, confirmation, backup, concurrent-change check and rollback are
identical to the release path. This mode is only a local pre-release gate; replace it with the
normal exact package pin before release.

The local-wheel flow does not install the published-version broker task. It is suitable for live
MCP evaluation, but does not claim that a held session survives a Codex restart. Restart Codex
after applying the block, then continue with [Getting started](getting-started.md).

## Doctor

Local diagnostics, including broker startup, current-user IPC and protocol compatibility:

```powershell
uvx --from "codex-serverops-mcp==$Version" serverops-install doctor
```

Full connection and remote preflight:

```powershell
uvx --from "codex-serverops-mcp==$Version" serverops-install doctor --profile kunde-prod
```

The profile form may open visible authentication. Doctor checks target resolution, a held Bash,
the effective user, required common Linux commands, every configured allowed root, non-prompting
sudo behavior and obvious root-login/broad-NOPASSWD risks. Sudo findings are warnings because
Doctor cannot replace a manual sudoers review. `--json` emits the same stable pass/warning/fail
records for support automation. Without `--profile`, remote checks are explicitly reported as not
run.

## Update and uninstall

Run `serverops-install update` from the newly pinned distribution to migrate local state. It never
silently edits the Codex pin; preview and apply `codex-config` separately.

`serverops-install uninstall` previews removal of the managed Codex block and the marked
current-user broker task. `--apply` requires confirmation, stops the broker first and refuses an
unmarked task collision. Profiles and audit logs remain by default; `--remove-data` explicitly
removes the whole ServerOps LocalAppData directory after confirmation. User SSH keys and remote
files are never removed. Because the MCP itself is launched by `uvx`, there is no checkout or
private installed payload to delete.
