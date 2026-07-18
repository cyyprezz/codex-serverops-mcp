from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import uuid
from multiprocessing.connection import Client, Listener

from codex_serverops_mcp import WORKER_PROTOCOL_VERSION

MAX_AUTH_MESSAGE_BYTES = 16_384


def request_visible_auth(kind: str, prompt: str, context: dict[str, object]) -> str:
    """Open a one-use visible UI whose secret response returns directly to this worker."""
    pipe = rf"\\.\pipe\codex-serverops-auth-{uuid.uuid4().hex}"
    authkey = os.urandom(32)
    environment = dict(os.environ)
    environment["SERVEROPS_SPIKE_AUTHKEY"] = base64.urlsafe_b64encode(authkey).decode("ascii")
    listener = Listener(pipe, family="AF_PIPE", authkey=authkey)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 1  # SW_SHOWNORMAL
    process = subprocess.Popen(
        [sys.executable, "-m", "codex_serverops_mcp.spike.auth_ui", "--client", pipe],
        env=environment,
        close_fds=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        startupinfo=startup,
    )
    try:
        connection = listener.accept()
        try:
            request = json.dumps(
                {
                    "protocol_version": WORKER_PROTOCOL_VERSION,
                    "request_id": f"auth_{uuid.uuid4().hex}",
                    "kind": kind,
                    "prompt": prompt[-500:],
                    "context": context,
                }
            ).encode("utf-8")
            connection.send_bytes(request)
            response = json.loads(connection.recv_bytes(MAX_AUTH_MESSAGE_BYTES).decode("utf-8"))
        finally:
            connection.close()
    finally:
        listener.close()
        process.wait(timeout=5)
    if response.get("protocol_version") != WORKER_PROTOCOL_VERSION:
        raise RuntimeError("authentication UI protocol mismatch")
    if response.get("status") != "submitted":
        raise RuntimeError(f"authentication UI returned {response.get('status', 'invalid')}")
    value = response.get("value")
    if not isinstance(value, str):
        raise RuntimeError("authentication UI returned an invalid value")
    return value


def _show_dialog(request: dict[str, object]) -> dict[str, object]:
    import tkinter as tk

    protocol = request.get("protocol_version")
    if protocol != WORKER_PROTOCOL_VERSION:
        return {"protocol_version": WORKER_PROTOCOL_VERSION, "status": "protocol_mismatch"}
    kind = str(request.get("kind", ""))
    prompt = str(request.get("prompt", ""))
    raw_context = request.get("context", {})
    context = dict(raw_context) if isinstance(raw_context, dict) else {}
    fixture_value = context.pop("local_fixture_value_to_enter", "")
    root = tk.Tk()
    root.title("Codex ServerOps authentication")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    result: dict[str, object] = {"protocol_version": protocol, "status": "cancelled"}

    context_text = "\n".join(f"{key}: {value}" for key, value in context.items())
    heading = "Verify the SSH host key" if kind == "host_key" else "Authentication required"
    tk.Label(root, text=heading, font=("Segoe UI", 12, "bold"), anchor="w").pack(
        padx=18, pady=(16, 8), fill="x"
    )
    tk.Label(root, text=context_text, justify="left", anchor="w").pack(
        padx=18, pady=(0, 8), fill="x"
    )
    tk.Label(
        root,
        text=prompt,
        justify="left",
        anchor="w",
        wraplength=560,
        bg="#f2f2f2",
    ).pack(padx=18, pady=(0, 12), fill="x")

    entry: tk.Entry | None = None
    if kind != "host_key":
        entry = tk.Entry(root, show="*", width=64)
        entry.pack(padx=18, pady=(0, 12), fill="x")
        if isinstance(fixture_value, str):
            entry.insert(0, fixture_value)

    buttons = tk.Frame(root)
    buttons.pack(padx=18, pady=(0, 16), fill="x")

    def cancel() -> None:
        root.destroy()

    def submit() -> None:
        value = "yes" if entry is None else entry.get()
        result.update({"status": "submitted", "value": value})
        root.destroy()

    tk.Button(buttons, text="Cancel", command=cancel, width=12).pack(side="right")
    tk.Button(
        buttons,
        text="Accept" if kind == "host_key" else "Submit",
        command=submit,
        width=12,
        default="active",
    ).pack(side="right", padx=(0, 8))
    root.protocol("WM_DELETE_WINDOW", cancel)
    root.bind("<Return>", lambda _event: submit())
    root.bind("<Escape>", lambda _event: cancel())
    if entry is not None:
        entry.focus_set()
    root.update_idletasks()
    root.geometry(f"600x{root.winfo_reqheight()}")
    root.mainloop()
    return result


def _client(pipe: str) -> int:
    encoded_key = os.environ.pop("SERVEROPS_SPIKE_AUTHKEY", "")
    if not encoded_key:
        return 2
    authkey = base64.urlsafe_b64decode(encoded_key.encode("ascii"))
    connection = Client(pipe, family="AF_PIPE", authkey=authkey)
    try:
        request = json.loads(connection.recv_bytes(MAX_AUTH_MESSAGE_BYTES).decode("utf-8"))
        response = _show_dialog(request)
        connection.send_bytes(json.dumps(response).encode("utf-8"))
    finally:
        connection.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", required=True)
    args = parser.parse_args()
    raise SystemExit(_client(args.client))


if __name__ == "__main__":
    main()
