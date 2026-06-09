# Release Process

Use this checklist before tagging a public alpha release.

## Version Bump Checklist

- Update `pyproject.toml`.
- Update `unlimited_skills/__init__.py`.
- Update README version wording.
- Update `SECURITY.md` supported version.
- Update `CHANGELOG.md`.
- Update `docs/releases/<version>.release-manifest.json`.

## Docs Consistency Checklist

- README, SECURITY, CHANGELOG, and docs agree on the current alpha version.
- Local Community Core commands are documented as registration-free.
- Hosted catalog/update/enhancer/team commands are documented as registration-gated.
- Public self-update remains unregistered.
- Hosted catalog is described as registration-gated early access and populated without publishing private registered skill bodies.
- PyPI is not presented as the v0.2.x distribution path.

## Security Wording Checklist

- State that hosted remote manifests require valid signed manifest envelopes.
- State that signatures verify manifest authenticity.
- State that SHA256 verifies downloaded archive bytes against the signed manifest.
- Do not claim archive-byte signature verification unless that is implemented separately.
- State that zip extraction rejects path traversal.
- State that enhancement scripts are SHA256-verified before execution.
- State that hosted clients must not upload skill bodies, prompts, source code, full paths, repo paths, customer names, env vars, tokens, secrets, or device private keys.
- State that private signing keys are never shipped in the client or committed to the repo.
- State that Local Skill Hub is allowlist-only until a release explicitly enables a broader distribution policy.

## Smoke Tests

Run the repeatable v0.2.x smoke suite first:

```bash
python scripts/run-v0.2x-smoke-tests.py
```

See [release-smoke-tests.md](release-smoke-tests.md) for coverage, feature-detection behavior, and extension rules.

For `v0.2.2-alpha`, also run:

```bash
python scripts/run-staging-registry-e2e.py --fixture-mode --temp-home
python scripts/run-production-registry-contract-e2e.py --fixture-mode --temp-home
python scripts/run-v0.2.2-alpha-cross-repo-smoke.py --fixture-mode --temp-home
python scripts/verify-v0.2.2-alpha-release.py
python scripts/run-v0.2.2-alpha-fresh-install-smoke.py
python scripts/run-v0.2.2-alpha-upgrade-smoke.py
```

Legacy ad hoc checks may still be useful for manual verification:

```bash
python -m pip install -e ".[all]"
unlimited-skills reindex
unlimited-skills search "security review"
unlimited-skills view <known-skill>
unlimited-skills serve --host 127.0.0.1 --port 8765
unlimited-skills doctor --json
```

Additional alpha checks:

- unregistered: local search works;
- unregistered: `updates check` fails with registration-required wording;
- Hermes sandbox: fake `.hermes/skills`, context reduction leaves only router, rollback restores;
- OpenClaw sandbox: installer patches `AGENTS.md` unless opt-out;
- Claude Code sandbox: project `.claude/skills` are mirrored on router CLI call.

## Tag And Release Checklist

Required merge order for `v0.2.2-alpha`:

1. Private registry PR #2: signed registry manifest publisher.
2. Public PR #13 through PR #20: v0.2.1-alpha runtime, trust, lifecycle, and finalization baseline.
3. Private registry PR #3: `feat/staging-signed-registry-api-v1`
4. Public PR #21: `test/staging-signed-registry-e2e-v1`
5. Public PR #22: `feat/hub-plan-heartbeat-entitlement-sync-v1`
6. Private registry PR #4: `feat/registry-production-api-mvp-v1`
7. Public PR #23: `test/production-registry-contract-e2e-v1`
8. Private registry PR #5: `feat/registry-release-channels-rollback-v1`
9. Public PR #24: `feat/client-channel-pinning-update-rollback-v1`
10. Final gate PR: `release/v0.2.2-alpha-final-gate`

Complete [releases/v0.2.2-alpha-checklist.md](releases/v0.2.2-alpha-checklist.md) before tagging.

```bash
git tag v0.2.2-alpha
git push origin v0.2.2-alpha
```

Then create GitHub release notes that include:

- release scope;
- known limitations;
- install-from-GitHub instructions;
- security boundary summary;
- smoke-test results.
