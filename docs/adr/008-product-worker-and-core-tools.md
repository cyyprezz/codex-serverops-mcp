# ADR 008: Product worker composition and four core tools

Status: accepted

## Context

The stateful worker, broker and visible-auth components were independently proven, but the
public MCP still exposed no tools. Promoting them requires one real process path without moving
SSH ownership into FastMCP or duplicating OpenSSH configuration behavior.

## Decision

Compose the stored profile, OpenSSH target, visible-auth coordinator, ConPTY and stateful Bash
session inside the broker-created worker process. Direct profiles use validated arguments.
SSH-alias display context is resolved through `ssh -G`; ServerOps does not implement its own
SSH configuration parser.

Expose exactly four tools in this phase: `server_profiles`, `server_connection`, `server_exec`
and `server_terminal`. FastMCP handlers remain thin application adapters. Only profile reads are
annotated read-only; connection, arbitrary command and raw terminal operations use conservative
mutating/open-world annotations.

MCP reconnect queries the existing broker-owned worker. It never submits or retries a previous
command. A command connection loss before its end frame remains `outcome_unknown`.

## Evidence

Unit and process tests fix the target resolver, worker protocol, application mapping, exact
tool schema and broker auto-start behavior. A real Windows Docker smoke traverses application,
broker, worker, ConPTY and OpenSSH and verifies persistent cwd, persistent virtual environment,
exit code, raw terminal cursors and reconnect without retry.

## Consequences

The package now has a useful core surface but remains `0.0.0.dev1`. Setup, structured files,
elevation, installer and the complete eight-tool `0.1.0` contract remain later milestones.

## Current-product amendment

The historical four-tool milestone above has since grown into the complete eight-tool development
surface while remaining `0.0.0.dev1`. The public action formerly described here as an MCP
reconnect is now named `rediscover`. It only returns the existing broker-owned worker and never
repairs a lost SSH connection, creates a replacement session or retries a command.

The command-completion boundary has also been hardened beyond observing an end frame: the worker
requires the strict result/cwd/health sequence, control of the original Bash shell and terminal
liveness. Loss before that verification remains `outcome_unknown`.
