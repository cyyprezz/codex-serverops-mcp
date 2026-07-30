# Changelog

All notable changes are documented here. The project follows Keep a Changelog and uses semantic
versions for published releases.

## 0.1.1 — 2026-07-30

### 0.1.1C release hardening

- Synchronized package, registry, Codex, Claude Code, capability, and documentation versions.
- Added clean-state plugin launch, MCP EOF/SIGTERM, hard broker restart, worker-orphan, maximum
  timeout, uninstall, migration, artifact checksum, and release-contract gates.
- Made plugin-only uninstall idempotent, kept update checks client-neutral, and hardened explicit
  data removal against reparse targets.
- Required commit-bound manual evidence before the tag workflow can publish.

### 0.1.1B product presentation

- Reframed the public README around operator outcomes, safe first use, Codex and Claude Code
  quickstarts, architecture, honest limits, and Available-versus-Planned capability status.
- Added a reproducible non-production demo, a machine-readable capability contract, automated
  claim checks, and a contributing guide.
- Aligned public metadata and corrected stale or over-broad product, bootstrap, client, and
  session-lifetime claims.

### 0.1.1A foundation

### Added

- Claude Code marketplace and plugin with an exact published runtime pin.
- Client-neutral `serverops-control` and `serverops-diagnose` skills.
- Shared idempotent local bootstrap with locked configuration initialization, migration backups,
  rollback verification, protected runtime/audit state, and entry-point integration.
- Client-selectable local Doctor checks and product-oriented MCP instructions.
- Project contracts, roadmap, ADR index, and a non-shipping Windows packaging spike.

### Changed

- Public display branding is now ServerOps while technical identifiers remain compatible.
- Plugin startup now prepares local state without a manual setup prerequisite.

### Security

- Configuration and audit lockfiles are restricted to the current user immediately after creation.
- Automatic bootstrap is limited to an allowlist of ServerOps-owned paths and fails closed on
  invalid schemas, wrong file types, and reparse targets.

## 0.1.0 — 2026-07-18

- Initial public Windows release with stateful broker-owned SSH sessions, visible local
  authentication, structured remote files, guided elevation, redacted local audit, installer and
  Doctor flows, and explicit unknown-outcome handling.
