# Catalog Quality

Catalog quality commands show signed hosted metadata for registered catalog items. They are read-only diagnostics for choosing and supporting skills. In `v0.3.8-alpha`, the cross-repo integration proves fixture/static skill evaluation metadata without automatic telemetry, prompt upload, untrusted script execution, automatic skill rewriting, or auto-publish. In `v0.3.9-alpha`, the catalog quality report also includes a public-safe skill improvement section from the maintainer-controlled remediation workflow.

## Commands

```bash
unlimited-skills catalog quality community:browser-qa-pack:0.1.0
unlimited-skills catalog quality community:browser-qa-pack:0.1.0 --json
unlimited-skills catalog eval-status community:browser-qa-pack:0.1.0
unlimited-skills catalog explain-risk community:browser-qa-pack:0.1.0
unlimited-skills catalog improvement-status community:browser-qa-pack:0.1.0
unlimited-skills catalog known-issues community:browser-qa-pack:0.1.0
unlimited-skills catalog browse --show-quality
unlimited-skills catalog search "browser qa" --show-quality
```

## Registration And Signatures

Hosted quality and evaluation status requires registration. The client verifies signed `catalog-quality-status` and `catalog-eval-status` responses before displaying or enforcing any status.

The public client does not run local evaluations of user content. It does not send prompts, task text, skill bodies, local paths, repo paths, customer data, tokens, device proofs, or private keys.

## Fields

Quality output includes:

- quality grade;
- score band;
- last evaluation timestamp;
- blockers;
- warnings;
- compatibility notes;
- deprecation or retirement status;
- feedback-derived issue categories;
- install-risk summary.

`catalog eval-status` adds the evaluation lifecycle status, optional next evaluation time, and evaluator version.

## Install Risk

`catalog install` checks signed quality status before writing. Hosted blocked, retired, or blocker-bearing items are refused. Items below the recommended quality threshold are allowed only when not blocked, and the dry-run or install result includes a warning.

Local and non-hosted overrides are not introduced here. Existing local policy remains the only source of local override behavior.

## Privacy

Quality diagnostics are metadata-only. The support bundle includes quality summary counts only, not item ids, item names, raw feedback, prompts, skill bodies, local paths, repo paths, customer data, tokens, proofs, or private keys.

Skill improvement status builds on the same boundary for signed remediation metadata. It adds open issue counts, severity summaries, fix status, recommended version/channel, stale-installed-version flags, and deprecation/retirement reasons without exposing skill bodies or local data.

The improvement section is summary metadata only: improvement backlog counts, fixed pending eval status, top issue categories, and maintainer triage state. It does not contain prompts, search queries, private skill bodies, local paths, repo paths, tokens, private keys, or device proofs.
