# Troubleshooting

Start with:

```powershell
serverops-install doctor --client codex --profile <profile>
```

For Claude Code use `--client claude`; for client-independent runtime checks use `--client core`.

If Codex does not show the `serverops` MCP after plugin installation, start a new Codex task and
verify that the repository marketplace and `codex-serverops-mcp@serverops-codex` plugin are
installed. Do not add a second user-wide MCP block. `doctor --client codex` checks the alternative
installer-managed block and can warn when a correct plugin-only installation does not have one.

If Claude Code does not load ServerOps, verify `claude` is on `PATH`, run
`claude plugin marketplace add cyyprezz/codex-serverops-mcp` (or the full HTTPS Git URL) and
`claude plugin install serverops@serverops-claude`, then start a new Claude Code session. ServerOps
Doctor deliberately does not parse or modify undocumented Claude-owned configuration files.

Both plugin manifests pin `0.1.1`. On first start that runtime creates only ServerOps-owned local
state. If bootstrap fails, inspect the reported LocalAppData path and permissions; do not work
around the failure by editing client configuration or running as administrator.

## Python and candidate resolution

The Python-package release does not bundle Python. Before debugging either client, require both
commands to resolve a real CPython 3.12 executable:

```powershell
python --version
uv python find 3.12
```

If `uvx` selects `Microsoft\WindowsApps\python.exe` and fails with Windows error 1312 (`Eine
angegebene Anmeldesitzung ist nicht vorhanden`), the Windows app-execution alias is not a usable
runtime. Install or repair Python 3.12, make the real executable discoverable, and rerun the check.
For a controlled local-candidate test, `UV_PYTHON` may point at the recorded Python 3.12
executable; do not add that machine-specific path to a plugin manifest.

An unpublished exact pin cannot be downloaded from the public package index. Release-candidate
tests must therefore make the identically versioned wheel available to the spawned `uvx` process
through an isolated wheelhouse/cache or a recorded test-only `uvx` shim. Do not change either
plugin manifest or its `0.1.1` argument for this test. A successful candidate run proves the built
artifact and unchanged launch contract; it does not claim that the pin is already public.

- `ssh_missing`: enable the Windows OpenSSH Client optional feature and rerun Doctor.
- `claude_code_missing`: install Claude Code or select `--client core` when only the shared runtime
  should be checked.
- `codex_config_invalid`: repair the existing TOML manually; the installer will not overwrite it.
- `codex_config_unmanaged`: rename/remove the existing unmarked `mcp_servers.serverops` entry only
  after reviewing who owns it.
- `broker_unavailable` or `broker_protocol`: close old Codex/MCP processes and run the exactly
  pinned package version again. Version mismatches fail closed.
- `local_acl_shared` or `broker_acl`: do not continue with secrets; repair the Windows user/ACL
  context first.
- `profile_unresolved`: for advanced SSH behavior, verify the alias with `ssh -G <alias>` and keep
  ProxyJump/ProxyCommand in OpenSSH configuration.
- `connection`: run `ssh` manually to distinguish network/firewall reachability from profile or
  authentication issues. Never paste the password into Codex or a support log.
- `authentication_cancelled` or `authentication_timeout`: retry the operation and answer only the
  separate local ServerOps window. Closing it intentionally cancels the owning SSH attempt.
- Repeated key-passphrase prompts: verify the selected private-key path and OpenSSH agent/config.
  ServerOps never stores the passphrase.
- `remote_commands_missing`: install the named common Linux utilities or disable structured file
  work until the preflight passes.
- `allowed_root_invalid`: create/correct the configured directory and inspect symlinks with the
  intended SSH account.
- `sudo_noninteractive_*` or `sudo_broad_nopasswd`: these are risk warnings, not proof of a precise
  sudoers rule. Review `sudo -l` and sudoers on the server.
- Repeated sudo-password prompts: call elevation `status`, acquire once when inactive, reuse that
  timestamp for the operation sequence and call `release` afterward. Do not acquire/release around
  every command.
- `session_lost` or shell-health failure: `exit`, `logout`, `exec`, disabled required builtins or
  other destructive shell changes can make the original Bash unverifiable. Open a new session;
  do not treat the old session as ready.
- `outcome_unknown`: inspect server state through a new session or independent SSH connection
  before deciding what to do. `rediscover` may find broker metadata, but it never repairs a lost
  SSH connection or retries the command.
- Public-key transition failure: inspect `local_profile_rollback_status`. Even after
  `rolled_back`, the public key may already be present in remote `authorized_keys`. With
  `outcome_unknown`, neither `public_key_installed` nor `public_key_was_new` is known. ServerOps
  never removes the remote key automatically; review the remote account before retrying or
  removing it.
- `audit.logged = false`: the profile or remote operation retains its reported result, but the
  protected local audit append failed. Repair local storage/DACLs before relying on audit coverage.

For local development wheels, `python_unsupported` means the managed block did not use Python
3.12. Regenerate it with both `--development-wheel` and `--development-python` rather than editing
the block by hand.

Visible password, passphrase, host-key and interactive-sudo flows remain manual Windows release
checks. Cancelling or closing their local window must return a controlled auth status, not move the
secret into chat.
