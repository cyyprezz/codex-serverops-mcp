# Visible authentication isolation

ServerOps separates connection authentication from terminal output by using Windows OpenSSH
Askpass as the provenance boundary. OpenSSH must invoke the configured helper with
`SSH_ASKPASS_REQUIRE=force`; text that merely appears in the ConPTY stream is never treated as a
host-key, account-password or key-passphrase request.

The existing `serverops-auth` entry point has two local roles. In normal mode it is the visible Tk
window. When OpenSSH starts it with the worker-issued Askpass environment, it is a minimal helper
that forwards the OpenSSH prompt to the owning worker and writes only the authorized response to
Askpass stdout. It does not display a second credential UI or carry a secret in its environment or
command line.

The visible window still uses the worker's DirectAuth coordinator. It displays the profile,
target, user and original bounded prompt. Password and passphrase inputs are masked. A host-key
request preserves the complete bounded OpenSSH notice, including key algorithm and SHA-256
fingerprint, and requires an explicit confirm or reject decision.

## Direct data path

```text
OpenSSH -> invokes serverops-auth in Askpass mode
prompt  -> Askpass helper -> SID-only/HMAC worker relay -> DirectAuth worker coordinator
                                                       -> visible serverops-auth window

secret  <- Askpass stdout <- short-lived relay buffer <- owning worker <- DirectAuth UI response
```

The MCP and broker are not part of either local channel. A credential follows only
`UI -> worker -> short-lived relay buffer -> Askpass stdout -> OpenSSH`. It is never an MCP
parameter, broker message, profile value, environment variable, process argument, normal result,
exception payload or audit event. Mutable UI, wire, relay and worker buffers are cleared on a
best-effort basis after use.

The worker relay uses a random named-pipe path with a current-user-SID-only Windows DACL and a
fresh random token. The helper and relay perform the role-bound nonce/HMAC handshake before a
prompt is accepted. The capability token and pipe name are inherited through the child
environment; they are not credentials. The helper removes its inherited copies immediately, and
the capability becomes unusable when the relay closes. Invalid handshakes, malformed requests,
timeouts and ambiguous connection state fail closed.

For every visible DirectAuth request the worker separately creates a fresh request ID, token and
one-use SID-only pipe. The UI receives only the bounded prompt and non-secret target context. Its
response goes directly to the worker; the broker cannot observe it.

## Connection prompt policy

The worker classifies and authorizes an Askpass invocation before opening the visible window:

- a direct `interactive_password` profile permits one complete host-key decision and one account
  password; public-key authentication is disabled in the OpenSSH arguments;
- a direct `openssh` profile permits one complete host-key decision and one private-key
  passphrase; account-password and keyboard-interactive authentication are disabled;
- an SSH-alias profile follows the user's OpenSSH configuration and may request either an account
  password or a key passphrase, but still receives at most one credential answer;
- at most one host-key answer and one credential answer are accepted, and after a credential has
  been answered every later connection prompt is rejected.

Credential prompts are limited to 500 characters. A host-key request is limited to 2048
characters and is accepted only when the complete notice contains the authenticity statement,
algorithm, SHA-256 fingerprint and confirmation question. An incomplete confirmation line is not
enough.

`server_exec` and `server_terminal` output can never invoke Askpass or authorize a connection
dialog. Sudo is intentionally separate: only an explicit interactive elevation operation may
authorize a PTY sudo prompt, and every interactive `acquire`, elevated `exec` and root-session
startup binds its custom `sudo -p` text to a fresh random operation nonce. A matching-looking
banner without the exact current nonce is ignored. Guided operations resolve the Ubuntu system
sudo by absolute path; non-interactive elevation always uses `sudo -n`.

## Outcomes and limits

The worker maps local outcomes to controlled statuses:

```text
authentication_cancelled
authentication_rejected
authentication_timeout
authentication_failed
```

A host-key confirmation supplies only `yes`; rejection never silently trusts the server. A
credential response is limited to 4096 bytes and cannot contain a line ending. If connection
authentication is cancelled, rejected, timed out or becomes ambiguous, the owning SSH process is
terminated rather than left at a hidden prompt.

Askpass proves that OpenSSH invoked the helper; it does not prove that a genuine server-side PAM
challenge is benevolent. The strict profile and prompt-count rules reduce that exposure but do
not replace trusted server configuration. Current-user pipe ACLs and HMAC capabilities also do
not protect against a fully compromised process already running as the same Windows user. Python,
Tk and Windows may create internal memory copies that cannot be reliably locked or overwritten,
so the promise concerns routing, persistence and logging, with best-effort mutable-buffer clearing.

ServerOps uses its own protected `known_hosts` file below the local configuration directory.
Trusting a displayed fingerprint therefore affects ServerOps connections, not the user's normal
OpenSSH `known_hosts` file.

## Verification boundary

Automated Windows tests cover the pipe DACL and HMAC role, the real existing `serverops-auth`
entry point in Askpass mode, full host-key notices, direct-password/direct-key/alias policy,
prompt-count limits, post-credential rejection, fake terminal banners, cancellation, rejection,
timeout, response bounds and buffer clearing. The reproducible Windows/OpenSSH spike and product
decision are recorded in [ADR 015](adr/015-windows-openssh-askpass-boundary.md).

Protocol automation does not claim that a real window was visible. Window layout, masking, focus,
close behavior and taskbar presence remain a manual Windows release check.

The optional passphrase entered while creating a new key is a separate setup concern. It stays
inside `serverops-setup` and its directly owned `ssh-keygen` ConPTY. Later logins with that
protected key use the Askpass path described above.
