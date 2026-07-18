# ADR 003: Authentication isolation

Status: accepted; visible desktop behavior remains a manual release check

## Context

Passwords, private-key passphrases and sudo passwords must never enter MCP parameters,
responses, broker messages or audit logs. Host-key decisions also need a visible local context.

## Decision

The session worker creates a single-use random local pipe and launches a separate visible auth
program. The UI connects directly to that worker, receives only non-secret context plus the
current prompt, and returns the user's input directly. The worker accepts SSH prompts only during
connection startup and sudo prompts only during explicit elevation; remote command or raw-terminal
output cannot authorize the auth program. It reports only success, cancellation, timeout or
failure outside that direct channel.

Every auth request has a random request ID, a fresh 256-bit connection key, a 16,384-byte
message limit and an exact worker-protocol version. The listener accepts once and then closes.
Unknown or mismatched responses fail closed. Auth input is never logged.

## Current-product amendment (2026-07-18)

The original one-use worker/UI DirectAuth channel remains the visible-input boundary, but it no
longer treats connection-looking ConPTY text as proof that OpenSSH requested a credential.
Connection authentication now uses Windows OpenSSH Askpass as its provenance boundary, as decided
in [ADR 015](015-windows-openssh-askpass-boundary.md).

OpenSSH invokes the existing `serverops-auth` entry point in helper mode with
`SSH_ASKPASS_REQUIRE=force`. The helper authenticates to a random current-user-SID-only worker pipe
with a role-bound nonce/HMAC handshake. The worker applies the selected profile policy and only
then launches the normal visible DirectAuth UI. The response path is
`UI -> worker -> short-lived relay buffer -> Askpass stdout -> OpenSSH`; secrets never enter MCP,
broker, environment values, process arguments or audit.

Direct password permits host key plus account password. Direct OpenSSH permits host key plus key
passphrase and disables account-password/keyboard-interactive authentication. SSH aliases follow
OpenSSH configuration but receive at most one credential response. All modes permit at most one
complete host-key decision, and every connection prompt is rejected after the credential answer.
Completed-command and raw-terminal output cannot invoke Askpass.

Sudo remains a separate operation-authorized PTY path. Interactive root startup binds its custom
`sudo -p` text to a fresh worker nonce so a matching-looking banner cannot authorize DirectAuth.
This decision does not claim protection from a malicious genuine PAM challenge or a fully
compromised process already running as the same Windows user.

## Spike automation exception

The repeatable automated Docker run generated disposable credentials inside the ignored
runtime directory and let the worker read them locally. Their values did not cross the broker,
were not printed and were deleted after success. This is test scaffolding, not a product
credential-storage design. The manual mode uses the visible direct pipe.

## Product evidence

The product auth program and Askpass relay use the secured native pipe primitive. Automated
Windows tests cover the effective SID-only DACL, invalid tokens, HMAC role, reuse, expiry, all
supported response types, UI cancellation, timeout, real helper entry point, profile mismatch,
post-credential rejection and mutable-buffer clearing. Capability tokens are inherited through
the respective child environments and never appear in command lines; credentials are never
environment values. Architecture tests keep the broker outside the direct worker/UI boundary.

The automated client is intentionally headless. Actual top-level visibility, input masking,
focus and close behavior remain the documented manual Windows release check and are not claimed
as automated.

## Consequences

Authentication failure terminates the ambiguous SSH process. The broker may report only the
resulting non-secret session status. Python, Tk and operating-system memory copies cannot be
fully zeroed, so the guarantee is limited to routing, persistence, logging and best-effort
clearing of mutable application buffers.
