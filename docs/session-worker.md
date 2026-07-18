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

Commands start only from `READY`. A random, strict line-delimited frame returns combined PTY
output, exit code and remote working directory, followed by a health record for the original Bash
shell. Technical records use explicit Bash builtins and do not depend on aliases or `PATH`.
Output is bounded; if the configured limit is exceeded, the newest portion is returned with
`truncated = true`.

Only one command may be active. Completion requires the complete begin/debug/end/cwd/health
sequence, the original non-exported readonly shell identity, enabled required builtins and a live
terminal process. A connection or shell loss before that verification is `outcome_unknown` and is
never retried. A timeout sends the proven remote `VINTR` byte and a recovery frame. The session
becomes `READY` only after the same shell-health and liveness checks pass; otherwise it becomes
`LOST`.
Timed-out commands may already have produced side effects before interruption and are never safe
to retry merely because their completion frame was not returned.

Commands may intentionally change ordinary Bash state, including the working directory,
variables, virtual environments and shell options. State that destroys or replaces the original
shell cannot be made safe: `exit`, `logout`, `exec`, a disabled required builtin, an interfering
DEBUG trap or malformed synchronization causes controlled session loss rather than a false
successful result followed by a claimed-ready session. Marker strings correlate PTY records; they
are not a security boundary or a shell sandbox.

## Raw terminal behavior

The raw controller supports start, cursor-based read, UTF-8 write, interrupt, resize, status
and close. Reads may return as soon as any new terminal chunk arrives, so callers continue from
`next_cursor` until their desired output appears. Buffer loss is reported through
`dropped_before_cursor`.

Closing raw mode sends the proven interrupt and then a framed no-op. The state returns to
`READY` only after the strict frame, original-shell health and terminal-liveness checks pass.
Failure to prove that control returned moves the session to `LOST`; the interactive outcome is
reported as unknown rather than retried.

## Authentication boundary

The session does not accept passwords as `open` or `execute` parameters. Prompt kinds are allowed
only by the active local operation: SSH credentials during connection startup and sudo only during
explicit elevation. Matching normal command or raw-terminal output is ignored. For an authorized
prompt, a worker-local authentication coordinator receives a single-use `SecretInputSink`.
The sink writes directly to the owned terminal and overwrites the supplied mutable byte buffer
after use. The production visible auth process and SID-restricted one-use pipe implement that
coordinator.

## Current verification

Unit tests cover every state transition, adversarial prompt spoofing, prompt classification,
bounded framing, timeout, manual interrupt, raw cursor reads, shell replacement/termination,
disabled builtins, changed shell options, hostile DEBUG traps, invalid recovery and
secret-buffer clearing. Local
Docker/OpenSSH development scripts can additionally exercise the product core against Windows
ConPTY with all four prompt kinds, persistent working directory, sudo, protected-key login and a
live raw `cat` session; public CI does not run that environment.

The optional full product smoke traverses application, auto-started broker, dedicated worker
process and Docker SSH. It verifies profile opening, persistent working directory, persistent
virtual environment, exit code, cursor-based raw terminal and MCP session rediscovery without
command retry.
