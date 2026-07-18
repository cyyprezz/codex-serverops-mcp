# Local setup assistant

`server_profile_setup` starts `serverops-setup` as a separate visible process. The MCP command
line contains only a random request ID. Host and user suggestions are read from a status file
inside the current-user-only runtime directory; no password, passphrase or private-key content
is part of that file or an MCP result.

## Supported workflows

The assistant supports:

- adding direct targets and existing OpenSSH aliases;
- editing, removing and testing profiles;
- selecting an existing private key by path without reading its content;
- generating a new Ed25519 key below `%USERPROFILE%\.ssh\serverops` by default;
- optional local key passphrases through a directly owned `ssh-keygen` ConPTY;
- installing only the selected public key through an interactive password session;
- comparing the public-key algorithm and blob before appending, so a different comment does not
  duplicate the same key;
- testing a fresh key login before retaining the key-based local profile;
- configuring terminal/file permissions, allowed roots, elevation guidance, root-session
  guidance, environment label and output limits.

## Guided setup flow

Adding or editing a profile uses four focused pages instead of one long technical form:

1. **Connection** collects the profile label and either a direct server target or an existing
   OpenSSH alias.
2. **Authentication** shows only the fields required for the selected password, OpenSSH,
   existing-key or new-key workflow.
3. **Access** explains terminal, file and optional sudo capabilities in user-facing terms.
   Allowed roots appear only when file tools are enabled, root-session guidance appears only
   with elevation, and technical timeout/output limits stay collapsed by default.
4. **Review** summarizes the effective target and capabilities before the local save action.

The header and navigation remain visible while an individual page scrolls when required by
window height or display scaling. Going back retains the entered values. The final review and
security warning require local confirmation. The assistant states that terminal commands use
the SSH user's actual rights and that local roots or elevation settings are not a remote sandbox.

## Public-key transition

For a direct target, automatic installation temporarily stores the confirmed password profile,
opens an ordinary broker-owned session, creates `~/.ssh` with mode 700 and
`authorized_keys` with mode 600, and compares the key algorithm and Base64 blob while ignoring an
optional comment. A correlated remote result reports exactly one of `key_already_present` or
`key_added`. The successful setup result therefore contains
`public_key_installed = true` and `public_key_was_new = false` or `true`, respectively. The public
line is Base64-encoded only for safe shell transport; Base64 is not treated as confidentiality.

After the command succeeds, the local profile switches to the private-key path and a completely
new SSH session tests key login. A later failure restores the previous local configuration only if
its content hash still matches the setup transaction. The returned rollback status is
`rolled_back`, `skipped_concurrent_change` or `failed`; a concurrent local edit is never silently
overwritten.

The remote key is never removed automatically. A disconnect after the remote write but before its
result marker is `outcome_unknown`, so `public_key_installed` and `public_key_was_new` are both
unknown. A later local-switch or login-test failure may know whether the key was newly added, but
still does not prove that automatic removal is safe. The visible error states:

```text
The local profile switch was rolled back.

The public key may already be present in the remote authorized_keys file.
Review the remote account before retrying or removing the key.
```

When a concurrent local edit prevents rollback, or rollback itself fails, the first sentence is
replaced by the corresponding truthful rollback status; the remote-key warning remains.

## Profile and setup audit

Profile creation, update, removal and testing, key generation, and public-key installation emit
local redacted audit events. They contain the profile name and a narrow capability summary, never
the host/IP, full key path, public-key line, configuration content or any secret. Audit failure does
not turn a successful local mutation into a failure; the setup result reports
`audit.logged = false` instead.

## Secret handling

The new-key passphrase is never placed in `ssh-keygen` arguments or environment variables. The
setup window transfers a mutable buffer directly to the ConPTY, overwrites it best-effort and
does not persist it. Python, Tk, Windows and OpenSSH can create internal memory copies, so the
guarantee is limited to no persistence, logging, MCP routing or broker routing.

Login passwords, existing-key passphrases and host-key decisions continue through the separate
one-use `serverops-auth` path directly to the session worker.

## Verification boundary

Automated tests cover request expiry, bounded waits, forbidden secret result fields, command-line
isolation, profile validation, no-overwrite key generation, comment-insensitive public-key
identity, added/already-present results, unknown outcomes, fresh-login testing, conflict-aware
rollback, redacted profile audit and the current eight-tool surface. The real Windows
ConPTY smoke generates and removes an Ed25519 pair and confirms that no passphrase argument is used.

The actual setup window layout at supported display scales, focus, file picker, local
confirmation and the human-driven password/key-install flow remain a manual Windows release
gate. Rendered development previews do not replace that gate. The reproducible steps are in
the private release-validation procedure.
