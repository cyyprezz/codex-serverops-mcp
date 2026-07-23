# ServerOps 0.1.1 release checklist

This checklist is the publication boundary. The automated suite is necessary but not sufficient.
Do not tag, publish, or describe `0.1.1` as released until the exact candidate commit, artifacts,
client cold starts, and manual real-server evidence all pass.

## 1. Freeze the candidate

1. Commit one stable-version candidate with `0.1.1` synchronized in the package, lockfile,
   registry, both marketplaces/plugins, both MCP pins, capability contract, active documentation,
   and release notes.
2. Confirm the worktree is clean and record `git rev-parse HEAD`.
3. Make no source changes after candidate testing. The only permitted follow-up is one commit that
   changes only `docs/release-evidence.json`.

Run the machine contract:

```powershell
$env:PYTHONPATH = "src"
python scripts/verify_release.py
```

## 2. Automated candidate gates

```powershell
uv sync --locked --all-groups --python 3.12
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
ruff check .
uv build

$Wheel = Get-ChildItem dist\*.whl | Select-Object -First 1
$Sdist = Get-ChildItem dist\*.tar.gz | Select-Object -First 1
python scripts/verify_distribution.py $Wheel.FullName $Sdist.FullName
python scripts/stdio_surface_smoke.py $Wheel.FullName --cache-dir .uv-cache
python scripts/stdio_surface_smoke.py $Wheel.FullName --offline --cache-dir .uv-cache
python scripts/stdio_surface_smoke.py $Wheel.FullName --offline --cache-dir .uv-cache `
  --manifest plugins/codex-serverops-mcp/.mcp.json --repeat 2
python scripts/stdio_surface_smoke.py $Wheel.FullName --offline --cache-dir .uv-cache `
  --manifest plugins/claude-serverops-mcp/.mcp.json --repeat 2

New-Item -ItemType Directory -Force checksums | Out-Null
python scripts/artifact_checksums.py create checksums\SHA256SUMS.txt `
  $Wheel.FullName $Sdist.FullName
python scripts/artifact_checksums.py verify checksums\SHA256SUMS.txt dist
```

Validate the repository and Claude Code plugin with the exact CI-pinned validator:

```powershell
npx --yes @anthropic-ai/claude-code@2.1.206 plugin validate . --strict
npx --yes @anthropic-ai/claude-code@2.1.206 plugin validate `
  .\plugins\claude-serverops-mcp --strict
```

Follow [release-candidate-checklist.md](release-candidate-checklist.md) for the detailed mapping
from requirements to evidence.

## 3. Clean Windows client gates

Execute [windows-test-plan.md](windows-test-plan.md) on clean Windows snapshots. Codex and Claude
Code must each install only their plugin and start the unchanged `0.1.1` manifest pin without a
prior setup command. Capture sanitized client versions, exact candidate commit, artifact hashes,
created ServerOps paths, DACL results, stdout parse results, Python 3.12 resolution, candidate
wheelhouse/cache provisioning, and before/after client/task hashes. If a test-only `uvx` shim is
needed before the exact pin exists on the public index, record its hash and keep both manifests
unchanged.

The repository smoke can prove the shared launch contract with a local candidate wheel. It does
not replace real plugin installation in each client. Likewise, Codex may present the initialized
eight-tool server to the model through one dynamic `mcp__serverops` gateway; record that client
presentation separately from the underlying MCP `tools/list` result.

## 4. Migration, rollback, and uninstall

Complete [migration-rollback-evidence.md](migration-rollback-evidence.md). Prove:

- public `0.1.0` schema-1 profiles and audit bytes remain unchanged;
- schema-0 migration has a protected hash-named preimage and verified rollback;
- explicit setup remains idempotent;
- plugin-only uninstall does not create or edit client configuration;
- default uninstall retains profiles and audit;
- `--remove-data` requires preview and explicit apply and refuses reparse targets; and
- the broker task remains an independent preview/apply decision.

## 5. Real SSH and visible-window gates

Run [manual-release-gates.md](manual-release-gates.md) with a disposable non-root Linux account.
The operator must directly observe password, encrypted-key, host-key, sudo, unusual-banner,
interrupt, disconnect, timeout, unknown-outcome, no-retry, and cleanup behavior.

Record the sanitized result:

```powershell
$env:PYTHONPATH = "src"
python scripts/manual_release_check.py --output docs/release-evidence.json
```

Every required check and external scenario must be `true`, `automated`, or `manually_verified` as
defined by the evidence schema. `not_tested` and `not_applicable` block release.

## 6. Commit-bound final gate

The evidence revision must be the candidate commit itself or its direct parent when the only
following commit adds `docs/release-evidence.json`.

```powershell
python scripts/verify_release.py `
  --tag v0.1.1 `
  --evidence docs/release-evidence.json
```

Merge the verified candidate and evidence into `main` before tagging. The tag workflow has no
manual-dispatch, token, skip-existing, or automated-evidence bypass. It publishes only after its
Windows build, tests, validators, distribution inspection, cold STDIO smoke, and checksum gates
pass. Publication still requires separate user authorization.
