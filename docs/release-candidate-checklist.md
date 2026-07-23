# ServerOps 0.1.1 release-candidate checklist

Mark an item complete only from evidence for the exact candidate commit and artifacts. A local
green unit test does not substitute for a named real-client or real-server gate.

## Source and compatibility

- [ ] Worktree is clean and exact commit is recorded.
- [ ] `python scripts/verify_release.py` proves all `0.1.1` versions and pins are synchronized.
- [ ] Package name, import package, six entry points, LocalAppData path, MCP ID, tool names,
  config schema 1, and broker/worker protocol 3 remain unchanged.
- [ ] Codex and Claude Code skills remain byte-identical and client-neutral.
- [ ] README, capabilities, release notes, and metadata describe only final behavior.

## Local state and lifecycle

- [ ] First MCP start on empty LocalAppData creates only allowlisted ServerOps state.
- [ ] Second start and explicit `setup` do not rewrite current config or bootstrap state.
- [ ] Existing `0.1.0` profiles and audit bytes survive unchanged.
- [ ] Schema-0 migration backup, DACL, verification, and injected rollback pass.
- [ ] Client config sentinels and Scheduled Task inventory remain unchanged by bootstrap.
- [ ] Broker-task preview makes no change; apply requires explicit confirmation.
- [ ] Default uninstall preserves profile and audit data.
- [ ] Plugin-only/Claude-only uninstall is idempotent and does not create a Codex config file.
- [ ] `--remove-data` is separately previewed, confirmed, and refuses unexpected/reparse targets.

## Process and protocol

- [ ] MCP EOF exits cleanly; SIGTERM and abrupt client close emit no banner or traceback on stdout.
- [ ] Every MCP stdout line is valid JSON-RPC.
- [ ] Hard broker termination ends its authenticated workers and removes worker status.
- [ ] Replacement broker starts with an empty registry; no worker adoption or automatic replay.
- [ ] Worker death becomes controlled lost state and never causes command replay.
- [ ] Timeout `3600` reaches application, broker, worker, and client budgets unchanged.
- [ ] Short real timeout recovers the original healthy shell or reports controlled loss.
- [ ] Unusual banners and fake auth/sudo prompts cannot open an unauthorized credential window.

## Distribution and clients

- [ ] Wheel and sdist build from the candidate and pass distribution inspection.
- [ ] Wheel rebuilt from sdist has the same Python payload.
- [ ] Each clean client resolves a real Python 3.12 executable; the WindowsApps-alias negative
  case fails before ServerOps and is diagnosed.
- [ ] Codex marketplace/plugin install on a clean Windows snapshot without setup.
- [ ] Claude marketplace/plugin install on a separate clean snapshot without setup.
- [ ] The unchanged manifests start the exact candidate through a recorded isolated
  wheelhouse/cache or test-only `uvx` shim; no unpublished-pin success is presented as a public
  package-index result.
- [ ] Both clients initialize the same eight-tool core and create the same allowlisted local state;
  any client-side dynamic gateway presentation is recorded separately.
- [ ] Official pinned plugin validators pass.
- [ ] `SHA256SUMS.txt` verifies exactly one wheel and one sdist.

## Manual external gates

- [ ] Real direct target and SSH alias.
- [ ] Password, key passphrase, new host key, cancellation, and timeout in visible local windows.
- [ ] Interactive sudo acquire/cache/exec/release and separate root session.
- [ ] Ctrl+C, network disconnect, `outcome_unknown`, and no automatic retry.
- [ ] Structured text read/write/hash conflict/root escape checks in a disposable root.
- [ ] New-key transition, fresh login, failure reporting, rollback, and cleanup.
- [ ] Sanitized `docs/release-evidence.json` is bound to the exact candidate.

Only after every box is supported by evidence may the candidate be reported as
`0.1.1 release candidate ready`.
