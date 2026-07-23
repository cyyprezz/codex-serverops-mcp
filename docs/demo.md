# Reproducible ServerOps demo

This demo proves the currently shipped workflow without inventing customer stories, performance
figures, or production claims. Use a disposable or non-production Linux account and a user-owned
directory that is configured as both a read and write root.

## Record the environment

Record these non-secret facts with the result:

- Windows version, Python version, `uv` version, and ServerOps package version;
- client and client version (Codex or Claude Code);
- profile name and whether it uses a direct target or SSH alias; and
- whether the optional managed broker task is installed.

Do not record the hostname, username, paths, output, or versions if they identify a customer or
production system.

## 1. Confirm the local boundary

Install through the matching [client path](installation.md), then ask:

```text
List my ServerOps profiles only. Do not create, edit, remove, test, or connect to a profile. Do not
contact a server.
```

Expected evidence: the response is structured and no authentication window or server connection
opens. If no profile exists, use the visible assistant with non-secret suggestions and review the
saved target and permissions before continuing.

## 2. Verify one read-only connection

```text
Inspect profile "<demo-profile>". If the target matches, open one session and run only
`whoami; pwd; uname -sr`. Do not use sudo or change anything. Return the session ID, exit code,
working directory, and concise output. Leave the session open for the next step.
```

Expected evidence: one session ID, exit code `0`, the effective Linux user, current directory, and
kernel summary. A visible local prompt may appear when OpenSSH needs a password, passphrase, or
host-key decision; enter it only there.

## 3. Prove retained Bash state

In the same session, run:

```text
Change to the configured demo directory and set `SERVEROPS_DEMO=ready`. Then, as a separate
completed command in the same session, run only `pwd; printf '%s\n' "$SERVEROPS_DEMO"`. Report the
exit code and output.
```

Expected evidence: the second command reports the chosen directory and `ready`. This proves live
process-held state, not durable jobs or reboot recovery.

## 4. Prove a preconditioned text edit

Create a harmless UTF-8 demo file in the configured user-owned root outside ServerOps, or choose an
existing disposable file. Then ask:

```text
Read and hash "<demo-file>" with the structured file tool. Propose appending one line containing
`serverops-demo`, show the observed SHA-256, and wait for approval. After approval, apply the edit
with that exact expected SHA-256, read the file again, and report the new hash. Do not touch any
other path.
```

Expected evidence: bounded text content, an original hash, an explicitly approved edit, and a new
hash. Clean up the demo file only through a separately approved action. The configured root applies
to structured file tools, not to arbitrary shell commands.

## 5. Optional MCP-restart rediscovery

Run this step only when the managed current-user broker task was explicitly installed. Keep the
session open, restart only the MCP client/session, then ask the new client to list held sessions and
rediscover the recorded session ID without running a command.

Expected evidence: the same session is found and `command_retried = false`. This test does not
cover a broker crash, worker adoption, SSH loss, or Windows reboot.

## Finish

Close the demo session and report:

- which steps were run and whether they matched the expected evidence;
- any visible authentication or elevation prompt without its contents;
- every changed path and final hash; and
- any timeout, truncation, warning, or unknown outcome.

Do not deliberately induce `outcome_unknown` on a real server. If it occurs, stop mutations and
verify state read-only; never retry automatically.
