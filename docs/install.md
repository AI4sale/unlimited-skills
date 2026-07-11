# Install

Status: `v0.6.7` release train.

Install the free local core from PyPI:

```bash
python -m pip install --upgrade "unlimited-skills>=0.6.7"
unlimited-skills --version
unlimited-skills quickstart
```

The base install provides the fast lexical router. Install the local
multilingual vector sidecar and warm daemon dependencies with:

```bash
python -m pip install --upgrade "unlimited-skills[all]>=0.6.7"
unlimited-skills vector-reindex
```

For repository development, clone GitHub and use
`python -m pip install -e ".[all]"`. The v0.6 wheel already includes the
bundled packs needed by `quickstart`; repository-only contributor scripts and
the complete documentation tree remain in the checkout.

See [install-upgrade-uninstall.md](install-upgrade-uninstall.md) for agent-specific installer commands.

After installation, run the first-run wizard:

```bash
unlimited-skills setup --local-only --dry-run
unlimited-skills setup --local-only
```

Use [first-run-setup.md](first-run-setup.md) for registered, hub, and Enterprise onboarding modes.
