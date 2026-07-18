# ADR 013: Checkout-free uvx installer and explicit Doctor

## Status

Accepted for the 0.1 architecture.

## Decision

Codex starts the MCP with `uvx --from codex-serverops-mcp==<exact-version>` and no working
directory. The installer owns only a uniquely marked user-level `mcp_servers.serverops` block.
Preview is the default; apply/removal require local confirmation, current-content revalidation,
atomic backup and rollback.

Local setup prepares current-user state but never changes Codex configuration. Doctor reports
stable pass/warning/fail checks and accepts an explicit profile for live SSH/Bash, remote utility,
allowed-root, user and sudo preflight. Risk heuristics remain warnings.

## Consequences

- A repository checkout is not required after publishing.
- Foreign or ambiguous Codex entries fail closed.
- Update cannot silently repin Codex to a different distribution.
- Live Doctor may open the visible authentication path and creates a short-lived audited session.
- Manual Windows UI and real-network checks remain separate release evidence.
