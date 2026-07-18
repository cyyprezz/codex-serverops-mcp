# ADR 011: Guided sudo and separately owned root sessions

## Status

Accepted for the 0.1 architecture.

## Context

Server operations sometimes require root privileges, but putting sudo passwords in MCP arguments,
broker messages or configuration would violate the secret boundary. Replacing a normal worker's
shell with a root shell would also destroy state and blur ownership.

## Decision

One elevation tool exposes an explicit lifecycle. Short elevated commands run through framed
sudo in the held normal session. Interactive passwords use the existing one-use direct auth pipe;
non-interactive mode always uses `sudo -n` and fails closed.

A long-lived root shell is a new worker and OpenSSH process with its own session ID and a recorded
normal parent. The worker verifies UID zero before readiness. Structured file operations and
nested elevation are disabled there. Root sessions close explicitly and never replace or adopt a
normal session.

Broker and worker protocol versions advance together because root-session metadata and elevation
operations change their contracts.

## Consequences

- MCP and the broker never receive sudo secrets.
- Normal and root shell state remain separate and observable.
- Server-side sudoers remains the actual authorization boundary.
- Non-interactive automation is deterministic and cannot unexpectedly open a password prompt.
- Interactive auth behavior and window focus remain a manual Windows release gate.
- A caller must explicitly close both normal and root sessions when both were opened.
