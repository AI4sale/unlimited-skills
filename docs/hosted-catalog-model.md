# Hosted Catalog Model

Unlimited Skills separates the local MIT core from hosted catalog surfaces.

## Official Adapted-Skill Catalog

The registered hosted catalog is AI4sale-maintained, registration-gated, already populated in early access, and delivered through hosted catalog/update commands. The public MIT repository documents schemas and sanitized examples only; it does not publish private registered skill bodies.

Registered clean installs must not receive an empty catalog. The baseline registered community catalog includes starter metadata and update archives for:

- `ecc`: adapted Everything Claude Code skills from [affaan-m/ECC](https://github.com/affaan-m/ECC);
- `superpowers`: adapted Superpowers workflow skills from [obra/superpowers](https://github.com/obra/superpowers).

The hosted registry may add more community collections over time, but these two starter packs are the minimum useful registered catalog surface.

## Community-Skills Catalog

The `community-skills` catalog is the planned/early-access community publishing surface. Community submissions require explicit upload confirmation and intentionally upload only the selected skill or pack. Telemetry, catalog checks, update checks, and enhancement script metadata calls do not upload local skill bodies.

## Team, Private, And Enterprise Catalogs

Team/private catalogs are future Pro, Team, Business, and Enterprise surfaces. Enterprise Skill Lock, private registries, signed policy controls, and business enforcement are planned/paid hosted services and are not implemented in the public MIT client in this PR.

## Catalog Item Lifecycle

```text
draft -> reviewed -> approved -> published -> deprecated -> retired
```

## Collection Lifecycle

```text
versioned release -> manifest -> archive -> sha256 -> hosted update -> client apply -> local reindex
```

The hosted update archive format is `skill-collection-zip-v1`. Hosted update manifests must include a valid signed manifest envelope. The client verifies `manifest_signature` against a key trusted for the `catalog-updates` scope and the registry origin, enforces archive SHA256 verification, and uses safe zip extraction before installation.

## Compatibility Fields

Hosted catalog collection metadata can include:

- `compatible_agents`: `codex`, `claude-code`, `hermes`, `openclaw`
- `min_client_version`
- `max_client_version`
- `platforms`
- `skill_format`

## Visibility

Recommended visibility values:

- `registered-community`
- `team-free`
- `pro`
- `enterprise`

## Privacy Rules

Catalog and update check requests must not use user local skill names, local paths, repository paths, prompts, source code, customer names, environment variables, tokens, secrets, or device private keys.

The server may return official hosted catalog skill names or counts because that is registry-owned metadata. Public examples should use sanitized collection names and counts only.
