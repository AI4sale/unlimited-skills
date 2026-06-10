# Catalog Feedback

`catalog feedback` sends explicit, redacted quality feedback about one hosted catalog item. It is registration-gated and never runs automatically.

## Commands

```bash
unlimited-skills catalog feedback community:browser-qa-pack:0.1.0 \
  --type install_failure \
  --severity high \
  --title "Install plan unavailable" \
  --error-code install_plan_missing \
  --http-status 404 \
  --dry-run
```

Submit requires explicit confirmation:

```bash
unlimited-skills catalog feedback community:browser-qa-pack:0.1.0 \
  --type install_failure \
  --severity high \
  --yes
```

Status is aggregate-only:

```bash
unlimited-skills catalog feedback-status community:browser-qa-pack:0.1.0 --json
```

## Privacy Boundary

The client rejects obvious private keys, hosted tokens, local paths, repo paths, email addresses, prompt fields, and skill body fields before sending. The server receives only the allowlisted diagnostic fields selected by the user.

The command must not send prompts, task text, skill bodies, local or repo paths, customer data, tokens, device proofs, private keys, archive URLs, checkout URLs, or payment links.
