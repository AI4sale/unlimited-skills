# Security-gated skill installation

Unlimited Skills `0.6.9rc12` routes supported skill installation paths through
NVIDIA SkillSpector `2.5.0` before any skill files are copied into the library.

Run an audit without installing:

```bash
unlimited-skills security scan ./path/to/skill --json
```

The default scan is local static analysis with `--no-llm`. It scans the full
skill directory, including scripts, references, assets, manifests, and MCP
declarations. It does not execute skill contents.

Policy:

- `SAFE`: eligible inside an install operation the user already authorized;
- `CAUTION`: install is blocked pending review of every active finding;
- `DO_NOT_INSTALL`: install is blocked pending remediation or explicit risk
  acceptance by the authorized security owner;
- scanner unavailable, wrong version, invalid JSON, or incomplete coverage:
  fail closed.

This gate applies to `install-pack`, `import-dir`, `import-github`, registered
Community/Catalog installs, and hosted collection updates. Managed
Business/Enterprise private packs carry an archive-SHA-bound security
attestation inside the signed manifest, which the client validates before
download.

The gate is not a sandbox and cannot prove that a skill is harmless. Encrypted
payloads, image-hidden instructions, runtime-only behavior, and some
non-English attacks may require additional review.
