# Decision: adoption arc takes priority over further trust layers

- **date:** 2026-06-12
- **status:** active; governs the road to v0.5

## Why

v0.4.x built a deep trust/distribution stack (signed bundles, trust stores,
permission profiles, audit, threat model) while the entry funnel was broken: a
dead install command, an empty first search, the killer numbers missing from
the README, and a skill-invocation rate near zero. New engineering layers
compound zero adoption into zero value. The project frame was therefore
reset: user value first, adoption first, v0.5 is the first public alpha.

## Evidence

- Fresh-clone new-user audit: `pip install unlimited-skills` returned 404 yet
  was recommended everywhere, including runtime error hints; first search hit
  an empty library while 267 ready skills sat unimported in `packs/`.
- Invocation diagnosis: see `knowledge/product-state/skill-invocation-red-flag.md`.
- Review verdict on the adoption pivot: "A0 blocks v0.5" — no public release
  without a proven invocation funnel.

## Changed state

P0 lane executed and merged: #115 (working install path everywhere, with
`A3-PYPI-FLIP` markers for the future PyPI flip), #117 (A0 invocation rescue),
#118 (A1 golden path: `quickstart` + personal `mcp savings` demo). The
remaining trust/distribution work (E19+) continues as a background merge
train, explicitly not the strategic center.

## Next rule

Before adding a new platform/trust layer, show which adoption-funnel step it
serves (install → first search → first value → daily invocation). v0.5
blockers are funnel blockers: A0, A1, then README/A2 positioning, then A3
PyPI. Public alpha is not a paid launch; no payment links or delivery
promises until product readiness is declared.
