# ServerOps 0.1.0 to 0.1.1 migration and rollback evidence

ServerOps `0.1.1` keeps config schema 1, broker protocol 3, worker protocol 3, technical names, and
the existing LocalAppData root. The new bootstrap state is additive. No profile or audit rewrite is
required for a normal public `0.1.0` installation.

## Automated evidence contracts

| Contract | Evidence |
|---|---|
| Existing schema-1 profile and audit retained byte- and mtime-exact | `BootstrapTests.test_public_010_state_is_adopted_without_rewriting_profiles_or_audit` |
| First start creates allowlisted empty state; second run is unchanged | `test_first_run_creates_only_managed_empty_state_and_second_is_idempotent` |
| Concurrent first starts serialize safely | `test_parallel_first_run_is_safe` |
| Schema-0 preimage is hash-named and migrated once | `test_legacy_config_is_backed_up_once_and_migrated` |
| Failed post-write verification restores original bytes | `test_failed_post_write_verification_restores_migration_preimage` |
| Managed paths, locks, state, and migration backup use current-user DACLs | `test_every_managed_path_is_current_user_only` |
| Future, malformed, wrong-type, foreign, and reparse state fails closed | Bootstrap and installer setup regression suites |
| Explicit setup twice preserves config/state and both client sentinels | `InstallerCliTests.test_setup_twice_is_idempotent_and_preserves_both_client_configs` |
| Default uninstall retains profiles/audit; remove-data is separate | `test_uninstall_preserves_data_until_remove_data_is_explicitly_applied` |

These tests use neutral fixtures and do not prove a user's specific AppData. The clean Windows plan
must repeat the schema-1 adoption with a copy produced by the public `0.1.0` package.

## Migration sequence

1. Acquire `.bootstrap.lock`, then the config lock.
2. Validate every managed path without following a reparse target.
3. If config is missing, atomically create empty schema 1.
4. If config is schema 1, decode it and leave its bytes and mtime unchanged.
5. If config is schema 0, secure a SHA-256-named preimage in `migrations`, migrate atomically,
   decode the target again, and retain the backup.
6. On verification failure, restore the preimage under the same config lock and fail startup before
   MCP/broker composition or server contact.
7. Atomically create bootstrap `state.json`; subsequent starts validate and do not rewrite it.

## Rollback plan

- Before publication: remove the candidate plugin and restore its clean VM snapshot. No user state
  needs downgrading because schema 1 remains readable by `0.1.0`.
- After a failed local migration: stop ServerOps processes, preserve the failing files for support,
  verify the migration-backup hash, and restore only the matching preimage if automatic rollback
  did not already succeed. Do not guess or merge TOML manually.
- Package rollback: point the client back to exact `0.1.0` only after verifying the config remains
  schema 1. The additive `state.json`, bootstrap lock, and migration directory can remain; `0.1.0`
  ignores them.
- Broker task rollback: preview and install the exact prior package action explicitly. Never replace
  an unmarked or action-mismatched task.
- Client rollback does not delete profiles or audit. Data removal remains a distinct confirmed
  action and is not part of version rollback.

## Candidate evidence record

For the final run, attach the candidate commit, Windows/Python/uv/OpenSSH versions, before/after
config and audit hashes/mtimes, migration-backup hash and DACL result, test names, and sanitized
pass/fail status. Do not attach profile contents, audit lines, hosts, users, or credentials.
