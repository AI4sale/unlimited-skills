# Agent migrations

The library format is intentionally simple:

```text
<library-root>/registry/<collection>/skills/<skill-name>/SKILL.md
<library-root>/local/skills/<native-relative-path>/SKILL.md
```

Every migration script copies recursive directories that contain `SKILL.md` into a named collection.

## Dry-run first

All scripts default to dry-run mode.

```powershell
.\scripts\migrate-codex.ps1
```

```bash
./scripts/migrate-codex.sh
```

Apply explicitly:

```powershell
.\scripts\migrate-codex.ps1 -Apply
```

```bash
./scripts/migrate-codex.sh --apply
```

## Codex

Default source:

```text
%USERPROFILE%\.codex\skills
```

Default target:

```text
%USERPROFILE%\.codex\.unlimited-skills\library\local\skills
```

Codex migration preserves the source directory shape under `local/skills`, including `.system` skills so they remain available through the router. Duplicate local skills that are already provided by installed hosted/enhanced collections are copied under `local/duplicates` and are not indexed. `unlimited-skills` and `skill-library` are skipped to keep the visible Codex skill surface as one router skill. Registry, community, team, and bundled packs keep their own internal pack shape under `registry/<collection>/`.

Codex also needs the router skill installed:

```powershell
.\scripts\install-codex.ps1
```

```bash
./scripts/install-codex.sh
```

## Claude Code

Default source:

```text
%USERPROFILE%\.claude\skills
```

If your Claude Code skills are project-local, pass the project path:

```powershell
.\scripts\migrate-claude-code.ps1 -SourceRoot "D:\repo\.agents\skills" -Apply
```

```bash
./scripts/migrate-claude-code.sh --source-root "$HOME/.claude/skills" --apply
./scripts/migrate-claude-code.sh --source-root "/path/to/repo/.agents/skills" --apply
```

## OpenClaw

Default source:

```text
%USERPROFILE%\.openclaw\workspace\skills
```

Override it when needed:

```powershell
.\scripts\migrate-openclaw.ps1 -Apply
.\scripts\migrate-openclaw.ps1 -SourceRoot "D:\openclaw\workspace\skills" -Apply
```

```bash
./scripts/migrate-openclaw.sh --apply
./scripts/migrate-openclaw.sh --source-root "$HOME/.openclaw/workspace/skills" --apply
```

Prefer the full OpenClaw installer when setting up an agent:

```bash
./scripts/install-openclaw.sh --mode bundled
```

The installer also imports detected plugin and built-in OpenClaw skills into separate collections:

```text
openclaw-workspace
openclaw-plugin
openclaw-builtin
```

## Hermes

Default source:

```text
%USERPROFILE%\.hermes\skills
```

Plain migration copies Hermes skills into `local/hermes/skills` inside the Unlimited Skills library but does not reduce context if Hermes still scans the original visible skill root.

Override it when needed:

```powershell
.\scripts\migrate-hermes.ps1 -SourceRoot "D:\hermes\skills" -Apply
```

```bash
./scripts/migrate-hermes.sh --source-root "$HOME/.hermes/skills" --apply
```

For Hermes context reduction, use the adapter installer instead:

```powershell
.\scripts\install-hermes.ps1 -Mode evacuate-visible-skills -Apply
```

```bash
./scripts/install-hermes.sh --mode evacuate-visible-skills --apply
```

This moves real skills out of the Hermes-visible directory, installs only the `unlimited-skills` router, writes a rollback manifest, and prints before/after visible skill counts.

## Vellum AI

Default source:

```text
%USERPROFILE%\.vellum-ai\skills
```

Override it when needed:

```powershell
.\scripts\migrate-vellum-ai.ps1 -SourceRoot "D:\vellum\skills" -Apply
```

```bash
./scripts/migrate-vellum-ai.sh --source-root "$HOME/.vellum-ai/skills" --apply
```
