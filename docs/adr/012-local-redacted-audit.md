# ADR 012: Local redacted operational audit

## Status

Accepted for the 0.1 architecture.

## Context

Operational traceability requires tool and result metadata, but arbitrary commands, terminal
output and file content may contain credentials. Logging whole requests or responses would breach
the authentication and content boundary.

## Decision

The MCP application appends schema-versioned daily JSONL events below LocalAppData. Files use a
current-user DACL and a cross-process lock. Broker responses carry non-secret session identity so
the application can record profile, SSH user, effective user and elevation without another remote
request.

Only arbitrary command text is summarized: known patterns are redacted, the preview is bounded,
and the original command is represented by SHA-256. Output and structured file content are never
passed to the logger. Tool responses state whether the event was written and whether its command
preview was redacted or truncated.

## Current-product amendment

The same protected logger now records local profile and setup lifecycle actions. Its allowlist is
limited to profile name, result status, connection/authentication modes, environment label,
terminal/file capability flags, elevation mode and root-session flag. It excludes full host/IP,
full key paths, public-key lines, configuration content and secrets. The covered action families
are profile create/update/remove/test, key generation and public-key installation, including
failure and unknown-outcome events.

As with remote actions, an audit append failure is reported as `audit.logged = false` and does not
falsely turn a successful local mutation into a failure.

## Consequences

- Authentication input cannot enter audit through an MCP or broker field.
- Audit failure remains visible without changing an already executed remote outcome.
- The original-command hash enables equality correlation and is therefore still sensitive
  metadata.
- Pattern redaction is explicitly defense in depth, not a promise to recognize every secret.
