# ADR 006: Current-user secured Windows named pipes

Status: accepted

## Context

The spike proved named-pipe topology with a random authentication key but did not prove the
default pipe DACL. Product IPC requires an explicit current-Windows-user authorization boundary
that can be inspected and tested.

## Decision

Use `pywin32` 312 for native named-pipe creation and security descriptors. Each listener owns
an explicit DACL granting access only to the current process token's user SID. Remote clients
are rejected and the effective kernel DACL is read back before use.

Use length-prefixed, size-limited, exact-field JSON envelopes plus a versioned handshake and a
random per-broker instance token. Do not reuse `multiprocessing.connection` in product IPC.

## Consequences

Product IPC is Windows-specific by design and pywin32 is a Windows-only pinned dependency.
The same secured primitive must be used by broker, worker and one-use authentication channels;
no caller may create a less restricted fallback pipe.
