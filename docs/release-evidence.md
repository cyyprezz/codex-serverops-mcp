# External Ubuntu release evidence

ServerOps uses a disposable external Ubuntu account for the network, OpenSSH, sudo and Bash
checks that public CI cannot reproduce. Reports must omit addresses, domains, account names,
credentials, key material, customer identifiers and real production paths.

The table below records the historical development run from 2026-07-18. It is useful regression
context, but it is **not** final `0.1.0` evidence: the tested source history predates the public
repository and is not an ancestor of the current release candidate. Every `not tested` row and
every missing version must be resolved on the final candidate.

## Historical environment

| Field | Recorded value |
| --- | --- |
| Windows version | not recorded |
| Python version | 3.12.13 |
| uv version | not recorded |
| Windows OpenSSH version | not recorded |
| Ubuntu version | 24.04.4 LTS |
| Remote OpenSSH version | 9.6p1 |
| sudo version | not recorded |
| Bash version | not recorded |
| Test date | 2026-07-18 |
| Source revision | historical development revision; not a public-main ancestor |
| Package version | 0.0.0.dev1 |

## Historical scenario matrix

`automated` means a guarded script asserted the result after a connection existed. `manually
verified` means an operator completed or directly observed the scenario. A visible credential
interaction is never classified as automated merely because a script continued afterward.

| Scenario | Status | Evidence boundary |
| --- | --- | --- |
| Direct connection | manually verified | Setup assistant and real server |
| SSH alias | manually verified | Transactional alias setup and fresh login |
| Password login | manually verified | Visible local password window |
| Existing key | manually verified | Explicit existing encrypted key profile |
| Passphrase-protected key | manually verified | Visible local passphrase window |
| New Ed25519 key | manually verified | Setup-generated dedicated key |
| Public-key installation | manually verified | Disposable account only |
| Fresh login with new key | manually verified | Fresh worker after profile switch |
| Host-key confirmation | not tested | Must be repeated on final candidate |
| Authentication cancellation | manually verified | Controlled cancellation result |
| Authentication timeout | manually verified | Controlled five-second timeout |
| Persistent working directory | automated | External acceptance assertion |
| Persistent virtual environment | not tested | Must be repeated on final candidate |
| Persistent shell variables | not tested | Must be repeated on final candidate |
| Completed command and exit code | automated | External acceptance assertion |
| Large output and truncation | not tested | Must be repeated on final candidate |
| Raw terminal start | automated | External acceptance assertion |
| Raw terminal read | automated | External acceptance assertion |
| Raw terminal write | automated | External acceptance assertion |
| Ctrl+C | automated | Guarded real-network interruption check |
| Timeout and recovery | not tested | Must be repeated on final candidate |
| SSH connection loss | automated | Connection-specific self-reverting firewall rule |
| `outcome_unknown` | automated | Disconnect before command completion |
| No automatic retry | automated | Lost worker and no replay assertion |
| MCP restart | manually verified | Two checkout-free MCP processes; first auth was manual |
| Broker session rediscovery | automated | Same session ID and preserved cwd asserted |
| Structured file list | manually verified | Live installed MCP run |
| Structured text read | automated | External acceptance assertion |
| Structured search | automated | External acceptance assertion |
| Structured hash | automated | External acceptance assertion |
| Structured `write_text` | automated | Disposable child path only |
| Structured `apply_patch` | automated | Observed-hash update |
| Hash conflict | automated | Stale hash rejected |
| Symlink escape | automated | Outside target rejected |
| Direct path outside `allowed_roots` | not tested | Must be repeated on final candidate |
| sudo status | automated | Inactive/active state asserted |
| sudo acquire | manually verified | Visible local sudo window |
| Server-side sudo cache | manually verified | Reuse observed without another prompt |
| sudo exec | manually verified | Effective UID and result checked |
| sudo release | automated | Inactive state asserted after release |
| Root session | automated | Effective UID 0 and file-tool rejection asserted |
| Separate normal and root sessions | automated | Distinct session metadata asserted |
| Doctor against real profile | automated | Remote preflight succeeded |

## Final-candidate procedure

Capture neutral environment values on the machine that performs the final run:

```powershell
python --version
uv --version
ssh -V
git rev-parse HEAD
```

Capture only version strings on the disposable Ubuntu account:

```bash
. /etc/os-release; printf '%s\n' "$PRETTY_NAME"
sshd -V 2>&1 | head -n 1
sudo --version | head -n 1
bash --version | head -n 1
```

Run the automated, visible-window and external-server gates documented by the release process.
The evidence JSON must record all fourteen manual gates below as explicitly passed; none is
inferred from a unit test or from another gate:

```text
password_window
key_passphrase_window
host_key_window
sudo_window_and_cache
auth_cancel_and_timeout
setup_direct_and_alias_profiles
setup_existing_and_generated_keys
public_key_install_and_fresh_login
mcp_restart_and_session_rediscovery
interrupt_disconnect_and_no_retry
spoofed_remote_prompt_rejected
shell_state_corruption_detected
failed_key_transition_reports_remote_key_state
profile_mutations_audited
```

Then record the result on the exact stable-version candidate:

```powershell
$env:PYTHONPATH = "src"
python scripts/manual_release_check.py --output docs/release-evidence.json
python scripts/verify_release.py --tag v0.1.0 --evidence docs/release-evidence.json
```

The evidence recorder uses exactly four scenario states: `automated`, `manually_verified`,
`not_tested` and `not_applicable`. The stable release gate rejects every scenario that was not
actually automated or manually verified. The evidence revision must be the release commit itself
or its direct parent when the only following commit adds `docs/release-evidence.json`.
