# ADR 007: Reconnectable per-user broker

Status: accepted

## Context

Codex may restart or reconnect the STDIO MCP process while an operator expects SSH working
directory, environment and interactive state to remain alive. The MCP process therefore cannot
own session workers. A stale status file must also never allow a second broker to claim an
already-owned worker or pipe.

## Decision

Run exactly one broker per Windows user, enforced by the first instance of a deterministic,
SID-derived named-pipe path. The broker starts and owns one worker subprocess per session and
keeps the authenticated worker connection. MCP clients are disposable: they authenticate to
the broker, list broker-owned sessions and address them by unchanged random session IDs.

Persist only bounded discovery metadata in a current-user-only runtime directory. Validate the
status identity again through the authenticated pipe before registering a worker. Keep worker
tokens out of command lines and broker protocol payloads. Explicit broker shutdown wakes its
blocking accept loop through a local connection and then closes owned workers deterministically.

## Current-product amendment

"Reconnectable" in this ADR describes a new disposable MCP client connecting to the persistent
broker. The public `server_connection` action is named `rediscover`: it returns the existing
broker-owned session ID and worker without repairing SSH, adopting an unowned process, creating a
replacement session or retrying a command. A lost worker remains lost. The original phase's
requirement to connect real SSH creation to this lifecycle was subsequently completed by the
public session tools.

## Consequences

An MCP restart no longer terminates broker-owned workers. A broker crash still ends ownership;
this version does not adopt orphaned processes from status files. The product must connect real
SSH creation to the existing worker lifecycle before the public session tools are released.
Broker and worker process tests are Windows-specific, while registry and protocol behavior stay
independently testable.
