# ServerOps 0.1.1 artifact and checksum plan

## Release artifact set

The immutable release set contains exactly:

1. `codex_serverops_mcp-0.1.1-py3-none-any.whl`
2. `codex_serverops_mcp-0.1.1.tar.gz`
3. `SHA256SUMS.txt`

Plugin and marketplace files are distributed from the same tagged Git repository. They are not
separate binary release artifacts and must reference the same `0.1.1` package.

## Build and verification

The Windows tag job builds wheel and sdist once, inspects both, rebuilds a wheel from the sdist,
compares Python payload bytes, performs online then offline STDIO/bootstrap smoke, and creates the
checksum manifest from the original wheel and sdist. The offline phase also launches the unchanged
Codex and Claude `.mcp.json` arguments twice against the candidate wheelhouse; this supplements,
but does not replace, clean-client plugin installation.

`scripts/artifact_checksums.py` writes lowercase SHA-256 in sorted, path-free format:

```text
<64 lowercase hex>  <artifact filename>
```

The verifier accepts exactly one `.whl` and one `.tar.gz`, rejects duplicates, paths, whitespace,
missing files, changed bytes, or a manifest that includes itself.

## Publication flow

1. Upload wheel/sdist as the short-retention `python-distributions` workflow artifact.
2. Upload `SHA256SUMS.txt` separately as `release-checksums` so PyPI receives only valid Python
   distributions.
3. Publish the already verified wheel/sdist with PyPI Trusted Publishing and attestations.
4. Create the GitHub release from the verified tag and attach the same wheel, sdist, and checksum
   file. Do not rebuild between destinations.
5. Verify the GitHub assets against `SHA256SUMS.txt`, then compare PyPI-reported SHA-256 values.

The workflow must never use `skip-existing`; an existing filename/version is a release failure.
Code signing for a future Windows executable belongs to 0.1.2 and is not claimed for these Python
artifacts.

## Rollback

Python package versions are immutable. If any artifact or hash differs, stop before publication and
create a new candidate; never replace an uploaded file. If a defect is found after release, keep the
evidence and artifacts, document the affected version, and prepare a new patch release. Do not
delete or silently overwrite release assets as a rollback mechanism.
