# Security Policy

## Supported Version

`v0.1.0-alpha` is a developer preview. Security fixes should target the current `main` branch first.

## Reporting

Report security issues privately before public disclosure.

- Email: security@ai4.sale
- Include affected version or commit, reproduction steps, expected impact, and any logs or archive samples needed to reproduce.

Do not include live credentials, private keys, customer data, or unrelated secrets in reports.

## Local-First Boundary

The MIT core is designed to work offline. Local commands such as `search`, `list`, `view`, `where`, `reindex`, `adapt`, installers, migration scripts, and local learning logs do not require registration.

The hosted registry client must not upload skill bodies, prompts, source code, full local paths, repository paths, customer names, environment variables, tokens, or secrets during catalog, update, enhancement, or team-sync checks.

## Hosted Archives And Enhancers

Current v0.1.0-alpha behavior:

- collection archives are SHA256-verified before extraction;
- zip extraction rejects path traversal;
- local enhancement scripts are SHA256-verified before execution;
- hosted features require a registered installation token.

Known limitation:

- cryptographic signature verification for hosted archive metadata is planned, but the current client enforces checksum verification only.

## Scope

In scope:

- path traversal in archive extraction;
- hosted update or enhancement downloads that bypass checksum verification;
- leakage of local skill contents, prompts, secrets, or full paths through hosted client payloads;
- unsafe installer behavior that overwrites unrelated files outside documented target roots;
- authentication or authorization issues in registered hosted flows.

Out of scope for this public alpha policy:

- social engineering;
- denial-of-service without a practical security impact;
- vulnerabilities in third-party dependencies unless Unlimited Skills uses them in a way that creates additional risk;
- issues requiring already-compromised local administrator/root access without a clear privilege boundary.
