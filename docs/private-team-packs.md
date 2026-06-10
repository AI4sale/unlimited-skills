# Private Team Packs

Private team packs are registered, team-scoped skill packs served by the hosted Unlimited Skills registry.

The MIT local core still works without registration. Private team pack commands require a registered installation with a license token and device proof.

## Commands

```bash
unlimited-skills private-packs list
unlimited-skills private-packs preview <pack_id>
unlimited-skills private-packs install <pack_id> --yes
unlimited-skills private-packs sync --dry-run
unlimited-skills private-packs sync --yes
unlimited-skills private-packs installed
unlimited-skills private-packs remove <pack_id> --yes
unlimited-skills setup --private-packs
unlimited-skills support bundle --json
```

`sync` is dry-run by default unless `--yes` is passed.

## Local Layout

Installed private team packs are stored under:

```text
<library-root>/
  registry/
    private/
      <pack_id>/
        skills/
          ...
  .unlimited-skills-private-packs.json
```

The metadata file records only registry-owned private packs. `remove` refuses to delete a path unless that pack is marked as registry-owned in local metadata and the target stays under `registry/private/`.

## Security Boundary

The client:

- requires local registration before hosted private-pack calls;
- sends bearer token plus device proof to every private-pack endpoint;
- verifies the signed private team pack manifest before download/install;
- downloads archives only through the registered POST download endpoint;
- checks archive SHA256 before extraction;
- uses safe zip extraction to block path traversal;
- installs only under `registry/private/<pack_id>`;
- lists installed private packs locally without hosted calls.
- exposes only redacted private-pack counters in setup, service diagnostics, doctor, and support bundle output.

Metadata responses must not include private skill bodies, tokens, proofs, join codes, or private keys. The downloaded archive may contain the private team skills and is installed locally only after manifest and SHA verification.

## Trust

Private pack manifests use the same Ed25519 manifest envelope as other hosted registry artifacts, with scope `private-team-pack`.

For local tests or private deployments, provide trusted public keys through:

```bash
export UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS="key-id:base64url-public-key"
```

Production deployments should distribute private-pack public keys through the normal trust-store process before enabling private pack install/sync for users.

## Diagnostics and Support

Private-pack-aware diagnostics are local and redacted by default:

- `unlimited-skills setup --private-packs`;
- `unlimited-skills service status`;
- `unlimited-skills service doctor`;
- `unlimited-skills doctor --json`;
- `unlimited-skills support bundle --json`.

These surfaces include counts and error codes only. They do not include private pack names by default, private skill names, private skill bodies, raw archive URLs, local paths, tokens, device proofs, or private keys. `support bundle --include-private-pack-refs` may include hashed private pack references for support correlation; it still excludes names and contents.
