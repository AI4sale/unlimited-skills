# Implementation plan: replace the "Pro / Team: planned paid ..." README wording (A2 follow-up)

Status: **recipe only — do not execute until PR #121 (README repositioning)
has merged.** This document records the exact edit and the full verifier/test
impact scan so the change is a 5-minute mechanical PR when it lands.

## The edit

`README.md` line 198 (on `main` at the time of writing, inside the
"Product Editions" bullet list) currently reads:

```text
- **Pro / Team**: planned paid hosted collaboration, dashboard, private packs, collection assignment, longer auto-approval windows, and support. The public client includes registered private-pack install/sync commands; registry-side access requires private-pack entitlement or a Business/Enterprise plan.
```

Replace the entire line with:

```text
- **Pro / Team**: Team/hosted features are not available for sale. They remain future research until user demand and product gates justify them.
```

The required sentence is exactly: "Team/hosted features are not available
for sale. They remain future research until user demand and product gates
justify them." The `- **Pro / Team**:` bullet prefix is kept only so the
"Product Editions" list stays structurally intact; if #121 dissolves that
list, the bare two sentences replace the line wherever the old claim ended
up.

Note: PR #121 repositions the README, so the line number and surrounding
section may differ after the merge. Find the line by its unique phrase
`planned paid hosted collaboration` (it occurs nowhere else in the repo).

## Verifier/test impact scan (performed against `main`, 2026-06-12)

Method: extracted every quoted string literal (10+ chars) from all
`scripts/verify-*.py` and `tests/**/*.py` files and intersected them with
the old line's text; then checked, for each hit, whether the phrase
survives elsewhere in the document set that the check actually reads.

### Result: NO verifier or test pins the old wording in a way this edit breaks. Zero verifier edits required.

The three literal overlaps found, and why each one stays green:

| File:line | Pinned phrase | Why the edit does not break it |
| --- | --- | --- |
| `scripts/verify-v0.3.2-alpha-private-packs.py:155` | `"private-pack entitlement"` | Required in the **concatenation** of its `PUBLIC_DOCS` list (README + SECURITY.md + CHANGELOG.md + docs/known-limitations.md + docs/private-team-packs.md + ...). The phrase survives in `docs/private-team-packs.md` (lines 7 and 50) and `docs/releases/v0.3.2-alpha.md:36` after the README line is replaced. |
| `scripts/verify-v0.3.2-alpha-private-packs.py:156` | `"business/enterprise plan"` (lowercased check) | Same concatenated check. Survives in `docs/private-team-packs.md` (2x), `SECURITY.md:71`, `docs/known-limitations.md:22`, `CHANGELOG.md:352`, `docs/releases/v0.3.2-alpha.md`, `docs/releases/v0.3.2-alpha-upgrade-notes.md`. |
| `scripts/verify-v0.4-readiness-rfc.py:27` | `"private packs"` | Required in the concatenation of its `REQUIRED_DOCS` (README + CHANGELOG + known-limitations + the v0.4 audit/RFC docs). Survives in `docs/releases/v0.4-readiness-audit.md` (3x), `docs/rfcs/v0.4-skillops-platform-rfc.md`, `docs/rfcs/v0.4-risk-register.md`, and `CHANGELOG.md`. |

### Named verifiers explicitly checked (no pin on the old wording)

- `scripts/verify-v0.3.1-alpha-publication.py` — pins release-manifest
  fields, PR numbers, reconciliation counts, and distribution booleans; no
  Product Editions wording. Not affected.
- `scripts/verify-v042-alpha-mcp.py` — pins MCP wording only
  (`"unlimited-skills mcp serve"`, `"no oauth"`, `"may break before v0.6"`,
  etc., lines 113–140). Not affected.
- `scripts/verify-v04-cross-repo-readiness.py` — pins the phrase
  `"v0.4 cross-repo readiness"` **in README.md specifically** (line 135).
  Not affected by this edit, but see the adjacent-risk note below.
- `scripts/verify-v040-alpha-e01-e04.py` — pins
  `"v0.4.0-alpha E01-E04 integration"` in README.md (line 174). Not
  affected by this edit; adjacent risk below.
- `scripts/verify-v04-go-no-go.py` — pins `"v0.4 go/no-go"` in README.md
  (line 144). Not affected by this edit; adjacent risk below.
- `tests/` — `tests/test_public_alpha_docs.py` scans README + all docs for
  forbidden claims (the archive-signing phrase and the retired 0.1.0
  version string) and required security wording; the new sentence contains
  none of the scanned phrases.
  `tests/smoke/test_v02x_release_smoke.py::test_docs_security_claims_are_consistent`
  pins security wording unrelated to editions. `tests/test_private_packs.py`
  pins JSON keys (`"planned"` as a sync-report field), not README prose.
  `tests/test_install_path_docs.py` is about the pip command only. No test
  pins `Pro / Team`, `planned paid`, or any fragment unique to the old line.

### Forbidden-phrase scans checked against the NEW wording

The new sentence ("not available for sale", "future research") was checked
against every `FORBIDDEN_PHRASES`/forbidden list in `scripts/verify-*.py`
and the doc-scanning tests: no list contains any substring of it. The new
wording also cannot trip the private-material regex scans (no key/token
shapes).

## Adjacent risks (for the PR that lands this, not edits in this doc's scope)

1. **PR #121 interaction.** Three verifiers pin README-specific phrases
   (`"v0.4 cross-repo readiness"`, `"v0.4.0-alpha E01-E04 integration"`,
   `"v0.4 go/no-go"`). If #121's repositioning dropped those lines, those
   verifiers are already red on the #121 branch independently of this edit.
   Rebase this edit on top of the merged #121 README and re-run the
   verifier suite before concluding anything about this change.
2. **Other docs keep the paid-tier framing.** `docs/registration-and-licensing.md:61`
   ("**Pro / Team**: paid hosted workflow, ..."), `docs/product-editions.md`
   (the edition table the README links to), and
   `docs/hosted-catalog-model.md:22` carry sibling wording. They are NOT in
   scope of the A2 line replacement, but the README will then contradict
   `docs/product-editions.md` one click away. Recommend a follow-up pass
   aligning those files with the same not-for-sale sentence.
3. **CHANGELOG is exempt by convention.** Historical release notes quoting
   the old positioning stay untouched (same convention as the install-path
   guard's CHANGELOG exemption).

## Execution checklist (when #121 has merged)

1. `git grep -n "planned paid hosted collaboration"` — exactly one hit, in
   README.md; apply the replacement line above.
2. No verifier or test edits (per the scan above).
3. Run: `python -m pytest tests/test_public_alpha_docs.py tests/test_install_path_docs.py -q`,
   then the full suite, then
   `python scripts/verify-v0.3.2-alpha-private-packs.py` and
   `python scripts/verify-v0.4-readiness-rfc.py` as the two checks whose
   phrase sets overlap the old line.
4. Re-grep: `git grep -ni "planned paid"` must return only CHANGELOG/release
   history hits.
