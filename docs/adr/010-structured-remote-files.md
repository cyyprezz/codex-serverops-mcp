# ADR 010: Agentless structured remote files

Status: accepted

## Context

Structured file actions must enforce `allowed_roots` on the Linux host, preserve the held SSH
session and avoid introducing a remote agent. Local path normalization alone is insufficient
because symlinks, relative paths and filesystem races exist only on the remote server. Sending
untrusted values as shell syntax would create a command-injection boundary.

## Decision

Run an ephemeral Bash helper through the session worker's existing command runner. Encode all
untrusted values, frame responses with a random token and Base64 cells, and parse them under
strict size and shape limits. Resolve existing paths and allowed roots remotely with `realpath`;
for new entries, resolve the parent and validate the final name separately.

Perform text replacement through a same-directory temporary file with source/transfer/final
hashes and a final canonical-target check. Preserve mode and group only for files owned by the
SSH user. Reject foreign-owned destructive targets and descendants. Apply unified patches
locally against the exact remotely observed text, then write with that observed hash as the
precondition. Never retry an unknown mutation outcome.

Keep command framing, file wire framing, patch application and response mapping as separate
modules. Stream large terminal input in UTF-8-safe bounded chunks and keep Bash continuation
prompts empty so multi-line helpers cannot contaminate protocol output.

## Evidence

The portable helper passes in the disposable BusyBox-based Linux fixture. The Windows product
smoke passes through FastMCP-style application calls, the per-user broker, a worker, ConPTY and
Windows OpenSSH. It covers persistent cwd/virtualenv, stat, a 64 KiB text round trip, atomic
write, patch, stale-hash rejection, search, rename/remove, symlink escape, raw terminal and
reconnect without command retry.

## Consequences

No remote installation or daemon is required, and the two public file tools reuse the normal
session and profile capabilities. The helper depends on documented common Linux commands.
Remote filesystems remain outside our transaction boundary: races, unusual mount semantics and
abrupt loss can defeat cleanup or leave an outcome unknown. `allowed_roots` still do not restrict
arbitrary shell or terminal access.
