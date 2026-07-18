# Product architecture

This document defines the product boundaries. The development spike remains isolated test
scaffolding; production modules must not import from `codex_serverops_mcp.spike`.

## Process topology

```text
Codex
  -> FastMCP STDIO process
      -> visible local setup process (profile changes only)
      -> local broker client
          -> current-user Task Scheduler task
              -> one per-user broker process
              -> one session-worker process per SSH session
                  -> Windows OpenSSH in ConPTY
                  -> one-use direct authentication channel
                      -> visible local authentication process
```

The MCP process owns no OpenSSH process. The broker owns session metadata but never receives
passwords or passphrases. A worker owns one OpenSSH process for its complete lifetime.

The secured broker/worker lifecycle, MCP session-rediscovery path, direct visible-auth coordinator,
profile-driven product SSH session, separate setup process, structured-file service and guided
elevation service are implemented. Local audit, installer and Doctor are also implemented. The
current FastMCP surface exposes the complete eight-tool product contract. Distribution and manual
release gates remain before the package is labelled `0.1.0`.

## Package boundaries

```text
tools/       FastMCP schemas and thin adapters only
application Application-level composition and use cases
config/      Profile model, TOML codec, locking and atomic repository
broker/      Session registry, worker lifecycle and rediscovery behavior
worker/      Session state machine and exactly one SSH/terminal owner
ipc/         Versioned envelopes, size limits and secured Windows pipes
auth/        One-use auth protocol, launcher and visible local program
setup/       Request store, visible profile UI, key generation and setup operations
ssh/         OpenSSH arguments, prompt recognition and command framing
terminal/    ConPTY primitive, reader and bounded absolute-cursor buffer
files/       Structured remote path and file operations
elevation/   Guided sudo lifecycle and framed elevated command execution
security/    Policy, redaction and audit primitives
installer/   Installation, broker-task, doctor and Codex configuration transactions
```

The dependency direction is inward toward smaller primitives:

```text
tools -> application -> config / broker / files / elevation / security
setup -> config + broker client + terminal primitive + profile audit
broker -> ipc + worker protocol contracts
worker -> ipc + auth + ssh + terminal + files + elevation
auth -> ipc protocol primitives
files -> config model + explicit command-runner contract
elevation -> config model + explicit command-runner contract + SSH prompt constants
installer -> config + broker diagnostics
```

`terminal`, `ssh`, config models and protocol dataclasses do not import application, tools or
GUI code. Broker protocol contracts are kept separate from broker process orchestration so
they can be tested without starting processes.

## Responsibility rules

1. No service mixins. `ApplicationServices` composes explicit dependencies.
2. State transitions live in `worker/state.py`, not in transport or MCP adapters.
3. OpenSSH argument construction lives in `ssh/invocation.py`; no shell command string is
   built for local process startup.
4. Prompt recognition lives in `ssh/prompts.py`, but the worker authorizes prompt kinds from the
   active local operation. Secret transport belongs only to `auth/` and the owning worker;
   arbitrary remote output cannot authorize a dialog.
5. Command framing lives in `ssh/framing.py`; terminal buffering remains unaware of commands.
6. IPC envelope validation and size limits are independent from named-pipe lifecycle code.
7. Public tool handlers perform validation and delegation, not process orchestration.
8. Structured file policy never claims to restrict arbitrary terminal commands.
9. Guided elevation never claims to enforce server-side sudo policy.
10. Audit receives already redacted summaries and never auth payloads.
11. Production source files are held below 450 physical lines by an architecture test. A
    responsibility must be split before that limit is raised.
12. The persistent broker starts only through the exactly validated least-privilege current-user
    task; MCP clients never register or mutate that task implicitly.
13. Both IPC peers verify owner/DACL and prove token possession with nonces and HMACs before
    requests. Any ambiguous receive invalidates that stream.

## Session invariants

- One worker owns exactly one profile, one session ID and at most one OpenSSH process.
- At most one completed command or raw terminal activity is active per session.
- Commands start only from `READY`.
- A timed-out command stays active until interrupted, completed or lost; it is not silently
  marked ready.
- A completed-command result is accepted only after the strict result, working-directory and
  shell-health frame is valid and the original Bash process is still live.
- Loss after command submission and before verified completion and shell health is
  `outcome_unknown` and is never retried automatically.
- `exit`, `logout`, shell replacement through `exec`, disabled required builtins, hostile DEBUG
  traps or any other unverifiable shell synchronization deliberately move the session to `LOST`.
  Arbitrary shell state cannot be made unbreakable.
- A root shell is a separate worker/session and cannot replace an existing normal session.
- MCP action `rediscover` finds broker-owned metadata and the unchanged worker. It neither adopts
  an unowned SSH process nor repairs a lost connection, creates a replacement session or retries a
  command.

## Secret boundary

Passwords and sudo passwords may exist only in the visible auth process, its one-use direct
channel and the owning session worker while being written to OpenSSH. Login-key passphrases use
that same path. A passphrase for a newly generated key exists only in the visible setup process
and its directly owned `ssh-keygen` ConPTY. All are excluded from MCP schemas, broker messages,
profile configuration, normal exceptions and audit events. Host-key decisions use the isolated
auth path even though they are not credentials.

## Verification layers

- Pure unit tests: config, protocol envelopes, state machine, framing, buffers, path policy,
  redaction and audit schema.
- Process tests: broker lifecycle, worker ownership, session rediscovery and IPC failures.
- Optional local Docker integration: OpenSSH, Bash state, disconnects, sudo and remote files;
  public CI does not provision this environment.
- Manual Windows release check: visible setup/auth windows and user-driven confirmations.

The manual release check is never reported as automated.
