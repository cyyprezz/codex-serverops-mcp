# ADR 009: Local setup process and public-key transition

Status: accepted

## Context

Profile creation needs rich local confirmation, key selection and optional secrets. Modeling
those values as MCP parameters would expose them to Codex and normal tool logs. A synchronous
tool call would also block STDIO for an unbounded human interaction.

## Decision

Expose one `server_profile_setup` tool with start actions and bounded status/wait actions. Start
a separate visible setup process using only a random request ID. Store the non-secret request and
result under the SID-protected runtime directory and expire incomplete requests after 30 minutes.

Generate Ed25519 keys through a ConPTY-owned `ssh-keygen` process. Supply an optional passphrase
through terminal input, never command arguments or environment. Install only the public line via
an ordinary password-authenticated worker session, avoid duplicates, then test a fresh key login.
Use configuration snapshot hashes to restore local state after failure without overwriting a
concurrent edit.

## Evidence

Pure and Windows tests cover the request contract, secret-field rejection, launcher arguments,
profile drafts, key-generation prompt flow, public-key command, rollback and MCP surface. A real
Windows ConPTY smoke generated an Ed25519 pair and removed it afterward. During that smoke,
Windows OpenSSH exposed a DACL edge case: it creates the user-owned private file without
`WRITE_OWNER`. Path hardening now avoids resetting an already-correct owner and changes only the
DACL, with a regression test.

## Consequences

The MCP never receives setup secrets and remains restartable while a local request is pending.
The setup process may use the broker for connection tests and public-key installation but never
sends a secret in broker messages. Visible UI behavior and the human-driven install flow remain
manual release checks before `0.1.0`.
