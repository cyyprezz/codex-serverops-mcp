# Structured remote files

`server_files` and `server_file_edit` operate without installing an agent on the Linux server.
The worker executes a bounded Bash helper in the already-held SSH session and parses a token-bound,
Base64-framed response. File contents and untrusted path/query values are encoded; they are not
interpolated as shell syntax.

## Scope and capabilities

Both tools require a ready session. `server_files` additionally requires `allow_file_read`;
`server_file_edit` requires both `allow_file_read` and `allow_file_write` in the profile. The
normal SSH user performs every remote operation. No structured file action uses sudo.
Both tools are unavailable on a dedicated root session; this avoids accidental root ownership
and keeps their ownership and allowed-root contract tied to the configured SSH user.

`allowed_roots` are a policy only for these two tools. They do not sandbox `server_exec` or
`server_terminal`, and they cannot replace a restricted server account, Unix permissions or
server-side sudoers rules.

## Remote path checks

Existing targets are resolved with `realpath` on the server and compared against the freshly
resolved allowed roots. For a new entry, the helper resolves the existing parent, checks that
parent, validates the final name separately and rejects empty names, `.`, `..` and names starting
with `-`. Requested paths and configured roots reject control characters and are capped at 4096
UTF-8 bytes.

Directory listing does not follow child symlinks. Operations that dereference an existing symlink
reject it when its canonical target leaves every allowed root. Rename and removal also verify the
canonical parent and target immediately before mutation. An allowed root itself cannot be renamed
or removed.

## Read contract

- `list` defaults to 200 entries and accepts at most 1000.
- `read_text` defaults to 65536 bytes. Its effective maximum is 1 MiB or the smaller amount that
  fits the profile's bounded terminal output.
- A line selection requires `start_line` and `end_line`; both are positive and the span is capped.
- NUL bytes, non-whitespace control bytes and invalid UTF-8 produce controlled errors. A truncated
  final UTF-8 code point is omitted instead of returned as replacement text.
- `search_text` accepts a non-empty, single-line fixed string of at most 2048 UTF-8 bytes and at
  most 500 results. NUL-containing files are skipped.
- `hash` returns lowercase SHA-256 for a regular file.

## Edit contract

`write_text` and `apply_patch` accept at most 131072 UTF-8 bytes. A caller may pass the SHA-256 it
previously observed. A mismatch fails as `file_conflict` before replacement. `apply_patch` accepts
unified-diff hunks, requires exact current context and then uses the hash observed by its own read
as the write precondition.

Replacement creates a temporary file in the destination directory, transfers Base64 in bounded
terminal lines, verifies the temporary hash, preserves the existing mode and group, rechecks the
resolved target and source hash, calls `sync` best-effort, moves the temporary file and verifies
the final hash. Temporary files are removed on a handled failure. Existing write targets must be
owned by the SSH user.

Rename and removal require the edited entry to be owned by the SSH user. Directory rename and
recursive removal also reject any descendant owned by another user. `mkdir` creates mode `0700`.
Non-recursive removal refuses non-empty directories. An optional expected hash can protect file
removal.

## Honest limitations

The helper narrows common symlink and time-of-check/time-of-use risks but does not create a fully
transactional remote filesystem. Another process with sufficient rights can race a checked path;
mounts and network filesystems may give `mv`, `sync`, ownership or metadata semantics different
from a local Linux filesystem. Rename and creation cannot promise cross-filesystem atomicity.
Abrupt SSH or machine loss can leave a same-directory `.serverops.*` temporary file.

If the connection ends after mutation but before the result frame, the response is
`file_outcome_unknown`. The operation is not retried automatically. A caller must reconnect and
inspect the remote hash or path state.

The remote host needs Bash plus common Linux commands including `realpath`, `base64`, `stat`,
`sha256sum`, `find`, `grep`, `od`, `sed`, `head`, `wc`, `mktemp`, `mv`, `chmod` and `chgrp`.
Doctor reports the exact missing utilities before structured file work begins.

## Automated evidence

Unit tests cover input limits, path/value encoding, response framing, UTF-8 and binary handling,
patch conflicts, capability flags and ownership guards. Optional local disposable-container and
Windows product smokes cover write/read/patch/search, symlink escape, foreign ownership, a 64 KiB
transfer, persistent shell state, raw terminal and reconnect without retry. Public CI runs the
unit contract but does not provision that real SSH environment.
