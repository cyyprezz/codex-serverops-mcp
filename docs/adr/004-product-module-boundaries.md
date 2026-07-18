# ADR 004: Product module boundaries

Status: accepted

## Context

The spike intentionally optimized for fast feasibility evidence. Promoting its orchestration
files directly would combine process lifecycle, prompt handling, state transitions and test
fixture behavior. That would create large files and make later security work risky.

## Decision

Production code uses explicit composition and the package boundaries in `docs/architecture.md`.
No production module imports from the `spike` package. State, protocol, transport, prompt,
configuration and UI responsibilities have separate modules.

An architecture contract test rejects production Python files above 450 physical lines,
imports from the spike package and classes whose names end in `Mixin`.

## Consequences

Some proven spike behavior is re-expressed behind product contracts instead of imported as a
shortcut. This costs a small amount of duplication during promotion but keeps experimental
fixture code out of the release runtime and gives security-sensitive boundaries focused tests.
