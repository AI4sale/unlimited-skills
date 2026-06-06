# Agent migrations

The library format is intentionally simple:

```text
<library-root>/<collection>/skills/<skill-name>/SKILL.md
```

Every migration script copies recursive directories that contain `SKILL.md` into a named collection.

## Dry-run first

All scripts default to dry-run mode.

```powershell
.\scripts\migrate-codex.ps1
```

Apply explicitly:

```powershell
.\scripts\migrate-codex.ps1 -Apply
```

## Codex

Default source:

```text
%USERPROFILE%\.codex\skills
```

Default target:

```text
%USERPROFILE%\.unlimited-skills\library\codex\skills
```

Codex also needs the router skill installed:

```powershell
.\scripts\install-codex.ps1
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

## OpenClaw

Default source:

```text
%USERPROFILE%\.openclaw\skills
```

Override it when needed:

```powershell
.\scripts\migrate-openclaw.ps1 -SourceRoot "D:\openclaw\skills" -Apply
```

## Hermes

Default source:

```text
%USERPROFILE%\.hermes\skills
```

Override it when needed:

```powershell
.\scripts\migrate-hermes.ps1 -SourceRoot "D:\hermes\skills" -Apply
```

## Vellum AI

Default source:

```text
%USERPROFILE%\.vellum-ai\skills
```

Override it when needed:

```powershell
.\scripts\migrate-vellum-ai.ps1 -SourceRoot "D:\vellum\skills" -Apply
```
