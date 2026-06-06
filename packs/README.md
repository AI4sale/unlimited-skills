# Bundled Skill Packs

This directory contains optional skill packs that can be installed with:

```bash
scripts/install-codex.sh --mode bundled
```

or on Windows:

```powershell
.\scripts\install-codex.ps1 -Mode bundled
```

Bundled packs are not required for the default install path. By default, Unlimited Skills installs the router skill, migrates the user's existing local skills, and indexes them.

## Sources

- `ecc` is adapted from [affaan-m/ECC](https://github.com/affaan-m/ECC).
- `superpowers` is adapted from [obra/superpowers](https://github.com/obra/superpowers).

Each imported skill keeps source metadata in its frontmatter, including the original repository URL, source path, and adapter version where available.

## Adaptation Level

The adapter targets action memory rather than plain RAG. A useful skill must teach an agent how to act, so adapted skills are organized around:

- when to use the skill;
- when not to use it;
- required context;
- procedure;
- tools;
- expected output;
- known traps;
- examples of successful execution;
- regression tests.

`superpowers` is included as the first fully agent-adapted pilot pack. `ecc` is included as a structurally normalized imported pack and can be upgraded one skill at a time through the agent adaptation workflow in `docs/agent-skill-adaptation.md`.
