# Visible authentication isolation

`serverops-auth` is a separate local Tk window started by the session worker for exactly one
locally authorized OpenSSH or sudo prompt. It displays the profile, target, user and original
prompt. Password and passphrase inputs are masked; host keys show the bounded OpenSSH notice,
including key algorithm and fingerprint, and require an explicit confirm or reject decision.

Credential prompts are operation-bound. Host-key, SSH-password and key-passphrase prompts are
accepted only while OpenSSH is establishing a configured connection. A sudo prompt is accepted
only while an explicit interactive elevation action or root-session opening is executing. Text
printed by `server_exec` or an interactive remote program can never open an authentication
window, even when it resembles a password prompt.

## Direct data path

```text
OpenSSH prompt -> session worker -> one-use SID-only pipe -> serverops-auth
OpenSSH input  <- session worker <- direct response       <- local operator
```

The MCP and broker are not part of this path. Architecture tests prevent the broker from
importing the auth implementation and prevent the auth program from importing broker or worker
implementation modules. The worker is the only component that receives the direct response and
writes it to its owned OpenSSH terminal.

For each prompt the worker creates:

- a fresh 128-bit request ID,
- a fresh 256-bit connection token,
- a random named-pipe path with a current-user-only Windows DACL,
- a wall-clock expiry shown to the client and an independent monotonic server deadline,
- an exact worker-protocol version and a 16 KiB transport limit.

The token is inherited by the auth child through its environment and removed there immediately.
It is never placed on the process command line. A wrong token is rejected without consuming the
request; a successfully authenticated request is consumed once. Reuse, unknown response types,
oversized responses, disconnects and expired requests fail closed.

## Outcomes

The worker maps local outcomes to controlled statuses:

```text
authentication_cancelled
authentication_rejected
authentication_timeout
authentication_failed
```

A host-key confirmation sends only `yes`; rejection does not silently trust the server. A
credential response is limited to 4096 bytes and cannot contain a line ending. Mutable client,
wire and worker response buffers are overwritten after use. If auth is cancelled or becomes
ambiguous, the owning SSH process is terminated instead of leaving a hidden password prompt.

Python, Tk and Windows may create internal memory copies that cannot be reliably locked or
overwritten. The product therefore promises no persistence, logging or routing through MCP and
broker—not an impossible guarantee that a credential never exists in process memory while it is
being entered and transmitted.

ServerOps uses its own protected `known_hosts` file below the local configuration directory.
Trusting a displayed fingerprint therefore affects ServerOps connections, not the user's normal
OpenSSH `known_hosts` file.

## Verification boundary

Automated Windows tests cover the pipe DACL, correct and incorrect tokens, single use, expiry,
all four prompt kinds, cancellation, rejection, timeout, response bounds and buffer clearing.
They use a headless protocol client and do not claim that a real window was visible. Window
layout, masking, focus, close behavior and taskbar presence remain a private manual release check.

The coordinator implements the `StatefulSshSession` authentication contract and is composed by
the broker-created product worker. The headless product smoke preloads its disposable fixture
host key and uses key authentication, so it does not replace the manual visible-window check.

The optional passphrase entered while creating a new key is a separate setup concern. It stays
inside `serverops-setup` and its directly owned `ssh-keygen` ConPTY; it is not sent through this
auth protocol. Later logins with that protected key use the direct auth path described above.
