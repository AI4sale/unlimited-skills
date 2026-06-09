# Packaging

Status: `v0.3.0-alpha`.

## Distribution Decision

PyPI is not the supported `v0.3.0-alpha` distribution path. Use a GitHub clone.

Reason: the alpha product is more than the importable Python package. A working install needs repo assets that are intentionally kept visible and reviewable:

- router skills under `skills/`;
- shell and PowerShell installers under `scripts/`;
- migration and rollback scripts;
- schemas and sanitized examples;
- release and operations documentation;
- bundled starter/adapted packs when present in the repo.

A wheel-only install can provide the CLI entry point, but it cannot yet prove that agent router skills, installer scripts, and repo-managed assets are present on disk beside the checkout. PyPI packaging should wait until wheel/sdist asset inclusion and installer behavior are tested in CI.

## Required Asset Checks

Before publishing a v0.3.0-alpha release candidate, run:

```bash
python scripts/verify-v0.3.0-alpha-package-assets.py
python scripts/run-v0.3.0-alpha-packaging-smoke.py
```

The verifier checks:

- `pyproject.toml` and `unlimited_skills.__version__` agree on `0.3.0`;
- README and support docs identify `v0.3.0-alpha`;
- PyPI is explicitly documented as unsupported for this alpha;
- agent router skill assets exist;
- Codex, Claude Code, Hermes, and OpenClaw installers exist for PowerShell and shell;
- installer scripts expose opt-out and remote-token-safe flags;
- local library deletion is not documented as normal sync behavior.

The smoke test installs the checkout in an isolated environment, runs `unlimited-skills --version`, reindexes a temporary library, and verifies basic search/view behavior without production hosted calls.
