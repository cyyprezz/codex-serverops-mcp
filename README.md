# Codex ServerOps MCP

<!-- mcp-name: io.github.cyyprezz/codex-serverops-mcp -->

Windows-first local MCP server for operating explicitly configured Linux servers from Codex
through the Windows OpenSSH client. It keeps stateful Bash sessions alive, exposes structured
file operations and supports guided sudo without sending passwords or key passphrases through
MCP parameters.

## Why this exists

Codex can already run commands such as:

```bash
ssh my-server "docker compose ps"
```

But this is not the same as working inside a persistent remote environment.

Without a dedicated integration, Codex must repeatedly rebuild connection context, quote remote
commands correctly and reconstruct shell state for every operation. Working with password
authentication, long-running processes, interactive commands, changing directories, activated
virtual environments and `sudo` is especially awkward.

ServerOps MCP was built to solve that gap.

It provides Codex with persistent, broker-owned SSH sessions that keep their Bash state across
multiple MCP calls. Codex can enter a project directory, activate a virtual environment, run
commands, inspect output and continue working in the same remote shell.

Persistence does not make the shell indestructible. If a command exits or replaces the original
Bash, or leaves it impossible to verify, ServerOps loses the session in a controlled way and never
retries an uncertain command automatically.

Sensitive interaction remains local. SSH passwords, private-key passphrases, host-key decisions
and interactive sudo authentication are handled in separate visible windows and are never sent
through MCP tool arguments.

The goal is not to replace SSH or create a remote security sandbox. The goal is to turn an
existing SSH-accessible Linux server into a practical, stateful workspace for Codex while
continuing to use OpenSSH, Linux permissions and the operator's existing server configuration.

In practice, this enables workflows such as:

- diagnosing services and containers over several related commands;
- keeping the current directory and shell environment between operations;
- controlling long-running or interactive terminal processes;
- using password, key and guided sudo authentication without exposing credentials to Codex;
- reading and safely patching configured remote project files; and
- rediscovering broker-owned sessions after the disposable MCP process restarts, without
  rebuilding SSH or retrying a command.

> **Release status:** version `0.1.0` is the first public release. Its automated, packaging and
> contained integration gates are release-blocking. Real-network and visible credential checks
> remain documented operator evidence because public CI cannot reproduce a real SSH/sudo server.
> Start with disposable or non-production accounts while evaluating this initial release.

## What it provides

- direct SSH targets and existing OpenSSH aliases;
- a guided local profile assistant with password, existing-key and new-key workflows;
- stateful SSH sessions that preserve working directory and shell environment while the original
  Bash remains healthy and controllable;
- completed commands plus interactive terminal control;
- structured UTF-8 reads and hash-protected normal-user file edits below configured roots;
- explicit sudo acquisition, reuse and release plus optional separate root sessions;
- local redacted JSONL audit events; and
- a checkout-free `uvx` installer for published releases.

The Linux server needs no ServerOps agent or daemon.

## Requirements

- Windows 10 or Windows 11;
- Python 3.12 for the current release line;
- Windows OpenSSH Client;
- [`uv`](https://docs.astral.sh/uv/) / `uvx`; and
- an SSH-accessible Linux account with Bash. Structured file tools additionally need the common
  utilities listed in [Structured remote files](docs/structured-files.md).

Use a dedicated non-root SSH account and narrow server-side sudoers rules. ServerOps permissions
guide which MCP tools are offered; they do not replace Linux permissions, backups or a remote
sandbox.

## Getting started

The package is not published as `0.1.0` yet. Choose the matching path in
[Windows installation and Doctor](docs/installation.md):

- use the exact PyPI pin after a public release; or
- use the explicitly marked local-wheel flow when evaluating a development checkout.

After restarting Codex, follow [Getting started](docs/getting-started.md) to create the first
profile, open a session and verify the connection without putting a credential into chat.

## Documentation

- [Getting started](docs/getting-started.md)
- [Installation, update, Doctor and uninstall](docs/installation.md)
- [Profile configuration](docs/configuration.md)
- [MCP tool reference](docs/tool-reference.md)
- [Setup assistant and key transition](docs/setup-assistant.md)
- [Visible authentication](docs/authentication.md)
- [Structured remote files](docs/structured-files.md)
- [Guided sudo and root sessions](docs/elevation.md)
- [Security model and audit](docs/security.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Architecture](docs/architecture.md)
- [Release evidence and final-candidate procedure](docs/release-evidence.md)

## Development

```powershell
uv sync --locked --all-groups --python 3.12
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\ruff.exe check .
```

No credentials, private keys, host-specific configuration or generated runtime material belong
in the repository. See [SECURITY.md](SECURITY.md) before reporting a vulnerability.
