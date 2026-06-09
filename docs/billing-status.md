# Billing Status Diagnostics

`unlimited-skills billing` shows the registered installation's billing lifecycle state without enabling live payments in the public client.

Commands:

```bash
unlimited-skills billing status
unlimited-skills billing status --json
unlimited-skills billing refresh
unlimited-skills billing doctor
```

`billing status` is cache-only and performs no network call. `billing refresh` requires registration and posts a minimal request to `/v1/hub/billing-status` through the existing device proof flow.

The public client treats this as sandbox lifecycle visibility only. It does not create checkout sessions, open payment links, collect card data, store bank data, or forward hosted payment provider payloads.

Supported lifecycle states:

- `none`
- `trialing`
- `active`
- `past_due`
- `canceled`
- `suspended`
- `expired`
- `unknown`

Supported denial reasons:

- `unregistered`
- `no_entitlement`
- `plan_limit_exceeded`
- `past_due`
- `suspended`
- `expired`
- `policy_denied`
- `service_unavailable`

The billing diagnostic cache is stored under the Unlimited Skills home directory and is safe to include in support bundles after redaction. It must not contain registration tokens, device proofs, private keys, checkout URLs, payment links, invoices, card or bank data, local paths, private pack bodies, private skill names, or skill bodies.

Examples:

- `examples/billing/billing-status-active.example.json`
- `examples/billing/billing-status-past-due.example.json`
- `examples/billing/billing-status-suspended.example.json`

Schema:

- `schemas/billing-status.schema.json`
