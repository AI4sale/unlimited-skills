# Compatibility

Unlimited Skills is still pre-1.0, but the v0.6 adoption cycle freezes the
public contracts that people are already scripting against.

## Stability Levels

| Level | Meaning |
| --- | --- |
| Stable public-alpha | Documented shape and privacy boundary are preserved through v0.7. Optional fields may be added; documented fields must not be removed or repurposed. |
| Preview | Useful but still settling. The privacy boundary and local-first failure mode are preserved; output details may tighten. |
| Alpha/internal | May change before 1.0. Do not build automation against it unless a release gate explicitly freezes it. |
| Parked | Present in a PR or design thread but not accepted into public mainline behavior. |

## v0.6 Freeze Promise Through v0.7

The following surfaces are stable public-alpha contracts through v0.7:

- `unlimited-skills --version`;
- `unlimited-skills quickstart`;
- `unlimited-skills suggest`;
- `unlimited-skills mcp savings`;
- `unlimited-skills mcp install --claude-code`;
- `unlimited-skills feedback prepare`;
- `unlimited-skills learning-summary --events`;
- `unlimited-skills roi receipt`;
- `scripts/generate-public-alpha-signal-rollup.py`;
- local event privacy behavior after `v0.5.3-alpha`;
- feedback report schema;
- ROI receipt schema;
- PyPI Trusted Publishing and post-publish verification expectations.

The detailed command shapes live in [cli-contracts.md](cli-contracts.md). The
release-level freeze lives in
[releases/v0.6-contract-freeze-spec.md](releases/v0.6-contract-freeze-spec.md).
The executable frozen-contract guard is
[scripts/verify-v06-frozen-contracts.py](../scripts/verify-v06-frozen-contracts.py).
Future v0.6.x release promotion uses
`scripts/verify-v060-alpha-publication.py`, which invokes that guard in
prepublish and published modes and blocks publish/tag guidance if the guard
reports drift or a blocked surface.
The v0.6 compliance audit for the actual PyPI package lives in
[releases/v0.6-contract-compliance-audit.md](releases/v0.6-contract-compliance-audit.md).
The release note for the accepted v0.6 alpha lives in
[releases/v0.6.1-alpha.md](releases/v0.6.1-alpha.md). The owner decision packet
for the uploaded-but-not-released `0.6.0` artifact lives in
[releases/v0.6.0-uploaded-not-released-incident.md](releases/v0.6.0-uploaded-not-released-incident.md).

`v0.6.1-alpha` is the valid v0.6 alpha release. Install or upgrade to
`unlimited-skills==0.6.1` or newer. The `0.6.0` package was uploaded to PyPI
but was not tagged or released because the published verifier failed after
upload.

## What Can Still Break Before 1.0

Before 1.0, the project may still change:

- ranking and score internals;
- human-readable text wording;
- optional JSON fields;
- file names for private or internal diagnostics;
- docs tooling fixture values;
- private registry, hosted catalog, team, enterprise, marketplace, and policy
  implementation details that are not part of the v0.6 freeze;
- #119/E19 behavior, because #119 remains parked until explicitly reopened.

Breaking a stable public-alpha field before v0.7 requires an explicit
compatibility note, migration note, and test update in the same PR.

## Non-Claims

Compatibility does not mean hosted service readiness, team readiness,
enterprise readiness, marketplace acceptance, paid support, payment handling,
or a delivery commitment. It only documents what the local public core and
release gates are expected to keep stable.
