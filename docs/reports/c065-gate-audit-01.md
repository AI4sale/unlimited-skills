# C065-GATE-AUDIT-01: zero-candidate hook delivery audit

Status: audit evidence only; this does not implement the repair.

## Reproduction

Selected public baseline: `v0.6.4.post1` plus the C065 audit branch.

Real installed-library probe:

```powershell
python -m unlimited_skills --root "$env:USERPROFILE\.codex\.unlimited-skills\library" suggest "<Russian: write a LinkedIn post>" --json --card --limit 1
```

The concrete prompt used by the regression test is:

```text
\u043d\u0430\u043f\u0438\u0448\u0438 \u043f\u043e\u0441\u0442 \u0434\u043b\u044f \u043b\u0438\u043d\u043a\u0435\u0434\u0438\u043d
```

Observed:

```json
{
  "top_3_skill_candidates": [],
  "reason_code": "below_floor",
  "retrieval_path": "none",
  "needs_english_query": true,
  "delivery_tier": 1
}
```

Equivalent English retrieval query against the same installed library:

```powershell
python -m unlimited_skills --root "$env:USERPROFILE\.codex\.unlimited-skills\library" suggest "linkedin social content post marketing" --json --card --limit 3
```

Observed candidates:

```json
[
  {"name": "marketing-campaign", "source": "ecc", "score": 19.0},
  {"name": "social-publisher", "source": "ecc", "score": 19.0},
  {"name": "content-engine", "source": "ecc", "score": 18.0}
]
```

The library is not empty and the expected LinkedIn/social/content/post/marketing family exists.

## Failing regression spec

`tests/test_c065_gate_audit_01.py` adds two strict xfail tests:

- `test_suggest_should_not_return_zero_when_retrieval_family_exists`
- `test_user_prompt_submit_should_deliver_candidates_when_retrieval_family_exists`

Normal pytest keeps the suite green while documenting the known failure. To prove the current failure, run:

```powershell
python -m pytest tests/test_c065_gate_audit_01.py --runxfail -q
```

The direct hybrid retrieval fixture passes and proves the candidate family exists. The `suggest` and `UserPromptSubmit` assertions fail because the candidates are not delivered to the model.

## Gates responsible

- Mode gate: `UserPromptSubmit` shells out to `suggest`, not `search --mode hybrid`; `suggest` has no `--mode` or `--require-vector` option.
- Language gate: raw non-English text enters the lexical scorer first; without an in-budget vector result, the path becomes `retrieval_path=none`.
- Floor gate: `suggest` suppresses all hits below `DEFAULT_FLOOR=12.0`, returning `reason_code=below_floor`.
- Limit gate: the hook hardcodes `--limit 1`, so it cannot deliver the required three-candidate family even if the probe finds multiple hits.
- Tier gate: no candidates means `delivery_tier=1`; the hook emits either no output or a non-English re-query instruction, not candidate names.
- Tier silence: English no-match remains intentionally silent, so any repair must distinguish true empty/no-match from non-empty retrieval available elsewhere.

## C065 invariant

In a non-empty skill library, `UserPromptSubmit` must not inject zero candidates when any supported retrieval path returns candidates. Zero candidates are acceptable only for an empty library, command error or timeout with explicit diagnostic, user-disabled inject, or an explicit collection filter that has no skills.
