# Manual real-SSH and visible-authentication gates for 0.1.1

Run these gates on the exact candidate commit and wheel using a disposable non-root Linux account.
Back up `authorized_keys`; use a dedicated test root; never enter a production host, customer name,
credential, or private key in evidence.

## Visible OpenSSH authentication

- Direct target and existing SSH alias each connect successfully.
- Password and encrypted-key passphrase appear only in separate masked ServerOps windows.
- A new host key shows host, algorithm, and fingerprint and requires explicit accept/reject.
- Reject, close, and timeout each return controlled non-secret results.
- No credential or capability token appears in MCP arguments, stdout, audit, config, or process
  command lines.

Follow [manual-auth-checklist.md](manual-auth-checklist.md) and
[manual-setup-checklist.md](manual-setup-checklist.md) for window/layout/key-transition details.

## Unusual and hostile-looking banners

Configure a disposable pre-auth banner and MOTD containing password-, passphrase-, host-key-, and
sudo-looking lines. Confirm they remain remote output and cannot open a credential window. Repeat
inside completed and interactive terminal output. Only an actual OpenSSH Askpass event or the exact
fresh operation-bound sudo nonce may authorize a visible prompt.

## Sudo and root session

- Interactive acquire opens one labeled local sudo window.
- Status becomes active, a narrow command runs with expected effective UID, and server-side cache
  reuse does not open another prompt.
- Release invokes the documented invalidation and status becomes inactive.
- Non-interactive mode never opens a password window.
- A permitted root session is separate from the normal session and structured file tools remain
  unavailable inside it.
- Server sudoers/PAM denial stays a controlled failure; ServerOps never grants permission.

## Interrupt, timeout, and disconnect

- Interrupt a long command and verify the original shell is healthy before reuse.
- Run a short real timeout and verify recovery or controlled session loss without replay.
- Trigger a self-reverting network disconnect during an effectful command. Require
  `outcome_unknown`, invalidate the ambiguous connection, and verify remotely that no automatic
  retry occurred.
- Restart the MCP client with the managed broker task installed and rediscover the same live
  session with `command_retried = false`.
- Hard broker restart must end workers; do not claim adoption or reboot resume.

Use the guarded external scripts and [manual-spike-checklist.md](manual-spike-checklist.md). Never
introduce a persistent firewall rule or broad sudoers change.

## Structured files and key transition

- List/read/search/hash inside the exact disposable allowed root.
- Apply one approved UTF-8 edit with the observed SHA-256; reject a stale hash, symlink escape, and
  direct outside-root path.
- Install one selected public key, prove fresh key login, and repeat without duplication.
- Force the fresh login failure and record local rollback plus possible remote-key presence. Do not
  automatically remove or repeat an uncertain remote write.

## Evidence and cleanup

Record sanitized environment versions and every required scenario with
`scripts/manual_release_check.py`. All statuses must be automated or manually verified. Close every
session, remove only exact managed test tasks/keys/paths, and confirm no ServerOps or test process
remains. The evidence JSON must be bound to the candidate as defined by
[release-checklist.md](release-checklist.md).
