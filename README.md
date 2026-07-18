# Codex ServerOps MCP

Windows-first local MCP server for operating explicitly configured Linux servers from Codex
through the Windows OpenSSH client. It keeps stateful Bash sessions alive, exposes structured
file operations and supports guided sudo without sending passwords or key passphrases through
MCP parameters.

> **Development status:** the current package is `0.0.0.dev1`, not the stable `0.1.0` release.
> Its local automated suite and manually operated development environments have passed, but the
> public CI does not reproduce a real SSH/sudo server. Use only disposable or non-production
> accounts while release hardening is in progress.

## What it provides

- direct SSH targets and existing OpenSSH aliases;
- a guided local profile assistant with password, existing-key and new-key workflows;
- stateful SSH sessions that preserve working directory and shell environment;
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

## Development

```powershell
uv sync --locked --all-groups --python 3.12
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\ruff.exe check .
```

No credentials, private keys, host-specific configuration or generated runtime material belong
in the repository. See [SECURITY.md](SECURITY.md) before reporting a vulnerability.
