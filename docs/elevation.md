# Guided sudo and root sessions

The public `server_elevation` tool keeps passwords outside MCP and broker messages. It supports a
bounded elevated command in the existing session and, when explicitly allowed, a separately owned
root session.

## Security boundary

`elevation_mode` controls only the guided product workflow. It cannot prevent a user from typing
`sudo` through `server_exec` or `server_terminal`, but normal command and terminal output is never
allowed to open the local sudo-password window. An unmanaged interactive `sudo` may therefore wait
until it is interrupted or times out. Elevation cannot grant a permission denied by the remote
sudoers policy. Operators should use a restricted SSH account and narrow sudoers rules.

Interactive sudo is not routed through OpenSSH Askpass because it occurs inside the established
remote PTY. It is authorized only while an explicit `acquire` or elevation `exec` action is active.
A password is entered only in the separate visible local authentication process and travels over
a one-use current-user DirectAuth pipe directly to the worker that owns OpenSSH. It is absent from
the MCP schema, broker protocol, profile config, environment, process arguments, normal results
and logs. Matching output during `server_exec` or raw-terminal use does not authorize the window.

Non-interactive mode always passes `sudo -n`. It does not silently fall back to an interactive
prompt. `status` also uses a non-prompting validation. `release` calls `sudo -k` to invalidate the
remote timestamp associated with that connection.

Interactive clients should call `status` first and use `acquire` only when the held server
session has no active sudo timestamp. One successful acquisition is reused by all following
elevated commands in that session until the server-side sudo timeout, explicit `release`, or
session shutdown. Clients must not acquire and release around every individual operation. For a
long sequence of root operations, one explicitly opened root session avoids repeated sudo
validation and remains elevated until it is explicitly closed.

## Elevated command framing

`exec` Base64-encodes the requested script locally, transfers it in bounded chunks and decodes it
into sudo-owned Bash standard input. The command is never interpolated into shell syntax. Random
begin/end markers carry the root command's exit status; a missing completion marker is an unknown
or failed elevation outcome and is never retried automatically. Output is combined PTY output.

The command limit is 131072 UTF-8 bytes and timeout range is 0.1 through 3600 seconds. A completed
response identifies `effective_user = root` and `elevated = true`. It intentionally omits `cwd`,
because a one-shot elevated Bash does not change the held normal shell's directory.

## Dedicated root session

`open_root_session` starts a new worker, a new OpenSSH connection and `sudo -i` Bash. The worker
verifies `id -u` is zero before becoming ready. Its metadata includes its own session ID,
`root_session = true`, `effective_user = root`, and the normal parent session ID. It never replaces
or mutates the original worker.

Root sessions allow the regular execution and raw-terminal tools, but reject structured file
operations and further guided elevation. They must be explicitly closed with
`close_root_session` and their own session ID. Sudo timestamp sharing differs across server
configurations; non-interactive root-session startup therefore requires a valid existing policy
or NOPASSWD rule rather than assuming a normal session's cache will be shared.

For interactive root startup, the worker generates a fresh random operation nonce and embeds it
in a custom `sudo -p` prompt. Only a detected sudo prompt containing that nonce may reach
DirectAuth. A remote banner that merely resembles `[sudo] password for ...` is ignored. This binds
the startup prompt to that explicit root-session operation; server-side sudoers and PAM remain
the authorization and challenge sources.

## Automated evidence and manual gate

Unit tests cover mode policy, validation, framing, failure mapping, worker isolation and public
schema. A disposable Linux smoke proves controlled `sudo -n` failure, root identity and exit-code
framing. The full Windows path traverses MCP application, broker, worker, ConPTY and OpenSSH for
non-interactive sudo and a separate root worker. Interactive password entry remains an explicit
manual Windows release check because automation must not simulate the visible secret UI.
