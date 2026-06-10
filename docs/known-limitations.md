# Known Limitations

`v0.3.5-alpha` is a developer preview, not a stable production SLA.

- Hosted registry access is early-access.
- The registered hosted catalog exists and is populated, but availability may be limited during alpha.
- Exact registered catalog contents are delivered through registered hosted catalog/update commands, not published in the MIT repo.
- Community submissions are implemented as explicit registered uploads with local dry-run preview, hosted maintainer review, and signed approved/published distribution. `community submit --dry-run` remains local-only and uploads nothing.
- Enterprise Skill Lock is an opt-in local policy MVP. Managed hosted policy sync client behavior is implemented and fixture-verified; production private-registry endpoint delivery remains an in-review private registry dependency for the v0.3 alpha stack. SSO, SCIM, billing, organization administration, hosted dashboard controls, and broad enterprise private-registry enforcement are not implemented in this alpha.
- Private team pack client commands are implemented and fixture-verified. Production private pack access requires registry-side entitlement or a Business/Enterprise plan plus the private registry distribution, publishing, admin, and entitlement PRs being accepted and deployed.
- Hosted remote manifests must include valid signed manifest envelopes. SHA256 verification is still enforced for hosted collection archives and enhancement scripts before local installation.
- PyPI is not the supported v0.3.5-alpha distribution path because router skills, scripts, docs, and bundled packs are repo assets.
- Warm daemon mode is experimental and not the default retrieval path.
- Team sync is an MVP; server-side enforcement of limits and paid plan behavior may evolve.
- Local Skill Hub runtime is MVP alpha. The public repo includes docs, schemas, sanitized examples, CLI commands, and an allowlist-backed local FastAPI runtime when `server` extras are installed.
- Local Skill Hub can bootstrap from a validated local fixture allowlist or registered hosted allowlist metadata. The public repo includes only sanitized fake allowlist fixtures, not private registered skill bodies.
- Local Skill Hub LAN mode is alpha. It requires explicit `--allow-lan` and at least one active hub client token, but serious LAN deployment still needs reverse proxy/TLS and normal network access controls.
- `remote search`, `remote resolve`, and `remote view` call a configured Local Skill Hub over HTTP with hub-token auth. They are still alpha client runtime commands, not hosted registry search.
- Remote fallback is explicit: `local_allowed` falls back to the local library when the hub is unavailable, while `hub_required` fails.
- The current private registry audit verdict is `YES_WITH_ALLOWLIST` after scanning 315 skills.
- Full catalog distribution is disabled. Local Skill Hub uses allowlist-only distribution.
- Community install requires signed hosted metadata and an `approved` or `published` review status. Pending, rejected, withdrawn, deprecated, retired, and unreviewed items must not install silently.
- No marketplace storefront, billing, checkout, revenue share, live payment provider, card data, or bank data behavior is included in v0.3.5-alpha.
- Tool/platform skills use dry-run local install plans and client capability matching. The hub still never executes skills or installs packages.
- Existing `unlimited-skills serve` remains the separate free local daemon and does not require registration.
