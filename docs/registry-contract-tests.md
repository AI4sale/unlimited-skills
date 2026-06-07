# Registry Contract Tests

The public repo validates the hosted registry contract without including the private hosted backend.

## What To Validate

- Every file under `schemas/` and `examples/registry/` is valid JSON.
- Registry examples contain no private `SKILL.md` bodies.
- Registry examples contain no prompts, source code, local paths, repository paths, customer names, environment variables, secrets, or device private keys.
- Placeholder hosted tokens are allowed only when clearly redacted, for example `uls_token_example_redacted`.
- Update examples are accepted by `parse_updates`.
- Enhancement examples are accepted by `parse_enhancement_script`.
- Registration response examples contain fields needed by `register_installation`: `license_token` or `token`, `plan`, `features_enabled`, and `proof_required`.
- Catalog request examples include collection state only, not local skill names or paths.
- Catalog response examples can show an early-access snapshot count, but not private skill bodies.
- Signature metadata is documented as optional/planned. Current client enforcement is SHA256 verification plus safe zip extraction.

## Script

Run the lightweight stdlib-only validator:

```bash
python scripts/validate-registry-contract.py
```

## Pytest

The test suite also exercises the examples against current client parsers:

```bash
python -m pytest tests
```
