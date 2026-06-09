# First-Run Setup

`unlimited-skills setup` prints a privacy-safe local setup report. It does not upload local skills, prompts, local paths, tokens, device private keys, or private pack bodies.

Commands:

```bash
unlimited-skills setup --registered
unlimited-skills setup --hub
unlimited-skills setup --private-packs
```

`--private-packs` includes registered-service checks automatically because hosted private team packs require registration.

Private-pack setup checks include:

- registration state;
- hosted credential presence marker;
- trusted manifest key availability for `private-team-pack`;
- installed private-pack count;
- revoked count;
- stale count;
- last private-pack error codes.

The setup report does not include private pack names, private skill names, skill bodies, archive URLs, device proofs, raw tokens, private keys, or local filesystem paths.
