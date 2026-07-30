# Windows installation and Doctor

ServerOps requires Windows 10 or 11, Windows OpenSSH Client, `uvx` and Python 3.12 for the current
release line. Codex and Claude Code use separate thin client wrappers over the same MCP core. Run
the client-specific Doctor after installation and before adding a production profile.

## Version 0.1.1

Version `0.1.1` is packaged as a Python 3.12 wheel and starts checkout-free through `uvx` after
publication. Use the same exact version for the installer and MCP process.

```powershell
$Version = "0.1.1"
uvx --from "codex-serverops-mcp==$Version" serverops-install check
```

MCP, broker, setup, check, Doctor, and update automatically prepare
`%LOCALAPPDATA%\codex-serverops-mcp`, an empty schema-versioned profile file when needed, and
current-user-only runtime, audit, migration, status, and lock paths. The idempotent bootstrap does
not edit AI-client configuration, install a task, create a profile, request administrator rights,
or contact a server. `serverops-install setup` remains an optional compatible way to run the same
preparation explicitly.

## Codex plugin marketplace

The repository contains a Codex plugin under `plugins/codex-serverops-mcp` and a repo marketplace
named `serverops-codex`. Install both from the public repository:

```powershell
codex plugin marketplace add cyyprezz/codex-serverops-mcp
codex plugin add codex-serverops-mcp@serverops-codex
```

Start a new Codex task afterward. The plugin starts
`uvx --from codex-serverops-mcp==0.1.1 codex-serverops-mcp`, uses a 60-second startup timeout and
retains the 3730-second tool timeout required by the maximum supported remote command timeout.

Do not combine the plugin with a separate user-wide `[mcp_servers.serverops]` table. If the
installer previously created its marked block, preview and remove only that block before using the
plugin:

```powershell
uvx --from "codex-serverops-mcp==0.1.1" serverops-install codex-config --remove
uvx --from "codex-serverops-mcp==0.1.1" serverops-install codex-config --remove --apply
```

This preserves profiles, audit logs, runtime state and any separately managed broker task. The
plugin does not install a broker task or change user configuration on its own.

## Claude Code plugin marketplace

The repository also contains `plugins/claude-serverops-mcp` and the GitHub marketplace
`serverops-claude`:

```powershell
claude plugin marketplace add cyyprezz/codex-serverops-mcp
claude plugin install serverops@serverops-claude
```

If GitHub shorthand requires an unconfigured SSH key, use
`claude plugin marketplace add https://github.com/cyyprezz/codex-serverops-mcp.git` instead.

Start a new Claude Code session afterward. Its `.mcp.json` contains only Claude's STDIO fields and
pins `codex-serverops-mcp==0.1.1` exactly. Do not copy Codex's `startup_timeout_sec` or
`tool_timeout_sec` fields into the Claude file. Claude uses a `3730000` millisecond tool timeout.
The plugin does not edit Claude-owned configuration or inspect undocumented Claude state.

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

This direct user-wide configuration is an alternative to the Codex plugin. Do not enable both for
the `serverops` MCP name.

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
args = ["--from", "codex-serverops-mcp==0.1.1", "codex-serverops-mcp"]
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

The local-wheel flow does not install the version-pinned broker task. It is suitable for live
MCP evaluation, but does not claim that a held session survives a Codex restart. Restart Codex
after applying the block, then continue with [Getting started](getting-started.md).

## Doctor

Local diagnostics, including broker startup, current-user IPC and protocol compatibility:

```powershell
uvx --from "codex-serverops-mcp==$Version" serverops-install doctor
```

Select the client explicitly when diagnosing Claude Code or the shared runtime:

```powershell
uvx --from "codex-serverops-mcp==$Version" serverops-install doctor --client claude
uvx --from "codex-serverops-mcp==$Version" serverops-install doctor --client core
```

`--client codex` remains the default for compatibility. `--client all` checks both client paths;
Claude checks only documented CLI presence and shared prerequisites, never private client
configuration files.

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
