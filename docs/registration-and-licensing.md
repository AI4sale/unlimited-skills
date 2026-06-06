# Registration and Licensing

Unlimited Skills has two layers with different access models.

## Community Core

The repository source code is MIT licensed.

You can use, copy, fork, modify, self-host, and redistribute the local Unlimited Skills core without registering:

- router skill;
- installers and migration scripts;
- local skill library;
- lexical search;
- optional local Chroma vector index;
- local daemon;
- local learning logs;
- bundled base packs that are shipped in this repository.

Registration is not required for local or offline usage.

## Registered Hosted Services

Registration is required for official hosted services:

- hosted adapted-skill catalog;
- adapted collection update stream;
- registered local skill enhancement scripts;
- signed hosted collection archives;
- planned team skill sync for encrypted private team packs;
- hosted support and dashboard features;
- future cloud sync, marketplace, team, and enterprise features.

Registered installs store their state in:

```text
~/.unlimited-skills/registration.json
```

The file contains the local install id, the configured service URL, the service plan, the hosted-service token, and telemetry preference.

## Plans

Planned service tiers:

- **Community Core**: MIT local core, no hosted-service registration required.
- **Registered Community**: free registration key for hosted catalog and collection updates.
- **Team Free**: planned free team license for up to 10 registered team instances.
- **Pro / Team**: paid hosted workflow, dashboard, larger team sync, and collaboration features.
- **Enterprise**: private registry, private update channel, custom security terms, and support.

The exact hosted-service terms can change independently from the MIT source license. See [../SERVICE-TERMS.md](../SERVICE-TERMS.md).

## CLI

Register an installation:

```bash
unlimited-skills register --key "$UNLIMITED_SKILLS_REGISTRATION_KEY" --agent codex
```

Check license status:

```bash
unlimited-skills license status
```

Check hosted collection updates:

```bash
unlimited-skills catalog list
unlimited-skills updates check
```

Download and run the registered local enhancer:

```bash
unlimited-skills enhance download
unlimited-skills enhance run
unlimited-skills enhance run --apply
```

Without registration, local skills remain "as is". With registration, the client can download the official local enhancement script from the registry. The script runs locally and is checksum-verified before use.

Apply hosted collection updates:

```bash
unlimited-skills updates apply
```

Hosted catalog, update, and enhancement-script commands fail when the installation is not registered. Local commands such as `search`, `list`, `view`, `reindex`, `adapt`, and installer migrations continue to work without registration.
