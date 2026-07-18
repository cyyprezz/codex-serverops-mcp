# ADR 005: Session state, timeouts and raw terminal ownership

Status: accepted

## Context

A blocking completed command, a raw terminal program and an authorized authentication prompt can
all use the same OpenSSH terminal. Authentication is forbidden during raw-terminal operation.
Treating them as unrelated calls would allow concurrent writes or incorrectly mark a still-running
command ready after a timeout.

## Decision

Each worker has one explicit state machine. Completed commands and raw terminal mode are
separate controllers sharing that state and the worker-owned terminal.

A completed command timeout actively interrupts the remote foreground process and requires a
valid recovery frame before returning the session to `READY`. A raw terminal is left only after
an interrupt plus a framed Bash synchronization command. Connection loss before a command end
frame is `outcome_unknown` and cannot trigger a retry.

Authentication is a temporary substate of connection startup or explicit elevation that returns
to the exact prior state after the direct worker-local response is written.

## Consequences

The worker never reports a session ready based only on elapsed time or a successful write.
Interactive programs that alter terminal behavior may fail the synchronization step and close
or fail the session rather than leave ambiguous shared state.
