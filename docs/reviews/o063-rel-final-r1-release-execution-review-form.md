# O063-REL-FINAL-R1 — v0.6.3 Release-Execution Review Form (pre-built)

**Reviewer:** Opus. **Status:** review template (no code). **Fires on:** Codex's
v0.6.3 **release-execution PR (C063-REL-02)**. Pre-built per Hermes ("if Codex stalls,
Opus may pre-create the final release-review checklist") so the review is instant when
the PR opens. Grade against the *actual* PR; this only fixes the criteria.

**Boundary (hard):** Opus produces a verdict only. **Opus does NOT execute the release**
— tag / PyPI publish / version bump are the release-operator's gated action. A PASS here
authorizes the operator to proceed *if* they choose; it does not perform the release.

**Verdict scale:** `PASS` / `PASS_WITH_FIXES` / `BLOCKED`. One must-have (M) failure ⇒ BLOCKED.
Cite `file:line` / command output for each item.

## Ground truth (verified on main `0d0e477`)
- Current `pyproject.toml` version = **0.6.2**; manifest `package_version` = **0.6.3** →
  the release PR MUST bump `0.6.2 → 0.6.3`.
- Manifest `status` is currently `release_package_draft`, `git.tag_status` =
  `blocked_until_release_execution_gate_owner_approval_publish_and_clean_install_verification`.
- Release notes header currently says: *"Do not tag, version bump, publish, or promote from
  this document alone."* (draft framing — the release PR is what changes this state).
- v0.6.3 VFP = local Learning Loop tier commands; v0.6.2 router-health = **compatibility /
  tier-debt closure only, NOT v0.6.3 VFP** (manifest `value_frame`). Excluded by manifest:
  v0.6.4 Money Saved Meter, hosted telemetry, automatic skill improvement/mutation.

## Form A — Version & metadata consistency

- [ ] **M** `pyproject.toml` version bumped **0.6.2 → 0.6.3** (matches manifest `package_version`).
- [ ] **M** Version is consistent across: `pyproject.toml`, `docs/releases/v0.6.3-alpha.release-manifest.json`,
      `docs/releases/v0.6.3-alpha.md`, changelog, and `__version__` (`unlimited-skills --version` → 0.6.3).
- [ ] **M** Manifest `status` / release-notes "draft" framing is updated to a release-execution
      state (no longer "do not tag/version bump/publish from this document alone" if the PR is the execution step).
- [ ] **S** Changelog/notes entries are dated and list the shipped tier commands, not aspirational items.

## Form B — Command-level VFP evidence (every claimed tier runs)

- [ ] **M** Re-run `python scripts/verify-v063-tier-release-smoke.py --json` → **`ok=true`, 16 surfaces, 0 fails**
      (Free-core learning loop + both full tier ladders + the evidence-pack tamper check).
- [ ] **M** Each manifest `learning_loop_surfaces` tier command actually runs: free (doctor /
      improvement-candidates / apply-candidate --dry-run), registered (`learning export`), team
      (`learning team-rollup`), business (`learning admin-export`), enterprise (`learning
      evidence-pack` + `learning verify-evidence-pack`).
- [ ] **M** Enterprise fail-closed holds: tampering an evidence-pack file → verifier `ok=false` / non-zero exit.
- [ ] **S** v0.6.2 router-health compatibility commands still run (export/team-rollup/admin-export/
      evidence-pack/verify-evidence-pack), framed as compatibility only.

## Form C — Claim integrity (nothing outruns the code)

- [ ] **M** NO v0.6.4 surface claimed (no Money Saved Meter in the v0.6.3 release surface).
- [ ] **M** NO hosted/telemetry/dashboard/SSO/SCIM/governance-enforced/signature-enforced/
      billing claim, and NO automatic-skill-improvement/auto-mutation claim — anywhere in notes/manifest.
- [ ] **M** v0.6.2 router-health is framed as **compatibility/tier-debt closure**, NOT as v0.6.3 VFP.
- [ ] **M** No docs-only "tier" claim: every tier line maps to a runnable command (cross-check vs Form B).
- [ ] **S** `#207` (market-fit) referenced as **claim support**, not as implementation evidence.

## Form D — Gates green (release-readiness)

- [ ] **M** `tests/test_v063_tier_release_smoke.py` + the learning tier tests pass.
- [ ] **M** `scripts/verify-v06-frozen-contracts.py --json`, `scripts/verify-feedback-report-boundaries.py`,
      `scripts/verify-learning-feedback-contract.py`, `scripts/verify-learning-loop-closed-loop-proof.py` pass.
- [ ] **M** Full suite green; `git diff --check`; both smoke-script shims `py_compile` clean
      (hyphen shim imports the right module — re-confirm no #191-style mis-wire).
- [ ] **S** Clean-install / package-build smoke (if included) succeeds and exposes the tier commands.

## Form E — Release-execution boundary

- [ ] **M** The actual tag / PyPI publish / version-bump-commit is gated on **owner/operator approval**;
      the PR does not silently auto-publish.
- [ ] **M** `#195` (v0.6.4 release-readiness) stays HOLD; `#119`/E19 stay parked; no v0.6.4 work rides along.
- [ ] **Opus does NOT execute** — verdict only; the operator performs tag/publish if they approve.

## Reviewer output
One verdict per form + one overall. Any M failure → BLOCKED with the exact file/command.
On PASS, state plainly that the release package is consistent, every tier claim is backed by a
runnable command (smoke `ok=true`), and no claim outruns the code — and that execution remains
the operator's gated action. Post the verdict to the Hermes chat; **Codex merges** the PR; the
**release operator** (not Opus) performs any tag/publish.
