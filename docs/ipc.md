# Local IPC foundation

Product IPC uses native Windows named pipes through the pinned `pywin32` dependency. The
development spike's `multiprocessing.connection` transport is not imported by product code.

## Pipe security

Every product pipe is created with an explicit security descriptor:

- owner: current Windows user SID;
- DACL: one allow ACE for that same SID and no other allow ACE;
- remote clients rejected by `PIPE_REJECT_REMOTE_CLIENTS`;
- first listener instance created with `FILE_FLAG_FIRST_PIPE_INSTANCE`;
- DACL read back from the kernel object and verified before accepting traffic; and
- every client verifies the connected pipe owner and DACL before beginning a handshake.

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
protocol mismatches fail closed. A receive timeout, partial frame, invalid frame or correlation
failure permanently closes that connection; a later request never reuses an ambiguous stream.
Unknown message types produce a correlated controlled error.

## Handshake

The client first sends a fresh nonce and role without the broker-instance token. The server returns
a fresh nonce plus an HMAC proof over both nonces, role and protocol version. Only after verifying
that proof does the client return its own HMAC proof. The token itself never crosses the pipe.
Both proofs use constant-time comparison, and the final acknowledgement is correlated to the
client proof.

The verified SID owner/DACL is the local authorization boundary. The instance token additionally
rejects stale or misdirected peers and binds a connection to one broker lifetime; it is not a
substitute for Windows object security.

## Shutdown

Server-side connections flush queued response bytes before disconnecting so the peer cannot
observe a valid length prefix followed by discarded payload bytes. Broken-pipe errors are
converted to controlled IPC closure errors.
