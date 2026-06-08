# v0.2.x Release Smoke Tests

Run this suite before every public alpha release and before merging release-sensitive Local Skill Hub changes.

## Command

Linux/macOS:

```bash
scripts/run-v0.2x-smoke-tests.sh
```

Windows PowerShell:

```powershell
.\scripts\run-v0.2x-smoke-tests.ps1 -Python .\.venv\Scripts\python.exe
```

Direct Python:

```bash
python scripts/run-v0.2x-smoke-tests.py
```

The runner creates a temporary HOME and a temporary Unlimited Skills library root. It sets `UNLIMITED_SKILLS_HOME`, `HOME`, `USERPROFILE`, `HERMES_HOME`, and `UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC` for the subprocess. It also checks common real-home install targets after the run so smoke tests do not silently mutate user-level agent configuration.

## Coverage

The smoke suite covers:

- unregistered Community Core commands: `reindex`, `list`, `search`, `view`, `where`, and `serve` app wiring;
- registration-gated command boundaries for hosted updates, catalog, community, team, and `hub serve`;
- registry/local library layout and duplicate skill-name dedupe;
- Hermes visible-skill context risk detection through `doctor`;
- vector sidecar fast path without Chroma startup;
- Local Skill Hub allowlist-only runtime behavior with a synthetic fixture;
- Local Skill Hub token create/list/revoke and protected endpoint checks for missing, wrong, revoked, and valid tokens;
- remote Local Skill Hub client configure/status/search/resolve/view checks against a fake token-protected hub;
- explicit remote fallback checks for `local_allowed` and `hub_required`;
- hub allowlist bootstrap and cached `hub serve` wiring checks;
- token/secret redaction;
- docs/security claims for SHA256, planned signature verification, unregistered `serve`, registered `hub serve`, and allowlist-only full-catalog-disabled hub policy;
- self-update and install-pack git ref validation;
- production hosted network blocking by default.

## Feature Detection

The smoke suite is feature-detected so older topic branches can still report explicit skips. On the v0.2.1-alpha integration branch, the hub token, remote client, and allowlist bootstrap checks must run as real scenarios and should not be skipped.

Any skip for those three surfaces on a release integration branch means the branch is missing the corresponding runtime code and is not a valid RC.

## Network Policy

The default smoke suite must not call production hosted registry services. Tests monkeypatch `urllib.request.urlopen` and fail if a production host such as `unlimited.ai4.sale`, `api.github.com`, or `github.com` is used by default.

## Adding Scenarios

Add new release-sensitive checks to `tests/smoke/test_v02x_release_smoke.py`. Keep them:

- isolated to temp HOME/temp library roots;
- free of production hosted calls by default;
- fast enough for local release checks;
- explicit about skips when a feature is not merged yet.
