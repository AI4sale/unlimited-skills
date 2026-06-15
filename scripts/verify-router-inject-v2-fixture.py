#!/usr/bin/env python3
"""Verify the Router Inject v2 100-step guidance fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "fixtures" / "router-inject-v2" / "100-step-phases.json"


def load_fixture(path: Path = FIXTURE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify(payload: dict) -> dict:
    phases = payload.get("phases")
    if not isinstance(phases, list):
        raise AssertionError("fixture must contain phases list")
    errors: list[str] = []
    if len(phases) != 10:
        errors.append(f"expected 10 phases, found {len(phases)}")

    total_steps = 0
    required = 0
    negative_same_domain = 0
    previous_domain = None
    for index, phase in enumerate(phases):
        if not isinstance(phase, dict):
            errors.append(f"phase {index + 1} is not an object")
            continue
        steps = phase.get("steps")
        if not isinstance(steps, list) or len(steps) != 10:
            errors.append(f"{phase.get('phase_id', index + 1)} must contain exactly 10 steps")
        else:
            total_steps += len(steps)
        domain = str(phase.get("domain") or "")
        requires_requery = bool(phase.get("requires_requery"))
        if requires_requery:
            required += 1
        if previous_domain == domain and not requires_requery:
            negative_same_domain += 1
        if previous_domain == domain and requires_requery:
            errors.append(f"{phase.get('phase_id')} re-queries inside the same domain")
        previous_domain = domain

    threshold = int(payload.get("requery_threshold", 4))
    if required < threshold:
        errors.append(f"expected at least {threshold} required re-queries, found {required}")
    if negative_same_domain < 2:
        errors.append(f"expected at least 2 same-domain anti-spam negatives, found {negative_same_domain}")
    if total_steps != 100:
        errors.append(f"expected 100 steps, found {total_steps}")

    return {
        "ok": not errors,
        "phase_count": len(phases),
        "step_count": total_steps,
        "required_requery_count": required,
        "same_domain_negative_count": negative_same_domain,
        "threshold": threshold,
        "mechanism": "guidance_decision_level_not_runtime_hook",
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    args = parser.parse_args(argv)
    report = verify(load_fixture())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"Router Inject v2 fixture: {report['phase_count']} phases, {report['step_count']} steps, "
            f"{report['required_requery_count']} required re-queries, "
            f"{report['same_domain_negative_count']} same-domain anti-spam negatives"
        )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
