from pathlib import Path

spike_root = Path(SPECPATH)
repo_root = spike_root.parents[1]
source_root = repo_root / "src"
launcher_root = spike_root / "launchers"

hidden_imports = [
    "win32api",
    "win32con",
    "win32security",
    "pywintypes",
    "ntsecuritycon",
]
roles = (
    ("serverops-mcp", "serverops_mcp.py", True),
    ("serverops-broker", "serverops_broker.py", True),
    ("serverops-session-worker", "serverops_session_worker.py", True),
    ("serverops-install", "serverops_install.py", True),
    ("serverops-setup", "serverops_setup.py", False),
    ("serverops-auth", "serverops_auth.py", False),
)

analyses = []
executables = []
for name, launcher, console in roles:
    analysis = Analysis(
        [str(launcher_root / launcher)],
        pathex=[str(source_root)],
        binaries=[],
        datas=[],
        hiddenimports=hidden_imports,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=[],
        noarchive=False,
        optimize=0,
    )
    pyz = PYZ(analysis.pure)
    executable = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=console,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    analyses.append(analysis)
    executables.append(executable)

COLLECT(
    *executables,
    *(analysis.binaries for analysis in analyses),
    *(analysis.datas for analysis in analyses),
    strip=False,
    upx=False,
    name="ServerOps",
)
