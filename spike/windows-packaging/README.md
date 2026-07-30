# Windows packaging spike

This is a non-shipping 0.1.1A prototype. It tests whether the current Python package can be frozen
as one versioned onedir runtime with six explicit process roles. It does not create an installer,
change a release workflow, register a task, sign files, or modify AI-client configuration.

## Build contract

- Windows x64, Python 3.12, locked project dependencies, PyInstaller 6.21.0.
- Onedir only; no onefile extraction, UPX, or runtime downloads.
- Console roles: `serverops-mcp`, `serverops-broker`, `serverops-session-worker`,
  `serverops-install`.
- Windowed roles: `serverops-setup`, `serverops-auth`.
- Output: `spike/windows-packaging/out/ServerOps/`.

Run `./build.ps1`. The script uses Python/uv only as build tools. It copies the frozen output to an
isolated directory and proves `serverops-install.exe --version` without Python or uv on the runtime
PATH. Generated `build/` and `out/` folders are disposable and are not release artifacts.

## What the spike can and cannot prove

PyInstaller analysis and the version smoke test cover import discovery and a Python/uv-free frozen
process. Before 0.1.2 the prototype must also demonstrate MCP initialization, broker/worker named
pipes, pywin32 and pywinpty loading, an actual visible auth prompt, setup UI, and role-to-role launch
resolution on a clean Windows VM.

The current production broker/worker launch path can still rely on `sys.executable -m`; a frozen
role resolver is intentionally deferred to 0.1.2. Therefore a successful build is feasibility
evidence, not a claim that the frozen runtime is production-ready.

The spike intentionally excludes the optional `mcp.cli` module family. ServerOps imports the MCP
server API directly; freezing unused CLI modules would add an unnecessary `typer` dependency and a
larger update surface.

The current bundled development Python reports a broken Tk/Tcl installation during freezing.
Consequently the spike can build process stubs but cannot establish functional setup/auth windows
from this runtime. A 0.1.2 build image must pin and verify a Python distribution with working Tk,
then open both windows in Windows E2E before packaging can be accepted.

## 0.1.1A observed result

The pinned build completes and the frozen `serverops-install.exe --version` succeeds with a PATH
that contains neither Python nor uv. The frozen MCP process initializes and exposes the exact eight
tools, and the frozen broker starts, answers protocol-3 ping over its named pipe, and shuts down
cleanly. MCP client close currently emits `ValueError: I/O operation on closed file` on stderr even
though initialization succeeded; this shutdown defect must be reproduced and removed before 0.1.2.
Worker/ConPTY operation and the two Tk windows remain unproven by this spike runtime.

## Release recommendation

Proceed with ADR 017 option 3: a signed per-user Inno Setup package with immutable version
directories, separate signed binaries, an atomic active-version record, previous-version rollback,
and preserved LocalAppData state. CI should build from a clean archive, verify hashes/signatures,
run the clean-VM matrix, scan with Defender, and retain the unsigned reproducibility manifest plus
signed release manifest. Timestamp all signatures and keep certificate identity stable to reduce,
not promise elimination of, SmartScreen warnings.
