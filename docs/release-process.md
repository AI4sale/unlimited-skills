# Release Process

Use this checklist before tagging a public alpha release.

## Skill Effectiveness Cadence Gate

Before tagging ANY release, run the cadence gate:

```bash
python scripts/check-skill-effectiveness.py --cadence-check
```

It fails when 10 or more releases have shipped since the last recorded effectiveness run («каждые 10 релизов прогоняется проверка эффективности скилла»). When it fails, run the full check against the bundled library, fix any regression, and commit the refreshed record:

```bash
python scripts/check-skill-effectiveness.py
git add evals/last-effectiveness-run.json
```

Thresholds, measured baselines, and rules live in [adoption/skill-effectiveness-standard.md](adoption/skill-effectiveness-standard.md).

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

## Skill Effectiveness Gate

Unlimited Skills public adoption releases must prove that skill suggestions are
fast, relevant, and privacy-safe. Run the deterministic A0 gate before merging
changes to ranking, router instructions, hooks, indexing, or skill import
behavior, and before every public adoption release:

```bash
python scripts/check-skill-effectiveness.py --json --no-record
python scripts/verify-skill-effectiveness-gate.py
```

For the v0.5 public adoption release, use the stricter release gate:

```bash
python scripts/verify-skill-effectiveness-gate.py --gate v0.5-release
```

See [skill-effectiveness.md](skill-effectiveness.md) for thresholds, privacy
boundaries, and the every-10-releases minimum.

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
python scripts/verify-v0.2.2-alpha-publication.py
python scripts/run-v0.2.2-alpha-fresh-install-smoke.py
python scripts/run-v0.2.2-alpha-upgrade-smoke.py
```

For `v0.3.0-alpha`, also run:

```bash
python scripts/verify-v0.3.0-alpha-package-assets.py
python scripts/run-v0.3.0-alpha-packaging-smoke.py
```

For `v0.3.1-alpha`, also run the post-release stabilization gate:

```bash
python scripts/run-v0.3.1-alpha-post-release-smoke.py
python scripts/run-v0.3.1-alpha-release-smoke.py
python scripts/verify-v0.3.1-alpha-stabilization.py
python scripts/verify-v0.3.1-alpha-publication.py --expected-sha <tag-target-sha>
```

The default `v0.3.1-alpha` publication verifier must fail until production-signed registry artifacts are verified. If the release owner explicitly accepts blocked registry signing as a known issue, rerun the verifier with `--allow-registry-signing-blocked --release-owner-override-reason "<reason>"` and document that decision in release notes.

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
10. Public PR #25: `release/v0.2.2-alpha-final-gate`
11. Private registry PR #6: `feat/production-registry-deployment-ops-v1`
12. Public PR #26: `feat/production-registry-onboarding-diagnostics-v1`
13. Public PR #27: `feat/enterprise-skill-lock-policy-mvp-v1`
14. Publication gate PR: `release/v0.2.2-alpha-publication`

Complete [releases/v0.2.2-alpha-checklist.md](releases/v0.2.2-alpha-checklist.md) before tagging.

The machine-readable release manifest must not contain placeholder SHAs. Immediately before pushing a tag, verify the tag target against the manifest:

```bash
python scripts/verify-v0.2.2-alpha-publication.py --expected-sha <tag-target-sha>
```

If the release merge strategy changes the tag target, refresh `docs/releases/v0.2.2-alpha.release-manifest.json` and rerun the verifier before tagging.

```bash
git tag v0.2.2-alpha <tag-target-sha>
git push origin v0.2.2-alpha
```

Then create GitHub release notes that include:

- release scope;
- known limitations;
- install-from-GitHub instructions;
- security boundary summary;
- smoke-test results.
