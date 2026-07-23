# Architecture decision records

ADRs record durable ServerOps architecture decisions. Existing decisions remain immutable except
for status or supersession notes; a changed decision receives a new numbered record.

Required sections are: title, status, context, decision, consequences, compatibility, verification,
and rollback or supersession path. Status values are Proposed, Accepted, Superseded, or Rejected.

- 001–015: Windows terminal, sessions, authentication, module boundaries, IPC, broker/worker,
  setup, files, elevation, audit, installer, scheduler, and askpass decisions.
- [016 — Idempotent local bootstrap](016-idempotent-local-bootstrap.md)
- [017 — Versioned Windows multiprocess package](017-windows-versioned-multiprocess-package.md)

This directory is the project's only ADR system; `docs/decisions/` is intentionally not duplicated.
