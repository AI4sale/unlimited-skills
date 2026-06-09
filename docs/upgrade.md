# Upgrade

Status: `v0.3.0-alpha`.

Upgrade from a GitHub clone:

```bash
git fetch --tags origin
git checkout <target-tag-or-branch>
python -m pip install -e ".[all]"
unlimited-skills --version
unlimited-skills reindex
unlimited-skills doctor --json
```

For the v0.3 alpha release candidate, run:

```bash
python scripts/verify-v0.3.0-alpha-package-assets.py
python scripts/run-v0.3.0-alpha-packaging-smoke.py
python scripts/run-managed-policy-sync-e2e.py --fixture-mode --temp-home
python scripts/run-v0.3.0-alpha-release-smoke.py
```

Sync/update flows must not delete pre-existing local library files. Managed policy sync may update only the Enterprise Skill Lock policy it owns through managed sync state.
