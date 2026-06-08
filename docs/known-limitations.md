# Known Limitations

`v0.2.0-alpha` is a developer preview, not a stable production SLA.

- Hosted registry access is early-access.
- The registered hosted catalog exists and is populated, but availability may be limited during alpha.
- Exact registered catalog contents are delivered through registered hosted catalog/update commands, not published in the MIT repo.
- Community submissions are planned and not fully implemented unless current code explicitly says otherwise.
- Enterprise Skill Lock is planned.
- Cryptographic signature verification is planned. SHA256 verification is enforced today for hosted collection archives and enhancement scripts.
- PyPI is not the v0.2.0 distribution path because router skills, scripts, docs, and bundled packs are repo assets.
- Warm daemon mode is experimental and not the default retrieval path.
- Team sync is an MVP; server-side enforcement of limits and paid plan behavior may evolve.
- Local Skill Hub runtime is MVP alpha. The public repo includes docs, schemas, sanitized examples, CLI commands, and an allowlist-backed local FastAPI runtime when `server` extras are installed.
- Local Skill Hub LAN mode is alpha. It requires explicit `--allow-lan` and at least one active hub client token, but serious LAN deployment still needs reverse proxy/TLS and normal network access controls.
- `remote search`, `remote resolve`, and `remote view` are contract skeletons until the next remote-client PR wires real hub calls.
- The current private registry audit verdict is `YES_WITH_ALLOWLIST` after scanning 315 skills.
- Full catalog distribution is disabled. Local Skill Hub uses allowlist-only distribution.
- Tool/platform skills require local install plan and client capability support.
- Existing `unlimited-skills serve` remains the separate free local daemon and does not require registration.
