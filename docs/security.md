# Security model and audit

ServerOps MCP executes commands with the privileges of the selected SSH user. Local checks,
warnings and confirmations reduce risks, but do not replace backups, restricted accounts,
suitable file permissions or server-side sudoers rules.

## Boundaries that are and are not enforced

- Current-user Windows pipe ACLs isolate MCP, broker, workers and one-use authentication channels
  from other local users under the supported Windows model. Clients verify the connected pipe's
  owner/DACL, and mutual nonce/HMAC proofs establish token possession without transmitting the
  broker, worker or Askpass-relay token.
- OpenSSH Askpass invocation, forced with `SSH_ASKPASS_REQUIRE=force`, is the provenance boundary
  for connection prompts. The existing `serverops-auth` entry point acts as the helper and passes
  the prompt through a SID-only, HMAC-authenticated worker relay. Credential-looking ConPTY text
  alone cannot open a connection-auth window.
- Login passwords and key passphrases travel only
  `visible UI -> owning worker -> short-lived relay buffer -> Askpass stdout -> OpenSSH`. They are
  never MCP or broker data, environment values, process arguments, normal results or audit data.
- `allowed_roots` constrain only `server_files` and `server_file_edit`. Arbitrary shell and raw
  terminal access retain every permission of the selected SSH user.
- `elevation_mode` controls the guided workflow, not remote sudo authorization. Unix accounts,
  file modes and sudoers are authoritative.
- Direct password profiles permit only host key plus account password; direct OpenSSH profiles
  permit only host key plus key passphrase; SSH aliases follow OpenSSH configuration but receive
  at most one credential answer. At most one host-key answer is allowed, and all connection
  prompts are rejected after the credential answer.
- `server_exec` and raw-terminal output never authorize authentication. Sudo input remains on the
  PTY path and is accepted only during explicit interactive elevation. Interactive root startup
  additionally requires the worker's random nonce in its custom `sudo -p` prompt.
- Command framing correlates PTY output; it is not a security boundary or a shell sandbox.
- Automatic public-key installation never removes a remote `authorized_keys` entry during
  rollback. A lost result may mean that the key was already written, so ServerOps reports the
  uncertainty and local rollback status instead of guessing or attempting a destructive cleanup.
- Redaction recognizes limited known patterns and cannot guarantee detection of every secret.

Askpass proves that OpenSSH invoked the configured helper, not that every genuine remote PAM
challenge is trustworthy. The profile and prompt-count policies are defense in depth, while the
selected server and its PAM/sudo configuration remain authoritative. SID-only ACLs and capability
tokens also do not defend against a process already fully compromised as the same Windows user.
See [ADR 015](adr/015-windows-openssh-askpass-boundary.md) for the reproduced boundary and its
limits.

## Audit log

Operational MCP requests are recorded at:

```text
%LOCALAPPDATA%\codex-serverops-mcp\audit\YYYY-MM-DD.jsonl
```

The directory and daily file receive a protected current-user Windows DACL. A process lock and a
flushed append keep complete JSON lines when multiple processes write. Schema-version-1 remote
operation events record the applicable time, profile, session, SSH/effective user, tool, action,
result status, exit code, duration, truncation and elevation state. A failed write does not falsify
the remote result: the tool response reports `audit.logged = false`.

For `server_exec`, elevation `exec` and raw-terminal `start`, the log contains only a UTF-8-bounded
redacted preview, SHA-256 of the original command, and flags indicating redaction or truncation.
Raw terminal `write` input is never recorded as command text. Responses expose the same flags
under `audit`. The hash supports correlation but may reveal that two commands were identical.

The logger never includes PTY output, read file content, write content, patches, passwords,
passphrases, private keys or direct authentication input. Known redaction covers Bearer tokens,
labelled password/secret/API-key values, URL user information, common GitHub/cloud/API key shapes
and private-key blocks before preview truncation.

Local profile and setup operations use the same protected log with a separate narrow event shape.
The actions are:

```text
profile_created
profile_updated
profile_removed
profile_test_started
profile_test_completed
profile_test_failed
key_generation_started
key_generation_completed
key_generation_failed
public_key_install_started
public_key_install_completed
public_key_install_failed
public_key_install_outcome_unknown
```

These events allow only the profile name, result status and, when a profile is available, its
connection type, authentication mode, environment label, terminal/file capability flags,
elevation mode and root-session flag. They omit the full host or IP address, full key path, public
key line, configuration content and all credentials. Removal uses only the bounded non-secret
profile summary available before deletion. If this local audit write fails, the profile operation
keeps its real outcome and returns `audit.logged = false`.

## Operational guidance

Use a dedicated non-root SSH account, narrow sudoers entries, host backups and separate production
approval procedures. Treat JSONL audit files as sensitive operational metadata even after
redaction. Rotate or remove them according to local policy; version 0.1 does not upload or centrally
manage audit data.
