# ServerOps 0.1.1 release notes

ServerOps 0.1.1 adds Claude Code as a first-class client, gives Codex and Claude Code the same
client-neutral operating workflows, and removes the manual setup prerequisite from plugin first
start. The public product name is now ServerOps; existing package names, commands, paths, profiles,
sessions, audit data, and protocol contracts remain compatible.

## Highlights

- Codex and Claude Code marketplaces with exact synchronized `0.1.1` runtime pins.
- Automatic, idempotent, current-user-only local bootstrap from MCP first start.
- Guided `serverops-control` and evidence-led `serverops-diagnose` skills.
- Product-oriented MCP instructions and client-selectable Doctor checks.
- Clearer operator-focused README, safe first prompts, reproducible demo, and machine-checked
  Available-versus-Planned claims.
- Hardened plugin-only uninstall, explicit data removal, hard broker/worker lifecycle, MCP EOF and
  SIGTERM handling, maximum timeout propagation, artifact checksums, and commit-bound release
  evidence.

## Upgrade from 0.1.0

No profile migration command is required. Starting the `0.1.1` MCP, broker, setup, check, Doctor,
or update entry point prepares additive bootstrap state and leaves valid schema-1 config and audit
files unchanged. The explicit setup command remains idempotent. Review
[migration-rollback-evidence.md](migration-rollback-evidence.md) before production rollout.

Package and both plugin pins must move together. Do not combine the Codex plugin with the optional
installer-managed user-wide MCP block. The installer can preview removal of that marked block
without removing profiles, audit, or an independently managed broker task.

## Important boundaries

- Windows 10/11, Python 3.12, `uvx`, and Windows OpenSSH remain required.
- No ServerOps agent is installed on Linux.
- Session state is process-held, not durable across Windows reboot or broker crash.
- Reliable MCP-restart rediscovery requires the explicitly installed current-user broker task.
- Structured files are bounded UTF-8 text operations, not binary/resumable transfer.
- An uncertain remote mutation is never retried automatically and has no exactly-once guarantee.
- Claude Desktop, `ServerOpsSetup.exe`, persistent jobs, incident timelines, fleet rollout, backup
  assurance, and native database adapters remain planned rather than shipped.

## Release verification

The release is blocked until the exact candidate passes [release-checklist.md](release-checklist.md),
including clean Codex and Claude Code plugin starts and the real SSH/visible-authentication gates.
No publication is implied by these notes.
