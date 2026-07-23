# Reproducible Windows test plan for ServerOps 0.1.1

## Test matrix

Use Windows 10 and Windows 11 where available, Python 3.12, the CI-pinned `uv`, Windows OpenSSH,
and current supported Codex and Claude Code versions. Use separate clean VM snapshots per client.
The Linux target must be disposable, non-root, and contain no customer data.

Before either cold start, record `python --version` and `uv python find 3.12`. The resolved path
must be a working CPython 3.12 executable, not the `Microsoft\WindowsApps\python.exe` app-execution
alias. A separate negative run should preserve and diagnose the Windows error-1312 failure before
ServerOps starts.

Record only version strings, the candidate commit, artifact SHA-256 values, neutral profile labels,
and pass/fail observations. Do not record hosts, accounts, credentials, key material, or remote
content.

## Prepare the immutable candidate

1. Build one wheel and one sdist from the clean candidate commit.
2. Generate and verify `SHA256SUMS.txt` with `scripts/artifact_checksums.py`.
3. Make the wheel available to the client-spawned `uvx` process through an isolated local
   wheelhouse/cache or a recorded test-only `uvx` shim under its exact `0.1.1` name. Do not edit
   either plugin manifest or replace its exact package argument. Record the provisioning method
   and shim hash, if used, as candidate-only evidence.
4. Snapshot LocalAppData, `.codex`, `.claude`, ServerOps task inventory, and related process list.

## Codex-only cold start

1. Restore a snapshot with no ServerOps AppData, plugin, MCP block, or broker task.
2. Install only the repository marketplace and `codex-serverops-mcp@serverops-codex` plugin.
3. Do not run `serverops-install setup` or `codex-config`.
4. Start a new Codex task and list ServerOps profiles without contacting a server.
5. Require the shared MCP core to list exactly eight tools and a valid empty schema-1
   configuration. Record the client presentation separately: Codex releases with dynamic MCP tool
   search may expose one `mcp__serverops` gateway to the model while the initialized ServerOps
   server still reports the eight underlying tools.
6. Inspect AppData allowlist, DACLs, task inventory, and client-config hashes.
7. Close and start another task. Config/state bytes and mtimes must be unchanged.

## Claude-Code-only cold start

Repeat the preceding procedure from a fresh snapshot using only the `serverops-claude` marketplace
and `serverops@serverops-claude` plugin. Do not infer this result from the Codex run. Verify `/mcp`
connection state and the same eight underlying server tools. Claude-owned configuration must
remain unchanged except for files the Claude plugin manager itself documents as its installation
state.

## Existing-state migration

1. Restore a state created by public `0.1.0` with one complete profile and a neutral audit fixture.
2. Capture config/audit bytes, hashes, and mtimes.
3. Start the unmodified `0.1.1` plugin pin; do not run setup first.
4. Require profile readability, identical config/audit bytes and mtimes, and new protected
   bootstrap state only.
5. Separately run a schema-0 fixture through setup, check the hash-named preimage and DACL, then
   inject verification failure and require byte-exact rollback.

## Installer and uninstall

1. Run explicit `setup` twice and compare config/state bytes and mtimes.
2. Run `setup --broker-task` without apply and compare Task Scheduler inventory.
3. Apply the task only after reviewing the exact `0.1.1` action; verify current-user/no-password/
   no-admin settings and remove it through the managed uninstall path.
4. Run plugin-only uninstall with no managed Codex block. It must succeed without creating
   `.codex/config.toml` and retain profiles/audit.
5. Preview `uninstall --remove-data`, cancel once, then explicitly apply. Verify only the literal
   ServerOps AppData directory is removed and foreign client/SSH files remain.

## Process and STDIO lifecycle

1. Close MCP stdin normally and require exit code 0 with no non-JSON stdout.
2. Initialize/list tools, then close the client abruptly. Every emitted stdout line must parse as
   JSON-RPC and no traceback may appear there.
3. Send SIGTERM/TerminateProcess and require no stdout banner or partial non-JSON frame.
4. Hard-terminate a broker holding a created worker. Require worker exit and status cleanup before
   starting a replacement broker with an empty registry.
5. Kill a worker during an effectful request and require controlled unknown outcome, invalidation,
   and no replay.

## Remote and visible authentication

Run [manual-release-gates.md](manual-release-gates.md). Include an unusual pre-auth banner and MOTD
containing password-, passphrase-, host-key-, and sudo-looking text. Only OpenSSH Askpass events and
operation-nonce-bound sudo prompts may open visible windows. Keep the MCP stream parseable while
the operator accepts, rejects, cancels, and times out each real prompt.

## Cleanup

Close all sessions, stop/remove only the managed test task, remove disposable profiles/keys/test
roots, and verify no ServerOps setup, auth, broker, worker, MCP, or test process remains. Restore
the VM snapshot and remove the disposable remote account or authorization.
