# A0 Skill Invocation Rescue — Baseline Diagnosis Report

Date: 2026-06-12
Scope: why Unlimited Skills is underinvoked in normal agent use.
Evidence sources (read-only): a live install's library `~/.unlimited-skills/library/.learning/events.jsonl` (167 events), the live router skill `~/.claude/skills/unlimited-skills/`, the global `~/.claude/CLAUDE.md`, `~/.claude/settings.json`, Claude Code transcripts (13 main sessions + 99 subagent transcripts, Jun 10–12), a fresh clone with a populated test root (267 skills).

This is the frozen baseline behind the A0 fixes (`suggest` probe, rewritten router contract, hook delivery, and the effectiveness regression standard in [skill-effectiveness-standard.md](skill-effectiveness-standard.md)).

---

## 1. Baseline measurement

### 1.1 Raw event counts (live events.jsonl)

| Metric | Value |
| --- | --- |
| Total events | 167 |
| Timespan | 2026-06-06 08:26 → 2026-06-12 06:45 (7 calendar days) |
| `search` | 83 (+1 `daemon_search`) |
| `view` | 33 |
| `skill_used` | 34 |
| `list` | 16 |
| Zero-hit searches | **0 of 84** (retrieval never came back empty) |

### 1.2 The shape of the curve is the headline

| Day | Events | skill_used |
| --- | --- | --- |
| Jun 6 | 60 | 17 |
| Jun 7 | 21 | 6 |
| Jun 8 | 57 | 11 |
| Jun 9 | 8 | **0** |
| Jun 10 | 10 | **0** |
| Jun 11 | 7 | **0** |
| Jun 12 | 4 | **0** |

83% of all events (138/167) happened Jun 6–8 — the dogfooding burst where the agent was *building Unlimited Skills itself* (queries: "registration update channel hosted catalog", "Local Skill Hub runtime MVP", "registry contract design signed bundle"). **Every single `skill_used` event (34/34) is from that burst. Since Jun 8 the full loop (search → view → use) has executed zero times.** Post-Jun 8: 21 searches, 3 views, 0 uses — and most of those searches are again from sessions auditing/developing unlimited-skills itself ("schema consolidation shared DDL sqlite refactor", "operator acceptance suite", "threat model abuse case").

### 1.3 Session-side denominator (Claude Code transcripts, Jun 10–12)

Counted actual `Bash`/`PowerShell` tool_use invocations of the launcher per main session:

| Session class | Sessions | Sessions with >=1 real launcher call |
| --- | --- | --- |
| Unlimited-skills dev/maintenance | 4 | 4 |
| Skill-inventory question ("how many skills do you have?") | 1 | 1 (list) |
| Ordinary substantive tasks (knowledge pipeline, git repo setup, project registration, LinkedIn activity, MCP config, browser/remote-control) | 8 | 2 (one search each) |
| **Subagent transcripts** (Task-tool agents) | 99 | **0** |

**Baseline invocation rate on ordinary skill-eligible tasks: ~2/8 sessions ≈ 25% touched search; 0% completed the search → view → use loop.** Excluding self-referential dev sessions, organic adoption is near zero, and subagents — which do most of the heavy lifting — never invoke it at all.

### 1.4 Finding #1: no denominator telemetry

`events.jsonl` only records CLI-side events. There is no record of sessions or tasks that *did not* search — no session id, no agent id, no task tag on `search` events. The invocation rate above had to be reconstructed by manually parsing Claude Code transcripts, which are retained only ~3 days and don't cover other agents. **We cannot manage what we don't measure: the system has no built-in way to compute its own invocation rate.** This is itself a P0 gap.

---

## 2. Trigger-path autopsy

Chain: global CLAUDE.md block → skill listing → SessionStart hook → router SKILL.md → CLI.

| # | Link | Status | Break reason |
| --- | --- | --- | --- |
| 1 | Global `CLAUDE.md` router block (55 lines, installed) | PRESENT, WEAK | Generic standing instruction ("Before doing substantive work, check whether..."). No concrete trigger conditions, no value framing, no cheap one-liner — the advertised command is a 3-line PowerShell incantation costing 4–10 s. Models notoriously deprioritize generic "always do X first" instructions when the user's request is concrete. Evidence: 6/8 ordinary sessions and 99/99 subagents had the block in context and never called the CLI. |
| 2 | Skill listing (router skill visible in skill list) | PRESENT, INERT | The `unlimited-skills` skill DOES appear in the Claude Code skill list with an "ask this router first" description. But it competes with ~100 other skill entries, and models select skills matching the *task domain*, not meta-skills about skill retrieval. Selection, not visibility, is the failure. |
| 3 | Plugin SessionStart hook | **NOT INSTALLED — double break** | (a) The live installation is the legacy `scripts/install-claude-code` path (skill dir + CLAUDE.md). `settings.json` `enabledPlugins` does not include the unlimited-skills plugin, so no deterministic per-session injection ever fires. (b) Even if it were installed, `session_start.py` gated on `shutil.which("unlimited-skills")` — and the CLI was **not on PATH** on the audited machine (it lives in the install venv, reached only via the rendered launchers). The hook would print the install-nag fallback instead of the router contract. The plugin path and the legacy installer path did not know about each other. |
| 4 | Router `SKILL.md` | OK CONTENT, HEAVY PROTOCOL | When loaded it is reasonable, but it prescribed a 6-step ritual (build query → search → pick → view → `use` log → `feedback`). Steps 5–6 cost extra tool calls with no benefit visible to the model; they have a 0% execution rate since Jun 8, starving the learning loop and corrupting the telemetry (usage is undercounted exactly when adoption is organic). |
| 5 | CLI invocation | WORKS, SLOW | Measured on the live install: `search --mode hybrid` = **9.9 s**, `--mode lexical` = **3.9 s** per call (shell → python startup → sentence-transformers model load per process for hybrid; the vector sidecar embeds the query in-process on every invocation). An experimental warm daemon (`serve`) exists and was used exactly once (Jun 6). 4–10 s for a *speculative* check is above the threshold models (and users) tolerate per-prompt. |
| 6 | Result quality | GOOD RECALL, RANKING NOISE IN LEXICAL | 0/84 live searches returned empty. On the 267-skill test root, 30/30 eval scenarios returned hits. But lexical top-1 was wrong-domain in ~5/30 cases (see §4): `flutter-dart-code-review` outranked `python-patterns` for a Python review query; `healthcare-emr-patterns` topped a TypeScript query (no TS skill existed at all); `prompt-optimizer` never surfaced for a prompt-engineering query. Hybrid mode fixes most of this but costs 10 s. |
| 7 | Quickstart/docs | ONE-SHOT DEMO ONLY | `docs/first-run-setup.md` showed exactly one `search` example; the setup wizard never walks the user/agent through a full "task → suggest → view → apply" loop, so the very first session after install establishes no habit. |

---

## 3. H1–H7 verdicts

| Hyp | Claim | Verdict | Evidence |
| --- | --- | --- | --- |
| H1 | Weak router instructions in CLAUDE.md | **CONFIRMED — root cause #2** | Block present in context of all 13 sessions; ordinary-task invocation still ~25%, subagents 0%. Instruction was generic ("before substantive work"), command was a 3-line 4–10 s incantation, no trigger taxonomy, no value proof. |
| H2 | Skill listing not reaching model context | REFUTED (narrowly) | The router skill IS in the visible skill list with a strong description. The listing reaches context; models simply don't pick a meta-skill when a concrete task is in front of them. The *real* listing problem: 100+ competing skill entries dilute it. |
| H3 | No hook/reminder triggering checks | **CONFIRMED — root cause #1** | No hooks at all in the live settings. The plugin that carries the SessionStart hook was not enabled. Even if enabled, the hook's `shutil.which` PATH check failed on the audited machine (CLI not on PATH) and degraded to an install nag. Zero deterministic per-session or per-prompt reinforcement existed in production. |
| H4 | Search friction (slow/awkward CLI) | **CONFIRMED — root cause #3** | Measured: hybrid 9.9 s, lexical 3.9 s per call; each call re-spawned shell+python and (hybrid) reloaded the embedding model. The documented command was 150+ characters. A speculative check this expensive loses to "just do the task" every time. Warm daemon exists but was experimental and unused. |
| H5 | Models don't know WHEN a task is skill-eligible | CONFIRMED | "Before substantive work" gives no decision procedure. Transcript evidence: knowledge-pipeline ops, git repo setup, outreach — all eligible (library has knowledge-ops, git-workflow, social-publisher), all skipped. Conversely the only ordinary sessions that searched were ones whose task *named* a domain. |
| H6 | Empty/irrelevant first results killing trust | PARTIAL | Empty results: never (0/84 live, 30/30 eval). Irrelevant top-1: real in lexical mode (~5/30 eval scenarios got a wrong-ecosystem top hit). Live sessions mostly used hybrid (good hits), so trust-killing was secondary — but once the speed fix pushes the default to lexical, ranking noise becomes primary. Hence the ecosystem ranking guard. |
| H7 | Quickstart never demonstrates "search skills first" | CONFIRMED | One isolated search example in first-run docs; the wizard ended at indexing. No demonstrated retrieval loop, no first-session habit formation. |

---

## 4. Skill-eligibility scenario eval set (30 scenarios)

Run against the populated test root (267 skills, the bundled `ecc` + `superpowers` packs) with lexical search, top-3, BEFORE the A0 fixes. "Top hit" = actual #1 at the time of diagnosis. STATUS: OK = relevant top-1; RANK = relevant skill exists but outranked by noise; GAP = no relevant skill in this root.

| # | Scenario (task an agent would face) | Query | Top hit (score) | Status / ideal invocation |
| --- | --- | --- | --- | --- |
| S1 | Debug an intermittently failing test | debug intermittent failing test root cause | test-driven-development (14) | OK; ideal also surfaces e2e-testing flaky strategies (#3) |
| S2 | Review a teammate's PR | code review checklist pull request | flutter-dart-code-review (24) | RANK — `requesting-code-review`/`receiving-code-review` tie at 24/20; wrong-ecosystem skill wins the tiebreak |
| S3 | Write unit tests for new module | write unit tests coverage | cpp-testing (10) | RANK — language-agnostic tdd-workflow at #3; needs language signal in query or ranking |
| S4 | Set up a git branching workflow | git branch merge rebase workflow | git-workflow (29) | OK |
| S5 | Open a PR with a good description | create pull request description | code-tour (7) | RANK/GAP — `github-ops` exists but doesn't surface; low scores all around |
| S6 | Security review before release | security review secrets injection auth | security-review (22) | OK |
| S7 | Refactor a large module safely | refactor large module safely | hexagonal-architecture (5) | RANK — weak scores; safe-refactoring content exists in tdd/plankton skills but doesn't surface |
| S8 | Design a REST API | REST API design pagination versioning | api-design (32) | OK |
| S9 | Plan a database migration | database schema migration rollback | database-migrations (19) | OK |
| S10 | Fix React re-render performance | React rerender performance optimization | react-performance (51) | OK (best-in-class) |
| S11 | Design a landing page | landing page design UI | frontend-design-direction (19) | OK |
| S12 | Write a README / tech docs | write technical documentation README | documentation-lookup (8) | RANK — article-writing #2; no dedicated docs-authoring skill |
| S13 | Deep research with citations | deep research literature sources synthesis | deep-research (22) | OK |
| S14 | Scrape a website | scrape website browser automation | browser-qa (14) | OK-ish — data-scraper-agent is the ideal; appears in top-3 |
| S15 | Fix failing CI pipeline | CI pipeline github actions build failure | github-ops (15) | OK |
| S16 | Containerize and deploy | docker container deployment | deployment-patterns (14) | OK |
| S17 | Add robust error handling | error handling exceptions retry patterns | error-handling (25) | OK |
| S18 | Add logging/observability | logging metrics observability tracing | enterprise-agent-ops (5) | GAP — no observability skill; scores ≤5 (should be below a suggest-threshold) |
| S19 | Profile slow code | performance profiling slow code optimization | react-performance (19) | RANK — React skill hijacks generic perf query; benchmark-optimization-loop is the generic ideal |
| S20 | Optimize a SQL query | SQL query optimization index | benchmark-optimization-loop (10) | RANK — postgres-patterns/mysql-patterns at #4-5 |
| S21 | Python code review | python idiomatic code review pep8 | flutter-dart-code-review (20) | RANK — python-patterns at #5 behind three wrong-language review skills |
| S22 | TypeScript type-safety patterns | typescript type safety patterns | healthcare-emr-patterns (16) | GAP — zero typescript-* skills in this 267-pack root; top-1 is pure noise |
| S23 | Write launch marketing copy | marketing landing copy launch announcement | marketing-campaign (19) | OK |
| S24 | Cold email outreach sequence | cold email outreach sequence | investor-outreach (15) | OK-ish — closest existing skill; content-engine also relevant |
| S25 | Break a feature into an implementation plan | implementation plan feature breakdown | plan-orchestrate (12) | OK |
| S26 | Fix a bug with a regression test first | fix bug regression test first | ai-regression-testing (17) | OK |
| S27 | Write release notes / changelog | release notes changelog versioning | github-ops (6) | RANK/GAP — opensource-pipeline exists (used successfully Jun 6) but doesn't surface |
| S28 | Clean a messy CSV/spreadsheet | spreadsheet csv data cleaning | data-scraper-agent (10) | GAP — no spreadsheet skill in root (Claude Code native xlsx covers it; suggest should defer) |
| S29 | Improve an agent prompt | prompt engineering LLM agent instructions | llm-trading-agent-security (19) | RANK — prompt-optimizer exists, never surfaces in top-5 |
| S30 | Build an n8n automation | n8n workflow automation webhook | automation-audit-ops (15) | OK-ish — live library's n8n collection is the ideal; test root has partial coverage |

**Summary: 30/30 return results; 17 OK, 9 RANK (relevant skill exists but loses to wrong-ecosystem noise), 4 GAP.** Library coverage is NOT the bottleneck — ranking and (above all) the trigger path are. This table is the frozen eval set for measuring fixes (now machine-readable in `evals/invocation-scenarios.json`, extended with explicit negative scenarios): a fix run = replay all queries, score top-3 relevance + measure end-to-end latency.

---

## 5. Proposed fixes, ranked by expected invocation-rate impact

### F1. `unlimited-skills suggest "<task>"` — a sub-1.5 s always-cheap probe (Effort: M, Risk: low) — IMPACT: HIGH — **SHIPPED**
One command, lexical-only (no embedding-model load), returns top-3 as one-liners with a score floor (suppress hits below the floor to avoid S18/S22-style noise), prints nothing ("no relevant skill") when below floor so the model can move on guilt-free. Measured budget existed: in-process lexical averaged ~340 ms/query on 267 skills — the 3.9 s observed cost was process+launcher startup, so the shipped implementation routes `suggest` through an import-cheap module (`unlimited_skills/suggest.py` + `unlimited_skills/__main__.py` fast dispatch) that skips native sync and the heavy CLI import graph. Everything else (F2–F4) becomes viable only once the probe is this cheap.

### F2. Rewrite the global CLAUDE.md router block (Effort: S, Risk: low) — IMPACT: HIGH — **SHIPPED**
Replace the vague "before substantive work, check" with: (a) a concrete trigger taxonomy, (b) ONE one-line command, (c) value framing, (d) an explicit skip rule so the instruction stays credible. The shipped contract (see any installer or `plugin/skills/unlimited-skills/SKILL.md`):

- value framing: "A 1-second lookup often replaces 20 minutes of rediscovery";
- ONE command: `<launcher> suggest "<task in 3-8 keywords>"`;
- TRIGGERS: code in a named language/framework; review/audit/security; tests/bugs/debugging; git/GitHub; prose; planning/refactoring/migrations/deployments/ops; user names a skill or asks "what can you do";
- ACT rule: view a relevant hit; silence means proceed, no synonym re-searching;
- SKIP rule: only when a relevant skill is already active in context.

### F3. Ship the hook path for the live install (Effort: M, Risk: medium) — IMPACT: HIGH (determinism) — **SHIPPED**
Two layers:
- **SessionStart** (existed in plugin, broken live): `session_start.py` now resolves the CLI via a fallback chain — env override → PATH → `~/.unlimited-skills/.venv` → rendered launchers — instead of `shutil.which` only. The legacy installer ALSO registers the hooks in `~/.claude/settings.json` (idempotent, fail-soft, `--no-hooks` to opt out), so both install paths converge on deterministic injection.
- **UserPromptSubmit** (new, the big lever): a hook that runs `suggest` on the user's prompt text and, only when a hit clears the score floor, injects one line: `Relevant skill available: <name> — <description> View it with: ...`. This converts invocation from model-initiative (unreliable) to ambient retrieval (deterministic). Hard 3 s timeout, fail-open silent on any error.

### F4. Collapse the protocol: drop mandatory `use`/`feedback` steps (Effort: S, Risk: low) — IMPACT: MEDIUM — **PARTIAL**
The rewritten router workflow marks `use`/`feedback` as optional enrichment ("helpful, never required"). Auto-logging `view` as presumptive usage remains future work.

### F5. Telemetry for the denominator (Effort: M, Risk: low) — IMPACT: MEDIUM — NOT YET
Add `session_id` + `agent` + optional `task` fields to every event; SessionStart writes a beacon. Then invocation rate = sessions with ≥1 search / sessions with beacon, computable from events.jsonl alone. (`suggest` already logs a `suggest` event with latency.)

### F6. Lexical ranking guard for wrong-ecosystem hits (Effort: M, Risk: medium) — IMPACT: MEDIUM — **SHIPPED**
Evidence: S2/S21/S22/S19. The shipped guard (`unlimited_skills/search_core.py`): if the query names a language/framework ecosystem and a skill names a *different* one, the score is multiplied by 0.4; ecosystem-specific skills on ecosystem-neutral queries get a mild 0.8. Plus a stopword filter (function words no longer inflate scores on natural-language prompts — critical for the UserPromptSubmit hook) and plural/singular query expansions.

### F7. Quickstart demonstrates the loop (Effort: S, Risk: none) — IMPACT: LOW-MEDIUM — **SHIPPED (docs)**
`docs/first-run-setup.md` now ends with one completed suggest → view loop.

### F8. Fill the eval-set gaps in default packs (Effort: S, Risk: none) — IMPACT: LOW — NOT YET
S18 (observability), S29 (prompt-optimizer has a broken empty `description:` in its frontmatter, so it cannot surface), S27 (release-notes), S5 (PR descriptions). Keeps `suggest` from staying silent on common tasks.

**Shipped order: F1 → F2 (+F7) → F3 → F6, plus the regression standard. Next: F5, F8.**

## 6. Target metric: >=70% invocation on skill-eligible tasks

**Skill-eligible task** = a user prompt (or subagent task) matching the F2 trigger taxonomy, operationalized as the categories of the §4 eval set (code-write, code-review, testing, debugging, git/PR, security, refactor/migration, deploy/ops, docs/prose, research, marketing/outreach, planning). Classification: for offline evals, the frozen scenario set; for live measurement, a weekly sample of session beacons' first-prompt text hand-labeled (or labeled by a cheap classifier) against the taxonomy.

**Invoked** = ≥1 `search`/`suggest` event in that session, with a query lexically related to the task (anti-gaming guard for evals). **Converted** = a `view` event follows a search in-session.

**Measurement** (all from events.jsonl once F5 lands):
- `invocation_rate = eligible sessions with >=1 search / eligible sessions` — **target >= 0.70** (baseline ~0.25 main sessions, ~0.0 subagents)
- `conversion_rate = sessions with view after search / sessions with search` — target >= 0.40 (post-Jun-8 baseline: 3/21 ≈ 0.14)
- `suggest_latency_p90 < 1.5 s` (baseline: 3.9–9.9 s; shipped: ~0.45 s direct, ~0.8 s through the PowerShell launcher)
- Offline regression: `scripts/check-skill-effectiveness.py` per the cadence in [skill-effectiveness-standard.md](skill-effectiveness-standard.md).

Review cadence: weekly cut of events.jsonl; fix is accepted when two consecutive weeks hold invocation_rate >= 0.70 across >= 20 eligible sessions including subagents.
