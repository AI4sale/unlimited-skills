# Skill Runtime Manifests And Capabilities

Retrieval can be centralized, but dependencies and capabilities remain local. Local Skill Hub may return skill metadata and selected skill bodies, but it never executes skills, installs packages, runs scripts, or receives secret values.

## Manifest Sources

The hub reads runtime metadata in this order:

1. `skill-runtime-manifest.json` next to `SKILL.md`.
2. `SKILL.md` frontmatter fields such as `skill_kind`, `python_packages`, `npm_packages`, `binaries`, `env_vars`, and `platforms`.
3. Allowlist metadata.
4. Inferred fallback metadata.

## Skill Kinds

Allowed `skill_kind` values:

- `pure_text`
- `asset`
- `tool`
- `platform`
- `secret_dependent`

## Local Requirements

Runtime manifests list names only:

```json
{
  "local_requirements": {
    "python_packages": ["playwright"],
    "npm_packages": [],
    "binaries": ["docker"],
    "env_vars": ["N8N_API_KEY"],
    "platforms": ["linux"]
  }
}
```

Environment variable values are never captured, sent, cached, or printed. Only names such as `N8N_API_KEY` may appear.

## Resolve Behavior

`remote resolve` sends local client capability names to the hub. The hub compares manifest requirements to those capabilities and returns:

- `missing_capabilities`
- `matched_capabilities`
- `install_plan_available`
- `warnings`

Pure text skills can still return body content. Tool, platform, and secret-dependent skills return metadata and dry-run install-plan guidance when local requirements are missing.

## Install Plans

`unlimited-skills remote install-plan <skill-name>` is dry-run metadata only. It prints required package names, binary names, environment variable names, platform constraints, warnings, and missing capabilities. It does not execute install commands.
