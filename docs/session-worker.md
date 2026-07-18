# Session worker core

The product worker core promotes only the transport behavior proven by the Windows spike. It
does not import spike orchestration.

## Modules

- `ssh/invocation.py` builds a Windows OpenSSH argument list from a validated profile.
- `ssh/prompts.py` incrementally classifies host-key, password, key-passphrase and sudo prompts.
- `ssh/framing.py` provides random command frames and a bounded incremental parser.
- `terminal/contracts.py` defines the terminal capability required by a worker.
- `worker/state.py` owns the explicit session state machine.
- `worker/authentication.py` defines the worker-local one-use response capability.
- `worker/session.py` owns completed stateful commands and session lifecycle.
- `worker/interactive.py` owns raw terminal actions independently from completed commands.
- `ssh/target.py` resolves direct targets or delegates aliases to `ssh -G`.
- `worker/service.py` composes profile, target, visible auth and stateful session behavior.
- `worker/protocol.py` validates the exact broker-to-worker operation contract.
- `worker/process.py` hosts that service in the broker-owned worker subprocess.

## Completed command behavior

Commands start only from `READY`. A random frame returns combined PTY output, exit code and
remote working directory. Output is bounded; if the configured limit is exceeded, the newest
portion is returned with `truncated = true`.

Only one command may be active. A connection loss before the end frame is `outcome_unknown`
and is never retried. A timeout sends the proven remote `VINTR` byte and a recovery frame. The
session becomes `READY` only if that frame is observed; otherwise it becomes `LOST`.

## Raw terminal behavior

The raw controller supports start, cursor-based read, UTF-8 write, interrupt, resize, status
and close. Reads may return as soon as any new terminal chunk arrives, so callers continue from
`next_cursor` until their desired output appears. Buffer loss is reported through
`dropped_before_cursor`.

Closing raw mode sends the proven interrupt and then a framed no-op. The state returns to
`READY` only after Bash executes that synchronization frame. Failure to prove control returned
is a controlled session failure.

## Authentication boundary

The session does not accept passwords as `open` or `execute` parameters. When a prompt is
detected, a worker-local authentication coordinator receives a single-use `SecretInputSink`.
The sink writes directly to the owned terminal and overwrites the supplied mutable byte buffer
after use. The production visible auth process and SID-restricted one-use pipe implement that
coordinator.

## Current verification

Unit tests cover every state transition, prompt classification, bounded framing, timeout,
manual interrupt, raw cursor reads and secret-buffer clearing. The Docker/OpenSSH spike also
executes the product core against real Windows ConPTY with all four prompt kinds, persistent
working directory, sudo, protected-key login and a live raw `cat` session.

The full product smoke additionally traverses application, auto-started broker, dedicated worker
process and real Docker SSH. It verifies profile opening, persistent working directory, persistent
virtual environment, exit code, cursor-based raw terminal and MCP-style reconnect without command
retry.
