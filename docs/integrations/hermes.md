# Hermes integration

Hermes can expose every `SKILL.md` under its visible skills directory at session startup. If that directory contains hundreds of ECC or Superpowers skills, installing Unlimited Skills as another ordinary skill does not reduce startup context: Hermes can still see the original skills.

For Hermes, context reduction requires a router-only adapter:

1. copy visible Hermes skills into the Unlimited Skills library;
2. move the original visible skill directories into a rollback backup;
3. install only the Hermes router skill at `~/.hermes/skills/unlimited-skills`;
4. rebuild the lexical index;
5. print a before/after report and rollback manifest.

## Dry run first

macOS/Linux/Git Bash:

```bash
./scripts/install-hermes.sh --mode evacuate-visible-skills
```

Windows PowerShell:

```powershell
.\scripts\install-hermes.ps1 -Mode evacuate-visible-skills
```

Dry runs do not modify files and explicitly say so.

## Apply router-only context reduction

macOS/Linux/Git Bash:

```bash
./scripts/install-hermes.sh --mode evacuate-visible-skills --apply
```

Windows PowerShell:

```powershell
.\scripts\install-hermes.ps1 -Mode evacuate-visible-skills -Apply
```

Defaults:

```text
Hermes visible root: ~/.hermes/skills
Install root:        ~/.unlimited-skills
Library root:        ~/.unlimited-skills/library
Backup root:         ~/.unlimited-skills/backups/hermes-visible-skills-YYYYMMDD-HHMMSS
```

Use custom locations when needed:

```bash
./scripts/install-hermes.sh \
  --hermes-home "$HOME/.hermes" \
  --install-root "$HOME/.unlimited-skills" \
  --mode evacuate-visible-skills \
  --apply
```

```powershell
.\scripts\install-hermes.ps1 `
  -HermesHome "$env:USERPROFILE\.hermes" `
  -InstallRoot "$env:USERPROFILE\.unlimited-skills" `
  -Mode evacuate-visible-skills `
  -Apply
```

## Install only the router

If you already moved skills out of Hermes' visible directory, install just the router:

```bash
./scripts/install-hermes.sh --mode router-only --apply
```

```powershell
.\scripts\install-hermes.ps1 -Mode router-only -Apply
```

## Expected report

A successful context-reduction install prints a report shaped like this:

```text
Hermes Unlimited Skills install report

Visible Hermes skill root:
  ~/.hermes/skills

Before:
  visible SKILL.md count: 184

Migrated to library:
  local path: local/hermes/skills
  migrated skills: 184

After:
  visible SKILL.md count: 1
  visible skills:
    - unlimited-skills

Router:
  installed: yes
  launcher: ~/.hermes/skills/unlimited-skills/scripts/unlimited-skills.sh

Index:
  lexical index: rebuilt
  vector index: skipped

Rollback:
  manifest: ~/.unlimited-skills/backups/hermes-visible-skills-.../manifest.json
```

The key proof is the after-count: only the `unlimited-skills` router should remain visible to Hermes.

## Rollback

Use the manifest path from the install report.

Dry run:

```bash
./scripts/rollback-hermes.sh --manifest ~/.unlimited-skills/backups/hermes-visible-skills-YYYYMMDD-HHMMSS/manifest.json
```

Apply:

```bash
./scripts/rollback-hermes.sh --manifest ~/.unlimited-skills/backups/hermes-visible-skills-YYYYMMDD-HHMMSS/manifest.json --apply
```

PowerShell:

```powershell
.\scripts\rollback-hermes.ps1 -Manifest "$env:USERPROFILE\.unlimited-skills\backups\hermes-visible-skills-YYYYMMDD-HHMMSS\manifest.json" -Apply
```

Rollback removes the generated Hermes router and restores the evacuated visible skill directories from backup.

## Migration versus context reduction

`migrate-hermes` is a library importer. It copies skills into Unlimited Skills and leaves the source directory untouched.

That is useful for preserving skills, but it does not reduce Hermes startup context if Hermes still scans `~/.hermes/skills`.

Use `install-hermes --mode evacuate-visible-skills --apply` when your goal is to reduce Hermes' visible skill list.
