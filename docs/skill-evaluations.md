# Skill Evaluations

Skill evaluations are safe, deterministic catalog-quality checks. They help catalog maintainers understand quality and compatibility before users install hosted catalog items.

`v0.3.8-alpha` treats evaluations as fixture/static checks:

- no automatic telemetry;
- no prompt or task text upload;
- no customer data;
- no production hosted calls in tests;
- no untrusted script execution;
- no automatic skill rewriting;
- no auto-publish.

The private registry owns evaluation generation. The public client consumes signed quality and evaluation metadata only.

## Public Client Boundary

The public client can display:

- quality grade and score band;
- evaluation status and timestamp;
- blockers and warnings;
- compatibility notes;
- feedback issue categories;
- deprecation or retirement state.

The public client must not display or upload:

- skill bodies;
- prompts or task text;
- local paths or repo paths;
- customer data;
- tokens, proofs, or private keys.

## Install Behavior

Hosted blocked items are refused. Low-score items show signed warnings before install. High-quality approved items can still be installed when normal catalog policy allows it.
