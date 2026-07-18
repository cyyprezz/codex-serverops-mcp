# Security model and audit

ServerOps MCP executes commands with the privileges of the selected SSH user. Local checks,
warnings and confirmations reduce risks, but do not replace backups, restricted accounts,
suitable file permissions or server-side sudoers rules.

## Boundaries that are and are not enforced

- Current-user Windows pipe ACLs isolate MCP, broker, workers and one-use authentication channels
  from other local users under the supported Windows model. Clients verify the connected pipe's
  owner/DACL, and mutual nonce/HMAC proofs establish token possession without transmitting the
  broker or worker token.
- Passwords, key passphrases and sudo input travel only between the visible auth process and the
  worker that owns OpenSSH. They are never MCP arguments or normal broker messages.
- `allowed_roots` constrain only `server_files` and `server_file_edit`. Arbitrary shell and raw
  terminal access retain every permission of the selected SSH user.
- `elevation_mode` controls the guided workflow, not remote sudo authorization. Unix accounts,
  file modes and sudoers are authoritative.
- Credential-like remote text is not trusted as an authentication request. SSH prompts are
  accepted only during connection startup and sudo prompts only during explicit elevation.
- Command framing correlates PTY output; it is not a security boundary or a shell sandbox.
- Redaction recognizes limited known patterns and cannot guarantee detection of every secret.

## Audit log

Operational MCP requests are recorded at:

```text
%LOCALAPPDATA%\codex-serverops-mcp\audit\YYYY-MM-DD.jsonl
```

The directory and daily file receive a protected current-user Windows DACL. A process lock and a
flushed append keep complete JSON lines when multiple MCP processes write. Each schema-version-1
event records time, profile, session, SSH/effective user, tool, action, result status, exit code,
duration, truncation and elevation state. A failed write does not falsify the remote result: the
tool response reports `audit.logged = false`.

For `server_exec`, elevation `exec` and raw-terminal `start`, the log contains only a UTF-8-bounded
redacted preview, SHA-256 of the original command, and flags indicating redaction or truncation.
Raw terminal `write` input is never recorded as command text. Responses expose the same flags
under `audit`. The hash supports correlation but may reveal that two commands were identical.

The logger never includes PTY output, read file content, write content, patches, passwords,
passphrases, private keys or direct authentication input. Known redaction covers Bearer tokens,
labelled password/secret/API-key values, URL user information, common GitHub/cloud/API key shapes
and private-key blocks before preview truncation.

## Operational guidance

Use a dedicated non-root SSH account, narrow sudoers entries, host backups and separate production
approval procedures. Treat JSONL audit files as sensitive operational metadata even after
redaction. Rotate or remove them according to local policy; version 0.1 does not upload or centrally
manage audit data.
