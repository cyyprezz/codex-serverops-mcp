# Getting started

Complete the matching installation path in [installation.md](installation.md), restart Codex and
confirm that a `serverops` MCP server with eight tools is available. Credentials must be entered
only in the separate local ServerOps windows, never in chat or an MCP argument.

## Create the first profile

Ask Codex to add a ServerOps profile and provide only non-secret suggestions such as the profile
name, host and Linux user. The local four-step assistant then owns the actual configuration.

### Connection

- Choose **Direct server** for a host/IP, port and Linux user.
- Choose **Existing SSH alias** when `ssh <alias>` already contains the target, user, key,
  ProxyJump or other OpenSSH behavior.

### Authentication

- **OpenSSH defaults** uses the user's normal SSH configuration and agent behavior.
- **Existing key** needs the private key path, for example `%USERPROFILE%\.ssh\id_ed25519`.
  Do not select the `.pub` file.
- **Install public key on the server** is idempotent. The transition logs in once with the account
  password, compares the key algorithm and blob without relying on its comment, and either reports
  that the key was already present or appends only the selected public line. It then proves a fresh
  key login before retaining the key profile. The result reports `public_key_was_new = false` for
  an existing key and `true` for a newly appended key.
- **New key** creates a dedicated Ed25519 key locally. Its optional passphrase stays in the setup
  process and its directly owned `ssh-keygen` terminal.

### Access

- Enable terminal access only when Codex may run arbitrary commands with the SSH user's rights.
- File read/write roots are absolute Linux paths, one per line. They restrict only
  `server_files` and `server_file_edit`; they do not restrict terminal commands.
- `interactive` elevation asks for the sudo password in the small local window when the remote
  timestamp is inactive. `non_interactive` never opens a password prompt and uses only `sudo -n`.
- A separate root session is optional and should remain disabled unless long-lived root shell
  access is actually required.

Review the effective target and permissions on the final page before creating the profile.

## Verify the connection

Start with read-only checks. Example requests to Codex:

```text
List my ServerOps profiles and inspect the new profile.
Open a ServerOps session for <profile>.
Run: whoami; pwd; uname -sr
List the configured allowed root with the structured file tool.
Close the ServerOps session.
```

If the disposable MCP process restarts while the broker and worker remain healthy, list the held
sessions and use `server_connection(action="rediscover")` with the existing session ID. This
rediscovers that unchanged worker and returns `command_retried = false`; it does not repair a lost
SSH connection or create a replacement session.

If sudo is enabled, acquire it once, run the required elevated operations, then release it. Do not
acquire and release around every individual command; ServerOps reuses the server-side sudo cache.

## Safe first use

- Begin with a disposable or non-production account and directory.
- Back up `authorized_keys` before testing automatic public-key installation.
- If installation or the following fresh login fails, read the local rollback status carefully.
  The public key may already be present remotely, and ServerOps never removes it automatically.
  Review the remote account before retrying or removing the key.
- Verify the server directly with `ssh` when host-key, firewall or account access is uncertain.
- Keep production approval and backups outside ServerOps; local confirmation is not a remote
  authorization boundary.
- Close sessions when work is complete. An `outcome_unknown` result must be investigated on the
  server and must never be retried automatically.

For diagnostics, run `serverops-install doctor --profile <profile>` and continue with
[troubleshooting.md](troubleshooting.md).
