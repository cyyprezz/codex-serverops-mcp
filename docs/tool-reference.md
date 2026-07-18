# MCP tool reference

Version `0.1.0` exposes exactly eight public tools. This tool surface is the compatibility
contract for the initial release.

## `server_profiles`

Read-only actions:

- `list` returns non-secret summaries for every local profile.
- `inspect` requires `profile_name` and returns the validated profile fields.

Passwords, passphrases, private-key contents and sudo credentials are absent from both config
and schema. An identity-file path may be shown; the private file is never read by the MCP.

## `server_profile_setup`

Actions that open the separate local program:

- `add` accepts optional `profile_name`, `suggested_host` and `suggested_user`.
- `edit`, `remove` and `test` require `profile_name`.

These actions return `status = user_interaction_required` plus a random `request_id`. The
request contains only non-secret suggestions and is stored below the current-user-only runtime
directory. `status` requires `request_id`; `wait` additionally accepts a bounded
`wait_timeout` from 0.1 through 30 seconds. Neither operation blocks indefinitely.

The local assistant performs the confirmation and any profile mutation. A key-creation
passphrase, login password, key passphrase or host-key answer never becomes an MCP parameter or
setup result. Completed non-secret statuses are `created`, `updated`, `removed` and `tested`;
cancel, expiry and failures are controlled terminal results. Profile mutations, tests, key
generation and public-key installation also report `audit.logged`; an audit-write failure does not
change the operation's real result.

## `server_connection`

Actions:

- `open` requires `profile_name`, starts the per-user broker if necessary, creates a dedicated
  worker and opens its held Bash session.
- `status` requires `session_id` and queries the owning worker.
- `list` returns broker-owned session metadata.
- `rediscover` requires `session_id`, returns the existing broker-owned worker and explicitly
  returns `command_retried = false`. It does not repair a lost SSH connection or create a new
  session.
- `close` requires `session_id` and closes only that worker/session.

Opening a connection may cause `serverops-auth` to appear locally. OpenSSH first invokes that
existing entry point in Askpass-helper mode; a SID-only/HMAC worker relay verifies the invocation
and the selected profile policy before the worker opens the visible DirectAuth window. A host-key
window contains the complete bounded OpenSSH notice, including algorithm and SHA-256 fingerprint.

A direct password profile can request only an account password, while a direct OpenSSH/key profile
can request only a key passphrase. An SSH alias follows OpenSSH configuration and may request
either, but the worker supplies at most one host-key answer and one credential answer. No later
connection prompt is accepted after the credential. Auth input never becomes an MCP parameter,
broker message, environment value, process argument or audit event. See
[`authentication.md`](authentication.md) and
[ADR 015](adr/015-windows-openssh-askpass-boundary.md).

## `server_exec`

Required parameters are `session_id` and `command`; `timeout` is optional. The command runs in
the held Bash shell and returns:

```json
{
  "status": "completed",
  "exit_code": 0,
  "cwd": "/opt/app",
  "output": "...",
  "truncated": false,
  "duration_ms": 420
}
```

PTY output is combined and is not represented as separate stdout/stderr. Completion is accepted
only after the strict result, working-directory and original-shell health records are verified and
the terminal remains live. A disconnect or irrecoverable shell change before then remains
`outcome_unknown`; neither `rediscover` nor any other layer repairs the connection or retries the
command. A timeout can occur after remote side effects and is also never an automatic retry
instruction.

## `server_terminal`

Required parameters are `action` and `session_id`. Actions and their additional fields are:

```text
start      command
read       cursor, optional timeout
write      text
interrupt  -
resize     columns, rows
status     -
close      optional timeout
```

`read` may return as soon as any new terminal chunk arrives. Continue from `next_cursor` until
the desired output appears. `dropped_before_cursor` reports bounded-buffer loss.
The `start` command receives the same redacted preview/hash audit treatment as `server_exec`.
Arbitrary `write` input is never logged as command text. Credential-looking terminal output never
has OpenSSH Askpass provenance and cannot open a connection-authentication dialog. Ordinary raw
terminal use also cannot authorize the sudo dialog.

## `server_files`

Read-only structured UTF-8 access inside the selected profile's `allowed_roots`:

```text
list         path, optional max_results
stat         path
read_text    path, optional byte_limit, optional start_line and end_line
search_text  path, query, optional max_results
hash         path
```

Paths are resolved on the remote server. Existing paths and symlink targets must remain below an
allowed root. `read_text` reports SHA-256, returned and selected byte counts, and truncation; it
rejects NUL/control-byte data and invalid UTF-8. A line range requires both positive endpoints.
Search is fixed-string, bounded, skips NUL-containing files and works with the supported BusyBox
or GNU userland. See [`structured-files.md`](structured-files.md) for limits and caveats.

## `server_file_edit`

Structured normal-user edits inside `allowed_roots`:

```text
write_text   path, content, optional expected_sha256
apply_patch  path, patch, optional expected_sha256
mkdir        path
rename       path, destination_path
remove       path, optional recursive, optional expected_sha256
```

Text and patches are limited to 131072 UTF-8 bytes. File replacement uses a same-directory
temporary file, transfer and result hashes, preserved mode/group metadata, a last-moment source
hash check and `mv`. Existing write targets and destructively edited paths must be owned by the
SSH user; recursive removal and directory rename reject foreign-owned descendants. Hash mismatch
is the controlled `file_conflict` error. Operations with an unknown result are never retried.

## `server_elevation`

Every action requires `session_id`. Guided elevation must be enabled by the selected profile:

```text
acquire             -
status              -
release             -
exec                 command, optional timeout
open_root_session    -
close_root_session   -
```

`status` reports whether a non-interactive `sudo -v` succeeds and does not prompt. `acquire`
uses the visible direct-auth path in interactive mode; non-interactive mode uses only `sudo -n`
and fails rather than falling back to a prompt. `release` invalidates the remote sudo timestamp.
`exec` accepts at most 131072 command bytes, returns combined PTY output and explicitly reports
`elevated = true` and `effective_user = root`. An unverified disconnect is never retried.

`open_root_session` creates a second worker and a second OpenSSH connection running a dedicated
root Bash. It returns that root session's own ID and its parent normal-session ID. Closing the
normal session does not implicitly adopt or merge the root shell; call `close_root_session` with
the root session ID. In interactive mode the worker binds startup sudo to a fresh random nonce in
its custom `sudo -p` prompt; a fake banner without that nonce is ignored. Structured file tools
are disabled in root sessions so they cannot silently create root-owned files. See
[`elevation.md`](elevation.md).

## Tool annotations

Only `server_profiles` and `server_files` are marked read-only. Setup, connection, arbitrary
command, terminal, file-edit and elevation tools use conservative mutating/open-world annotations.
`allowed_roots` restrict only the two structured file tools; server-side accounts, file
permissions and sudoers remain the actual security boundary for shell access.
