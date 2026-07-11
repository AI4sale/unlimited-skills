# Packaging

Status: `v0.6.7` PyPI-first release train.

## Distribution decision

PyPI is the supported user distribution path. The wheel includes the Python
package and bundled packs required by `quickstart`; package smoke verifies a
clean install, an upgrade from the public `0.6.4.post1` wheel, local-skill
preservation, index migration, retrieval, and frozen v0.6 CLI contracts.

```bash
python -m pip install --upgrade "unlimited-skills>=0.6.7"
python -m pip install --upgrade "unlimited-skills[all]>=0.6.7"  # vector + daemon
```

A GitHub clone remains the contributor/operator distribution because it also
contains source tests, release scripts, full docs, schemas, examples, and
agent-specific installer scripts:

```bash
git clone https://github.com/AI4sale/unlimited-skills.git
cd unlimited-skills
python -m pip install -e ".[all]"
```

## Release gates

The v0.6.7 workflow builds wheel and sdist once, runs `twine check` and tests
that exact artifact set, publishes through PyPI Trusted Publishing, waits for
the exact public version JSON, installs the public wheel into a clean
environment, and creates the GitHub tag/release only after that public-wheel
smoke passes. GitHub therefore cannot advertise a newer supported release than
PyPI.

Run the local source gates before publication:

```bash
python scripts/verify-v066-product-polish.py
python scripts/verify-v06-frozen-contracts.py
python scripts/verify-skill-effectiveness-gate.py
```

See `docs/releases/v0.6.7-plan.md` and `.github/workflows/publish-pypi.yml` for the
exact contract.
