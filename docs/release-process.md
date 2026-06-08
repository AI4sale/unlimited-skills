# Release Process

Use this checklist before tagging a public alpha release.

## Version Bump Checklist

- Update `pyproject.toml`.
- Update `unlimited_skills/__init__.py`.
- Update README version wording.
- Update `SECURITY.md` supported version.
- Update `CHANGELOG.md`.

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

## Smoke Tests

Run the repeatable v0.2.x smoke suite first:

```bash
python scripts/run-v0.2x-smoke-tests.py
```

See [release-smoke-tests.md](release-smoke-tests.md) for coverage, feature-detection behavior, and extension rules.

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

Required merge order for `v0.2.1-alpha`:

1. PR #13: `release/v0.2.1-alpha-hub-runtime-integration`
2. PR #14: `feat/remote-hub-router-installers-v1`
3. PR #15: `feat/capability-aware-local-install-plans-v1`
4. PR #16: `feat/signed-hub-manifests-v1`
5. PR: `release/v0.2.1-alpha-ci-and-merge-gate`

Complete [releases/v0.2.1-alpha-checklist.md](releases/v0.2.1-alpha-checklist.md) before tagging.

```bash
git tag v0.2.1-alpha
git push origin v0.2.1-alpha
```

Then create GitHub release notes that include:

- release scope;
- known limitations;
- install-from-GitHub instructions;
- security boundary summary;
- smoke-test results.
