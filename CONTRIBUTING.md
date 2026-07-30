# Contributing to ServerOps

ServerOps favors a small, reliable core over a large collection of thin command wrappers. Before
proposing a feature, check [AGENTS.md](AGENTS.md) and [ROADMAP.md](ROADMAP.md): new core behavior
must justify itself through durable state, large or binary data, resume, atomicity, idempotency,
event delivery, verification, or multi-client coordination.

## Development setup

Use Windows 10 or 11 and Python 3.12:

```powershell
uv sync --locked --all-groups --python 3.12
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
ruff check .
uv build
```

Run `python scripts/verify_release.py` and `python scripts/verify_distribution.py` as described in
[the release checklist](docs/release-checklist.md) when changing packaging or release contracts.

## Change expectations

- Preserve package names, entry points, configuration paths, protocols, profile data, audit data,
  and explicit unknown-outcome behavior unless a reviewed migration says otherwise.
- Add focused tests for code, manifests, documentation claims, and compatibility contracts.
- Keep credentials, private keys, customer identifiers, and production output out of commits,
  tests, issues, and examples.
- Document architectural decisions in [docs/adr](docs/adr/README.md).
- Do not claim planned capabilities as shipped. Public version pins change together during release
  hardening.

Open an issue before a broad architectural change. For security reports, follow
[SECURITY.md](SECURITY.md) instead of opening a public issue.
