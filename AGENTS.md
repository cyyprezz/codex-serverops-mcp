# ServerOps project contract

ServerOps is a client-neutral operations product for people who need to operate explicitly
configured Linux servers from ordinary AI applications. First-class clients are Codex/ChatGPT and
Claude Code. IDE-specific integrations are thin compatibility wrappers, not a product direction.

Primary users include freelancers and agencies with customer servers, small and medium Linux
operators, support and project owners, and technically interested users without a daily SSH
workflow. ServerOps must be easier to start than a traditional SSH workflow, retain useful state
outside disposable AI clients, return understandable evidence instead of raw-output floods, and
require no ServerOps software on the Linux host.

## Architecture boundaries

- Keep one MCP core and thin client distributions.
- Preserve package names, entry points, configuration paths, protocol versions, credentials,
  audit, sessions, structured files, and all unknown-outcome contracts unless a versioned
  migration explicitly changes them.
- Credentials and host-key decisions stay in visible local windows and never enter MCP arguments,
  logs, manifests, or prompts.
- Never automatically retry a mutation after `outcome_unknown`, `file_outcome_unknown`,
  `elevation_outcome_unknown`, a lost connection, or an effectful timeout.
- Add a core function only when durable state, large or binary data, resume, atomicity,
  idempotency, event delivery, verification, or multi-client coordination justifies it.
- Do not add promptable pseudo-tools for ordinary `df`, `free`, `ps`, `top`, `systemctl`, Docker,
  journal, process-kill, generic database, dump, or cron commands.
- Do not claim exactly-once effects. Use receipts, idempotency, verification, and explicit unknown
  outcomes where later phases introduce durable operations.
- Bootstrap may prepare only ServerOps-owned local state. Client configuration, Scheduled Tasks,
  SSH files, profiles, server contact, administrator rights, and unmanaged files require separate
  explicit authority.

Run the full unit suite, Ruff, package build, distribution inspection, and `git diff --check`
before release work. Never publish or release from an implementation task without explicit
authorization.
