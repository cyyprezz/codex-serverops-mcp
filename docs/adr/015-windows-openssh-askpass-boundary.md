# ADR 015: Windows OpenSSH Askpass as the connection-prompt boundary

Status: accepted

## Context

Connection prompt text previously arrived in the same ConPTY output stream as SSH banners,
remote shell output and interactive programs. Pattern matching can classify text, but it cannot
prove that Windows OpenSSH rather than the remote endpoint produced it. A server could therefore
print strings resembling an account-password, key-passphrase, host-key or sudo prompt and cause a
misleading local authentication window during startup.

ServerOps needs a provenance boundary that preserves the held Windows OpenSSH/ConPTY session,
keeps the visible DirectAuth UI worker-local, and keeps every credential outside MCP, broker,
environment values, command-line arguments and audit.

## Reproduced Windows feasibility

The committed `spike/askpass` probe ran native Windows OpenSSH 9.5p2 inside the same held ConPTY
shape as the product with `SSH_ASKPASS_REQUIRE=force`. A disposable Docker SSH server printed all
four of these strings in its pre-authentication banner and MOTD:

```text
password:
Enter passphrase for key C:\Users\user\.ssh\id_ed25519:
[sudo] password for deploy:
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

The probe reached the held Bash shell in three separate cases and counted helper process launches,
not matching output text. A fresh host key caused exactly one host-key Askpass invocation, direct
password login caused exactly one account-password invocation, and an encrypted private key
caused exactly one key-passphrase invocation. The fake banner was visible in every case and caused
no additional helper launch.

The feasibility helper used only disposable generated fixture values in its private environment
to isolate OpenSSH behavior. The runner removes its container, image, credentials, keys and
runtime directory in `finally`. That fixture mechanism is not the product secret path.

## Decision

Use forced Windows OpenSSH Askpass as the provenance boundary for connection prompts. The worker
sets `SSH_ASKPASS_REQUIRE=force` and supplies the existing `serverops-auth` entry point as
`SSH_ASKPASS`; no additional public executable is introduced. When invoked with the worker-issued
mode, pipe and capability variables, that entry point behaves only as a minimal Askpass helper.

The helper authenticates to a random worker-local named pipe. Its DACL grants access only to the
current Windows user SID, and the helper proves the `askpass` role and random token through the
standard nonce/HMAC handshake. It forwards the bounded OpenSSH prompt, receives one authorized
response and writes that response only to Askpass stdout. Capability metadata may be inherited in
the environment; a password, passphrase or host-key response may not.

The worker applies a stateful profile policy before it invokes the existing visible DirectAuth
coordinator:

- direct `interactive_password`: complete host-key notice and account password only;
- direct `openssh`: complete host-key notice and key passphrase only, with account-password and
  keyboard-interactive authentication disabled in OpenSSH arguments;
- SSH alias: follow the user's OpenSSH configuration, allowing either account password or key
  passphrase.

Every policy permits at most one host-key answer and one credential answer. After a credential is
answered, every later connection prompt fails closed. Credential prompt text is limited to 500
characters. A host-key notice is limited to 2048 characters and must retain the authenticity
statement, key algorithm, SHA-256 fingerprint and confirmation question.

The product secret path is exactly:

```text
visible serverops-auth UI
  -> one-use DirectAuth channel
  -> owning worker
  -> short-lived relay buffer
  -> serverops-auth Askpass-helper stdout
  -> Windows OpenSSH
```

It never includes MCP, broker, environment values, process arguments, profile configuration,
normal results, exception payloads or audit events. Mutable UI, wire, worker, relay and helper
buffers are cleared on a best-effort basis.

Sudo is not moved to Askpass. It occurs inside the established remote PTY and is authorized only
for an explicit interactive elevation operation. Interactive root-session startup uses a fresh
random nonce in the worker-selected `sudo -p` prompt; sudo-looking output without that nonce is
ignored. `server_exec` and raw-terminal activity never authorize connection prompts, and ordinary
non-elevation output never authorizes sudo.

## Consequences and limits

- Credential-looking banner, completed-command and raw-terminal text cannot acquire OpenSSH
  Askpass provenance merely by matching a prompt pattern.
- Connection cancellation, rejection, timeout, mismatch or ambiguity terminates the owning SSH
  startup rather than leaving a hidden prompt.
- Premature OpenSSH exit cancels any active DirectAuth challenge, terminates the visible process,
  closes its accepted pipes and requires the worker relay thread to stop before cleanup returns.
- The visible UI and its existing DirectAuth protocol remain unchanged; one executable has two
  strictly selected local roles.
- Windows OpenSSH behavior is now a release compatibility requirement. The committed probe is the
  reproducible gate for the forced-Askpass/ConPTY combination.
- Askpass proves that OpenSSH invoked the helper. It does not prove that a genuine server-side PAM
  challenge is benevolent; trusted server configuration remains necessary.
- Current-user ACLs and random HMAC capabilities separate local roles but do not protect against a
  process already fully compromised as the same Windows user.
- Python, Tk, OpenSSH and Windows can create internal memory copies that application code cannot
  reliably lock or erase. The guarantee is about routing, persistence and logging, with
  best-effort clearing of mutable application buffers.

## Reproduce

From the repository root on Windows with Docker Desktop available:

```powershell
.\.venv\Scripts\python.exe .\spike\askpass\probe.py
```

The probe is isolated from product profiles and known-hosts files. Product-level regression tests
add the real `serverops-auth` entry point, SID-only/HMAC relay, exact prompt policies,
post-credential rejection, cancellation and timeout coverage.
