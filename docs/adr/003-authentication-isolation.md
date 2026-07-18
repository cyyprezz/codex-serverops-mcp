# ADR 003: Authentication isolation

Status: accepted; visible desktop behavior remains a manual release check

## Context

Passwords, private-key passphrases and sudo passwords must never enter MCP parameters,
responses, broker messages or audit logs. Host-key decisions also need a visible local context.

## Decision

The session worker creates a single-use random local pipe and launches a separate visible auth
program. The UI connects directly to that worker, receives only non-secret context plus the
current prompt, and returns the user's input directly. It reports only success, cancellation,
timeout or failure outside that direct channel.

Every auth request has a random request ID, a fresh 256-bit connection key, a 16,384-byte
message limit and an exact worker-protocol version. The listener accepts once and then closes.
Unknown or mismatched responses fail closed. Auth input is never logged.

## Spike automation exception

The repeatable automated Docker run generated disposable credentials inside the ignored
runtime directory and let the worker read them locally. Their values did not cross the broker,
were not printed and were deleted after success. This is test scaffolding, not a product
credential-storage design. The manual mode uses the visible direct pipe.

## Product evidence

The product auth program now uses the secured native pipe primitive. Automated Windows tests
cover the effective SID-only DACL, invalid tokens, reuse, expiry, all supported response types,
UI cancellation, timeout and mutable-buffer clearing. The token is inherited through the auth
process environment and never appears in its command line. Architecture tests keep the broker
outside the direct worker/UI boundary.

The automated client is intentionally headless. Actual top-level visibility, input masking,
focus and close behavior remain the documented manual Windows release check and are not claimed
as automated.

## Consequences

Authentication failure terminates the ambiguous SSH process. The broker may report only the
resulting non-secret session status. Python, Tk and operating-system memory copies cannot be
fully zeroed, so the guarantee is limited to routing, persistence, logging and best-effort
clearing of mutable application buffers.
