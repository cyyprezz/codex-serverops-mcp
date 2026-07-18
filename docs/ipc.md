# Local IPC foundation

Product IPC uses native Windows named pipes through the pinned `pywin32` dependency. The
development spike's `multiprocessing.connection` transport is not imported by product code.

## Pipe security

Every product pipe is created with an explicit security descriptor:

- owner: current Windows user SID;
- DACL: one allow ACE for that same SID and no other allow ACE;
- remote clients rejected by `PIPE_REJECT_REMOTE_CLIENTS`;
- first listener instance created with `FILE_FLAG_FIRST_PIPE_INSTANCE`;
- DACL read back from the kernel object and verified before accepting traffic.

Failure to inspect or match the current-user-only policy closes the operation. The current SID
is also hashed into stable broker pipe names so different Windows users do not share a name.

## Message framing

Messages use a four-byte network-order length followed by UTF-8 JSON. Normal IPC messages are
limited to 262,144 bytes; authentication channels use the smaller limit defined by their
dedicated protocol.

Every envelope contains exactly:

```text
protocol_version
message_id
message_type
payload
```

Unknown or duplicate JSON fields, invalid identifiers, non-JSON payloads, oversized frames and
protocol mismatches fail closed. Unknown message types produce a correlated controlled error.

## Handshake

The MCP client sends a `hello` envelope containing its role and the random broker-instance
token read from the broker's protected runtime status. The broker compares the token using a
constant-time comparison and returns `hello.ack` with the exact broker protocol version.

The SID DACL is the authorization boundary. The instance token additionally rejects stale or
misdirected clients and binds a connection to one broker lifetime; it is not a substitute for
the DACL.

## Shutdown

Server-side connections flush queued response bytes before disconnecting so the peer cannot
observe a valid length prefix followed by discarded payload bytes. Broken-pipe errors are
converted to controlled IPC closure errors.
