# Configuration model

The local configuration is stored at:

```text
%LOCALAPPDATA%\codex-serverops-mcp\config.toml
```

Schema version 1 supports direct OpenSSH targets and existing OpenSSH aliases. Configuration
is parsed fail-closed: unknown fields, unsupported schema versions, mixed connection modes and
invalid value combinations are rejected.

## Direct target

```toml
schema_version = 1

[profiles."kunde-prod"]
display_name = "Kunde Produktion"
connection_type = "direct"
authentication = "interactive_password"
host = "192.168.1.50"
port = 22
user = "deploy"
allowed_roots = ["/opt/app"]
allow_terminal = true
allow_file_read = true
allow_file_write = false
elevation_mode = "interactive"
allow_root_session = false
environment = "production"
command_timeout_seconds = 60
max_output_bytes = 2097152
```

The worker builds a direct target from separately validated arguments. It does not
construct a shell command and does not reimplement complex OpenSSH configuration behavior.

## OpenSSH alias

```toml
schema_version = 1

[profiles."example-prod"]
display_name = "Example production"
connection_type = "ssh_config"
authentication = "openssh"
ssh_host = "example-prod"
allowed_roots = ["/opt/example-app"]
allow_terminal = true
allow_file_read = true
allow_file_write = false
elevation_mode = "interactive"
allow_root_session = false
environment = "production"
command_timeout_seconds = 60
max_output_bytes = 2097152
```

`ProxyJump`, `ProxyCommand` and organization-specific SSH behavior remain the responsibility
of the user's existing OpenSSH configuration and are selected through `ssh_host`.

## Validation and persistence

- Profile identifiers use at most 64 letters, digits, dots, underscores or hyphens.
- Direct profiles require host, port and Linux user and cannot also define an SSH alias.
- Alias profiles use OpenSSH authentication and cannot contain direct target fields.
- Structured file access requires at least one absolute normalized remote root.
- Structured write access requires structured read access.
- A guided root session requires an enabled elevation mode and terminal access.
- Configuration writes use a same-directory temporary file, `fsync`, and atomic replacement.
- A sibling byte-range lock serializes readers, writers and migrations across processes.
- SHA-256 snapshot hashes prevent silent lost updates after a caller has read the file.
- The schema-0 development draft migrates `sudo_mode` to `elevation_mode`; newer unknown
  schemas fail closed.

The following fields are forbidden and cause the complete profile to be rejected:

```text
password
sudo_password
key_passphrase
private_key_content
```

`allowed_roots` applies only to `server_files` and `server_file_edit`. Remote roots must be
absolute normalized paths without control characters and are canonicalized again by each remote
operation. They do not restrict arbitrary shell commands. Likewise, `elevation_mode` controls
the guided workflow but is not a server-side sudo boundary.

## Elevation modes

- `disabled` makes every guided action except non-prompting `status` unavailable.
- `non_interactive` always passes `sudo -n`; authentication failure is returned to the caller and
  never opens a prompt.
- `interactive` may open the same isolated visible authentication program used for SSH login.
  The sudo password travels only from that program directly to the owning worker.

`allow_root_session = true` separately permits a dedicated root worker. It does not reuse the
normal Bash process and does not enable structured file operations as root. The remote server's
sudoers configuration remains authoritative in every mode.
