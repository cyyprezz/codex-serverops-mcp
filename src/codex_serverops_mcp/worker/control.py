from __future__ import annotations

# ConPTY consumes local ETX before Windows OpenSSH forwards it. Session startup
# remaps the remote PTY's VINTR to Ctrl+], which ConPTY forwards reliably.
REMOTE_VINTR_BYTE = b"\x1d"
