# Skill Manifest Capabilities

Local Skill Hub separates central retrieval from local capability checks.

Skill runtime categories:

- `pure_text`: guidance-only skill.
- `asset`: skill with distributable local assets.
- `tool`: skill that requires packages, binaries, or commands.
- `platform`: OS-specific or platform-specific workflow.
- `secret_dependent`: skill that needs client-side credentials.

## Manifest Shape

```yaml
schema_version: 1
name: example-skill
distribution:
  central_retrieval: true
  central_body_distribution: true
  central_asset_distribution: false
  default_hub_behavior: distribute_body
skill_kind: pure_text
compatible_agents:
  - codex
  - claude-code
  - hermes
  - openclaw
platforms:
  - linux
  - macos
  - windows
local_requirements:
  python_packages: []
  npm_packages: []
  binaries: []
  env_vars: []
assets:
  required: false
  distributable: false
execution:
  hub_executes: false
  client_executes: false
secrets_policy:
  requires_secrets: false
  secret_names: []
license:
  type: MIT
  source_repo: ""
  source_pack: ""
```

The hub can retrieve centrally. Local capabilities decide whether a client can use a tool/platform skill. Secrets stay client-side and are represented only by required variable names, never values.
