# ADR 002: Session process ownership

Status: accepted

## Context

An MCP process may restart whenever Codex reconnects. If it owns OpenSSH directly, every held
working directory, virtual environment and interactive process disappears with it.

## Decision

Use one per-user broker and one worker process per SSH session. The worker owns exactly one
OpenSSH process and its PTY from creation to closure. The MCP is only a versioned client of the
broker.

The broker stores session metadata and worker connections, not passwords. A disconnected MCP
does not close workers. A new MCP performs a protocol handshake, lists existing sessions and
may address a session only by its unchanged session ID. Root shells are separate workers and
separate session IDs.

## Evidence

The spike started distinct broker and worker processes. Client A opened a key-authenticated
SSH session, changed to `/opt/app`, then disconnected. Client B connected to the same broker,
listed the existing session and observed `/opt/app` from the same held shell.

## Consequences

Broker shutdown policy must be explicit and must not kill a busy session merely because the
MCP disconnected. Worker loss becomes `LOST` or `FAILED`; it never triggers command replay.
The product broker needs single-instance enforcement, SID-only pipe ACLs and crash cleanup.

