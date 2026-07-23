# Getting started

Complete the Codex or Claude Code path in [installation.md](installation.md), then start a new
client session and confirm that the `serverops` MCP server exposes eight tools. Version `0.1.1`
bootstraps its own local state automatically; neither plugin requires a prior setup command.

## First contact-free prompt

Use this prompt before opening a connection:

```text
List my ServerOps profiles. Do not create, edit, remove, test, or connect to a profile. If no
suitable profile exists, wait for me to provide non-secret suggestions before opening the visible
profile assistant. Never ask for or accept passwords, passphrases, host-key decisions, or sudo
credentials in chat; those belong only in the local ServerOps window.
```

## Create the first profile

Ask the client to open the ServerOps profile assistant and provide only non-secret suggestions such
as profile name, host or SSH alias, and Linux user. The separate local four-step assistant owns the
actual configuration.

### Connection

- Choose **Direct server** for a host/IP, port, and Linux user.
- Choose **Existing SSH alias** when `ssh <alias>` already contains the target, user, key,
  ProxyJump, or other OpenSSH behavior.

### Authentication

- **OpenSSH defaults** uses the user's normal SSH configuration and agent behavior.
- **Existing key** needs the private key path, for example `%USERPROFILE%\.ssh\id_ed25519`.
  Do not select the `.pub` file.
- **Install public key on the server** is an explicit, idempotent user workflow. It logs in once,
  compares the key algorithm and blob, appends only a missing selected public key, and proves a
  fresh key login before retaining the key profile. It is not part of automatic bootstrap.
- **New key** creates a dedicated Ed25519 key locally. Its optional passphrase stays in the setup
  process and its directly owned `ssh-keygen` terminal.

### Access

- Enable terminal access only when the client may run arbitrary commands with the SSH user's
  rights.
- File read/write roots are absolute Linux paths, one per line. They restrict only
  `server_files` and `server_file_edit`; they do not restrict terminal commands.
- `interactive` elevation asks for the sudo password in a separate local window when the remote
  timestamp is inactive. `non_interactive` never opens a password prompt and uses only `sudo -n`.
- A separate root session is optional and should remain disabled unless long-lived root shell
  access is actually required.

Review the effective target and permissions on the final page before creating the profile.

## First controlled server contact

After reviewing the saved profile, use a deliberately narrow verification:

```text
Inspect ServerOps profile "<name>". If its target and permissions match the saved profile, open one
session and run only `whoami; pwd; uname -sr`. Do not use sudo, write files, install software, or
run additional checks. Report the profile, session, exit code, working directory, and concise
output. If the result is a timeout or `outcome_unknown`, do not retry. Close the session when
finished.
```

Continue with the [reproducible demo](demo.md) only on a disposable or non-production account.

## Session rediscovery

Reliable rediscovery after the MCP client process restarts requires the explicitly installed
managed broker task. While that broker, its worker, and the original Bash remain alive, list held
sessions and rediscover the existing session ID. The response reports `command_retried = false`.

This does not repair a lost SSH connection, adopt a worker after a broker crash, or resume a
session after Windows reboots. Without the managed task, do not promise that a session outlives the
MCP process tree.

## Safe first use

- Begin with a disposable or non-production account and directory.
- Back up `authorized_keys` before testing the optional public-key transition.
- If key installation or the fresh login fails, inspect the rollback result and remote account
  before retrying. ServerOps never removes a remotely present key automatically.
- Verify the server directly with `ssh` when host-key, firewall, or account access is uncertain.
- Keep production approval and backups outside ServerOps; local confirmation is not a remote
  authorization boundary.
- Close sessions when work is complete. A timeout or unknown-outcome result after a mutation must
  be verified read-only and must never be retried automatically.

For local and remote diagnostics, select the relevant client with `serverops-install doctor
--client core|codex|claude|all` and continue with [troubleshooting.md](troubleshooting.md). A
Codex plugin-only installation can warn about the absent alternative installer-managed config
block; see [installation.md](installation.md#doctor).
