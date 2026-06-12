"""Shared threshold profiles for the skill-effectiveness gate.

Keep release policy values here so the scenario runner, release wrapper,
tests, and docs do not grow independent copies of the same gate thresholds.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_GATE = "a0-merge"

EFFECTIVENESS_GATE_PROFILES: dict[str, dict[str, float | int]] = {
    "a0-merge": {
        "min_top1": 0.70,
        "min_top3": 0.85,
        "max_fp": 0.10,
        "max_p90_ms": 1500.0,
        "max_p95_ms": 2500.0,
        "warn_max_ms": 5000.0,
        "max_release_gap": 10,
        "min_positives": 30,
        "min_negatives": 10,
        "min_injection_precision": 0.90,
    },
    "v0.5-release": {
        "min_top1": 0.80,
        "min_top3": 0.90,
        "max_fp": 0.10,
        "max_p90_ms": 1200.0,
        "max_p95_ms": 2000.0,
        "warn_max_ms": 5000.0,
        "max_release_gap": 10,
        "min_positives": 30,
        "min_negatives": 10,
        "min_injection_precision": 0.95,
    },
}

RUNNER_ARG_NAMES: dict[str, str] = {
    "min_top1": "--min-top1",
    "min_top3": "--min-top3",
    "max_fp": "--max-fp",
    "max_p90_ms": "--max-p90-ms",
    "max_p95_ms": "--max-p95-ms",
    "warn_max_ms": "--warn-max-ms",
    "max_release_gap": "--max-release-gap",
    "min_positives": "--min-positives",
    "min_negatives": "--min-negatives",
    "min_injection_precision": "--min-injection-precision",
}


def get_effectiveness_gate_profile(name: str = DEFAULT_GATE) -> dict[str, float | int]:
    """Return a copy of the named threshold profile."""
    try:
        return deepcopy(EFFECTIVENESS_GATE_PROFILES[name])
    except KeyError as exc:
        choices = ", ".join(sorted(EFFECTIVENESS_GATE_PROFILES))
        raise ValueError(f"Unknown skill-effectiveness gate profile {name!r}; choose one of: {choices}") from exc


def profile_to_runner_args(name: str = DEFAULT_GATE, *, include_defaults: bool = False) -> list[str]:
    """Convert a named profile to CLI args for ``check-skill-effectiveness.py``.

    ``a0-merge`` is the runner default. By default this returns only values
    that differ from the A0 profile so wrapper invocations stay compact while
    still reading every value from the shared source.
    """
    profile = get_effectiveness_gate_profile(name)
    defaults = get_effectiveness_gate_profile(DEFAULT_GATE)
    args: list[str] = []
    for key, flag in RUNNER_ARG_NAMES.items():
        if include_defaults or profile[key] != defaults[key]:
            value: Any = profile[key]
            args.extend([flag, str(value)])
    return args
