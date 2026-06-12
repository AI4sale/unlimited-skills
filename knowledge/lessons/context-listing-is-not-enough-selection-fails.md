# Lesson: having the instruction in context is not enough — selection fails

- **date:** 2026-06-12
- **status:** active; transferable beyond this project

## Why

The leading hypothesis for zero skill invocation was that the router
instruction simply was not reaching the model's context (H2: "the listing is
missing"). If true, the fix would be delivery. It was false — and that
changes what kind of fix actually works.

## Evidence

The A0 diagnosis (`docs/adoption/a0-invocation-diagnosis.md`) refuted H2: the
router block WAS present in context in sessions where invocation still did
not happen. The failure sits at the *selection* step — at decision time the
model does not choose to pay an uncosted multi-second detour for an uncertain
reward, especially mid-task. A generic "consider checking the library"
instruction loses to task momentum almost every time.

## Changed state

A0 attacks selection, not delivery: the probe became cheap and deterministic
(`suggest`, sub-second, silence below a score floor), the instruction states
its cost and its payoff explicitly, hooks remove the decision entirely
(ambient hint), and at high confidence the skill card is injected so there is
no detour left to decline. Result: invocation becomes infrastructure.

## Next rule

When a model "ignores" an instruction that is verifiably in context, treat it
as an economics problem, not a prompting problem: cut the action's cost below
one second, make its expected value explicit, or remove the choice via
infrastructure (hooks/injection). Re-wording the instruction alone is the
weakest available move and must not be the only fix shipped.
