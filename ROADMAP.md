# ServerOps roadmap

## 0.1.1A — client and foundation integration

- Claude Code marketplace and plugin beside the compatible Codex distribution.
- Neutral ServerOps branding, client-neutral control and diagnosis skills, and product-oriented
  MCP instructions.
- Idempotent, current-user-only local bootstrap shared by runtime entry points.
- Project contracts, changelog, ADR index, and Windows packaging spike.

Done when a local candidate starts without manual setup, creates only protected ServerOps state,
preserves the eight-tool and protocol contracts, and passes all package gates.

## 0.1.1B — product presentation

- Rewrite the README around target users, outcomes, first use, trust boundaries, and client paths.
- Align screenshots, examples, metadata, support language, and documentation navigation with only
  claims demonstrated by current release evidence.

Done when the README separates published, candidate, and planned behavior; both client quickstarts
are reproducible; capability claims, links, commands, marketplace names, and version pins are
machine-checked; and the demo makes no production or fabricated-evidence claim.

## 0.1.1C — release hardening

- Synchronize version pins and changelog, validate clean-machine cold starts, complete visible
  credential checks, build hashed and attested Python artifacts, and require green CI plus
  commit-bound release evidence. Windows executable signing remains part of 0.1.2.

## 0.1.2A — Windows runtime and executable packaging

- Build the signed, versioned, self-contained per-user runtime selected by ADR 017.
- Provide separate MCP, broker, worker, setup, auth, and installer process roles with atomic
  upgrade, rollback, and uninstall.

## 0.1.2B — graphical onboarding and AI-client integration

- Add a non-technical Windows onboarding UI, client discovery, explicit integration previews, and
  controlled apply/remove flows for Codex, Claude Code, Claude Desktop, and selected MCP clients.

## 0.2 — operations runtime

- Durable jobs, append-only events and cursors, idempotency keys, receipts, artifacts, logs,
  resumable transfers, client identities, leases, and server tags.
- No specialist wrappers for operations that reliable prompting already covers.

## 0.3 — structured diagnosis

- Persisted investigations, structured findings, evidence links, checkpoints, and resumable
  diagnostic timelines built on the 0.2 operation store.

## 0.4 — transactional changes and fleet rollout

- Plans, preconditions, staged changes, verification, compensation, bounded concurrency, canaries,
  and resumable multi-server rollout state without exactly-once claims.

## 0.5 — backup assurance and native database adapters

- Backup-policy evidence, restore verification, retention checks, and narrowly scoped native
  adapters only where streaming, binary data, consistency, or verifiable transaction boundaries
  make shell prompting insufficient.
