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
- checking for the exact public key before appending to `authorized_keys`;
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
`authorized_keys` with mode 600, and appends only when `grep -qxF` does not find the exact key.
The public line is base64-encoded only for safe shell transport; base64 is not treated as
confidentiality.

After the command succeeds, the local profile switches to the private-key path and a completely
new SSH session tests key login. A failed installation or key-login test restores the previous
local configuration only if its content hash still matches the setup transaction. It does not
silently overwrite a concurrent profile change. An already appended remote public key is not
removed automatically after a later test failure because doing so could remove a key another
administrator began using.

## Secret handling

The new-key passphrase is never placed in `ssh-keygen` arguments or environment variables. The
setup window transfers a mutable buffer directly to the ConPTY, overwrites it best-effort and
does not persist it. Python, Tk, Windows and OpenSSH can create internal memory copies, so the
guarantee is limited to no persistence, logging, MCP routing or broker routing.

Login passwords, existing-key passphrases and host-key decisions continue through the separate
one-use `serverops-auth` path directly to the session worker.

## Verification boundary

Automated tests cover request expiry, bounded waits, forbidden secret result fields, command-line
isolation, profile validation, no-overwrite key generation, exact public-key installation,
fresh-login testing, conflict-aware rollback and the current eight-tool surface. The real Windows
ConPTY smoke generates and removes an Ed25519 pair and confirms that no passphrase argument is used.

The actual setup window layout at supported display scales, focus, file picker, local
confirmation and the human-driven password/key-install flow remain a manual Windows release
gate. Rendered development previews do not replace that gate. The reproducible steps are in
the private release-validation procedure.
