# Install

Status: `v0.3.1-alpha` stabilization train. Published baseline: `v0.3.0-alpha`.

Use a GitHub clone for this alpha:

```bash
git clone https://github.com/AI4sale/unlimited-skills.git
cd unlimited-skills
python -m pip install -e ".[all]"
unlimited-skills --version
```

PyPI is not the supported `v0.3.1-alpha` distribution path because the alpha still depends on repo assets: router skills, installers, schemas, docs, and migration scripts.

See [install-upgrade-uninstall.md](install-upgrade-uninstall.md) for agent-specific installer commands.

After installation, run the first-run wizard:

```bash
unlimited-skills setup --local-only --dry-run
unlimited-skills setup --local-only
```

Use [first-run-setup.md](first-run-setup.md) for registered, hub, and Enterprise onboarding modes.
