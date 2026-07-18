# Troubleshooting

Start with:

```powershell
serverops-install doctor --profile <profile>
```

If Codex does not show the `serverops` MCP after configuration, restart the desktop app, CLI
session or IDE extension. The desktop app, CLI and IDE share the same user configuration but load
new STDIO servers only when starting a session.

- `ssh_missing`: enable the Windows OpenSSH Client optional feature and rerun Doctor.
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
