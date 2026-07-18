# ADR 001: Windows terminal backend

Status: accepted for the spike; compatibility gate required for version 0.1

## Context

Windows OpenSSH must behave as an interactive terminal so password, key-passphrase, host-key
and sudo prompts can be handled outside Codex while a remote Bash shell remains stateful.
A plain redirected subprocess is insufficient for those console interactions.

The spike evaluated direct Win32 `ctypes`, pywinpty with native ConPTY, and pywinpty with its
WinPTY backend. Direct `ctypes` did not reach a trustworthy child-attachment/lifecycle result.
WinPTY accepted a host-key response but rejected the valid fixture password. Native ConPTY
passed authentication, state, output and disconnect tests.

Native ConPTY did not reliably forward ETX/`sendintr()` as remote SIGINT through Windows
OpenSSH. The remote PTY therefore remaps `VINTR` to Ctrl+] and the worker sends `0x1d` for the
user-facing interrupt operation, followed by a non-retrying recovery frame.

## Decision

Use pywinpty 3.x with its backend explicitly set to ConPTY.

The worker will:

- continuously drain output on a background thread,
- answer required terminal device/cursor queries,
- keep output combined, because a PTY does not preserve stdout/stderr separation,
- use absolute-cursor bounded buffering,
- resize through the PTY backend,
- configure and verify the session-specific remote `VINTR` mapping,
- recover framing after a successful interrupt without replaying the command,
- treat programs that invalidate the required terminal mode as a compatibility error until a
  separate strategy is proven.

## Consequences

pywinpty becomes a Windows-native distribution dependency and its wheel availability must be
verified during offline distribution tests. The wrapper contains a targeted relay-socket
lifecycle workaround for pywinpty 3.0.5 and must retain a regression test.

This decision does not promise that every full-screen or raw-mode program can be interrupted.
The exact behavior must be tested and documented. A future direct Win32 implementation may
replace pywinpty only if it passes the same end-to-end suite.

