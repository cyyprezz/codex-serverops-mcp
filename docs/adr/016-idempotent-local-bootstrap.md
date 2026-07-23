# ADR 016: Idempotent local bootstrap

Status: Accepted for 0.1.1A

## Context

The installer prepared complete local state, while MCP, broker, setup, audit, and runtime paths
created different subsets lazily. Plugin startup therefore depended on a manual setup instruction,
and the installer checked for a missing config outside the repository lock, allowing a concurrent
profile write to be replaced by an empty config.

## Decision

Use a client-neutral `LocalStateBootstrapper` at MCP, broker, setup, installer setup/update/check,
and Doctor entry points. It creates and secures only the ServerOps AppData allowlist, maintains a
small bootstrap-schema state file, and initializes or migrates config under the existing config
lock. Lock order is bootstrap then config.

Schema migration first stores a hash-named byte-for-byte preimage in the protected migrations
directory. The migrated document is atomically replaced, decoded again, and rolled back under the
same lock if verification fails. Current schema documents are never rewritten merely by startup.

Bootstrap is not placed in injectable server constructors. Worker and auth remain broker-owned,
narrow processes and do not bootstrap global state.

## Consequences

Plugins can start the candidate without a manual setup command. Corrupt, future, non-regular, or
reparse paths stop startup before any server contact. Client configuration, Scheduled Tasks, SSH
files, profiles, network access, and elevation remain outside bootstrap authority.

## Compatibility and verification

AppData and config paths, schema 1, entry points, and all protocol identifiers remain unchanged.
Tests cover first and repeated start, concurrency, lost-update prevention, migration backup,
rollback, ACLs, invalid paths, forbidden side effects, and entry-point ordering.

## Rollback

Code rollback leaves valid schema-1 state readable by 0.1.0. Migration preimages remain local
ServerOps files and can be restored manually only after stopping ServerOps processes. Uninstall
never runs bootstrap and removes local state only after explicit `--remove-data` confirmation.
