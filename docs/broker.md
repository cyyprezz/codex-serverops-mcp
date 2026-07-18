# Per-user broker and worker ownership

The product broker is the long-lived owner of session metadata and one worker subprocess per
session. An MCP client may disconnect without closing those workers. A later client reads the
secured broker status, performs a versioned handshake and rediscovers the unchanged session ID
and worker PID.

## Runtime layout

The default runtime directory is:

```text
%LOCALAPPDATA%\codex-serverops-mcp\runtime
  broker.json
  workers\sess-<random>.json
```

The runtime directories and each status file receive a protected Windows DACL granting full
access only to the current Windows user SID. Writes use a same-directory temporary file,
`fsync`, atomic replacement and a 64 KiB size limit. Duplicate JSON fields and unsafe session
identifiers are rejected.

`broker.json` contains the broker PID, pipe path, protocol version, random instance token and
start time. The token is not passed on a process command line. It is local connection material,
not an SSH credential, and remains inside the SID-restricted runtime directory.

## Ownership and lifecycle

- The deterministic per-user broker pipe enforces a single broker instance.
- A current-user Task Scheduler task with an exact managed description, action digest, execution
  action type, working directory, principal, logon trigger, least-privilege run level and managed
  settings starts the broker outside the disposable MCP STDIO process tree. Any changed property
  is treated as unmanaged. The task stores no password and ignores duplicate starts.
- Each session open starts a separate worker process with a random session ID and a private
  random token inherited through the environment.
- The broker verifies the worker status identity, performs a role-specific handshake and checks
  the worker PID through the connected pipe before publishing the session.
- Closing an MCP client does not close its broker-owned worker.
- `session.close` asks the worker to stop, waits for it and removes only that session's status.
- Explicit broker shutdown closes all owned workers and removes only its own status file.
- A stopped worker is marked `lost`; no command is replayed or automatically retried.
- IPC failure after delivery of an effectful worker request invalidates that worker connection,
  marks the session lost and returns an operation-specific unknown-outcome code.
- After acquiring the unique broker pipe, a replacement broker removes only status records whose
  PIDs are certainly dead. Live or unreadable records are preserved and are never adopted.

The public product path accepts session open, list, status, `rediscover`, exec, terminal and close
operations. Rediscovery returns the existing broker record and unchanged worker; it never repairs
a lost SSH connection, creates a replacement worker or retries a command. `session.create`
remains an internal lifecycle-test operation. Requests and responses use exact-field, bounded IPC
envelopes with correlation IDs. Unknown operations and invalid payloads return controlled error
envelopes.

## Current implementation boundary

The broker starts on first application use through an explicitly installed managed task and
connects stored profiles to the real stateful SSH worker. Without that task, development paths use
direct child startup and therefore do not claim MCP-restart survival. Broker-crash adoption and
computer-restart recovery remain explicit non-goals for version 0.1.
