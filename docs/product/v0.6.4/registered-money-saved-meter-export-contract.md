# O064-09 — Registered-tier Money Saved Meter: Export Contract

**Roadmap ref:** `...#v0.6.4`. **Tier:** Registered / Registered Community.
**Status:** build contract (no code). **Blocked:** until **US-063-005 GO**.
**Builds on:** the Free Core live meter (O064-08). This tier adds **one bounded
local artifact**, nothing live or hosted.

## Valuable Final Product
A bounded Registered-tier contract for a **local, future-compatible savings report
export** — a file the user produces locally and could later carry to a hosted
catalog/value view, **without** implying live hosted analytics or any automatic
upload in v0.6.4.

## 1. What Registered adds (and only this)
- A **local export command** that writes a schema-versioned savings report file
  (e.g. `savings-export-v1.json`) from the same safe aggregates the Free meter uses.
- The export is **produced locally and stays local** — there is **no submit/sync/
  upload verb** in v0.6.4.

## 2. Schema contract (future-compatible)
- Top-level `schema_version` (e.g. `"v1"`) so a future hosted catalog can ingest it.
- Body = the Free meter's safe aggregate fields: `calls_in_window`,
  `schema_bytes_avoided` (measured), `est_tokens_avoided` (estimated, `bytes // 4`),
  `gateway_standing_bytes`, coarse `window_*_bucket`.
- A `privacy` block with all-false upload/telemetry flags.
- **No** `install_id` / machine id embedded; same safe-field set as Free.

## 3. Privacy contract (same fail-closed gate as Free)
- Runs `assert_meter_safe` before write; suppresses/aborts the export on any
  forbidden field rather than writing a partially-redacted file.
- No server names, paths, prompts, skill bodies, tokens/keys in the export.

## 4. Claim boundary
- Allowed: "local export, future-compatible; **no upload in v0.6.4**."
- Forbidden: any wording implying the export is uploaded, synced, or feeds a live
  hosted dashboard now; any exact-dollar or exact-token claim.

## 5. Backward compatibility
- Additive: the export reads existing aggregates; it does not change `mcp savings`,
  ROI receipt, or the Free meter behaviour.

## 6. Acceptance
- Export file validates against the documented `schema_version` shape.
- Privacy-grep on the export file: no real paths/servers/keys (T9/T15 analog).
- "No submit verb" test: the Registered surface exposes no network action.
- Dollars off by default (T6 analog).

## 7. Explicitly NOT in Registered (v0.6.4)
No hosted submission/sync, no live dashboard, no account-bound analytics, no
automatic dollars, no telemetry.

---

### Evidence summary
- **VFP:** one local, schema-versioned, future-compatible savings export — no upload.
- **Privacy:** same fail-closed gate + safe fields as Free; no install/machine id.
- **Claim:** "local export, future-compatible; no upload in v0.6.4."
