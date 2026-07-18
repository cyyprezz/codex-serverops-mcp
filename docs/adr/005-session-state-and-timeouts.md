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

## Current-product amendment

The original phrase "valid recovery frame" now means a strict line-delimited result and health
sequence bound to the original non-exported readonly Bash identity, enabled required builtins and
a live terminal process. A normal completion is subject to the same checks. `exit`, `logout`,
shell replacement through `exec`, an interfering DEBUG trap, disabled framing builtins or any
other unverifiable synchronization moves the session to `LOST`. If a command was already
delivered, its result is `outcome_unknown`; neither timeout recovery nor any later layer retries
it. This is controlled failure behavior, not a claim that arbitrary shell state is unbreakable.

## Consequences

The worker never reports a session ready based only on elapsed time or a successful write.
Interactive programs that alter terminal behavior may fail the synchronization step and close
or fail the session rather than leave ambiguous shared state.
