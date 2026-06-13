from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "AI4sale/unlimited-skills"
DEFAULT_PACKAGE = "unlimited-skills"
DEFAULT_RELEASE_TAG = "v0.5.1-alpha"
USER_AGENT = "unlimited-skills-public-alpha-rollup/1.0"


def _utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _fetch_json(url: str, timeout: float) -> tuple[Any | None, str | None]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - public HTTPS JSON only.
            return json.loads(response.read().decode("utf-8")), None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _semantic_version_key(version: str) -> tuple[int, ...]:
    parts = []
    for part in re.split(r"[.\-+]", version):
        if part.isdigit():
            parts.append(int(part))
        else:
            break
    return tuple(parts)


def _parse_rollup_id(out_path: Path) -> str:
    match = re.search(r"public-alpha-signal-rollup-(\d+)", out_path.name)
    if match:
        return match.group(1)
    return "generated"


def _parse_marketplace_tracker(repo_root: Path) -> dict[str, Any]:
    tracker_path = repo_root / "docs" / "adoption" / "marketplace-submission-tracker.md"
    if not tracker_path.exists():
        return {
            "path": str(tracker_path.relative_to(repo_root)),
            "rows": [],
            "status_counts": {},
            "error": "missing tracker file",
        }

    rows: list[dict[str, str]] = []
    headers: list[str] | None = None
    for line in _read_text(tracker_path).splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = [cell.strip().strip("`") for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        if cells[0] == "surface":
            headers = cells
            continue
        if headers and len(cells) == len(headers):
            rows.append(dict(zip(headers, cells, strict=True)))

    status_counts: dict[str, int] = {}
    for row in rows:
        status = row.get("status", "unknown") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "path": str(tracker_path.relative_to(repo_root)),
        "rows": rows,
        "status_counts": status_counts,
        "error": None,
    }


def _load_social_input(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("--social-json must contain a JSON object")

    allowed = {"source", "date_checked", "summary", "public_url", "metrics", "notes"}
    social = {key: raw[key] for key in allowed if key in raw}
    metrics = social.get("metrics")
    if metrics is not None and not isinstance(metrics, dict):
        raise SystemExit("--social-json metrics must be a JSON object when provided")
    return social


def _fixture_snapshot(repo_root: Path) -> dict[str, Any]:
    return {
        "date_checked": "2026-06-13",
        "mode": "fixture",
        "package": {
            "name": DEFAULT_PACKAGE,
            "latest": "0.5.1",
            "releases": ["0.5.0", "0.5.1"],
            "status": "available",
            "error": None,
        },
        "github_release": {
            "repo": DEFAULT_REPO,
            "tag": DEFAULT_RELEASE_TAG,
            "name": "v0.5.1-alpha - adoption tools",
            "prerelease": True,
            "published_at": "2026-06-13T04:05:42Z",
            "status": "available",
            "error": None,
        },
        "github_repo": {
            "repo": DEFAULT_REPO,
            "stars": 5,
            "forks": 0,
            "watchers": 5,
            "status": "available",
            "error": None,
        },
        "github_issues": {
            "public_issues_returned": 0,
            "open_prs": ["#119 parked"],
            "status": "available",
            "error": None,
        },
        "marketplace": _parse_marketplace_tracker(repo_root),
    }


def _live_snapshot(repo_root: Path, timeout: float) -> dict[str, Any]:
    package_data, package_error = _fetch_json(f"https://pypi.org/pypi/{DEFAULT_PACKAGE}/json", timeout)
    release_data, release_error = _fetch_json(
        f"https://api.github.com/repos/{DEFAULT_REPO}/releases/tags/{DEFAULT_RELEASE_TAG}", timeout
    )
    repo_data, repo_error = _fetch_json(f"https://api.github.com/repos/{DEFAULT_REPO}", timeout)
    issues_data, issues_error = _fetch_json(
        f"https://api.github.com/repos/{DEFAULT_REPO}/issues?state=all&per_page=100", timeout
    )
    pulls_data, pulls_error = _fetch_json(f"https://api.github.com/repos/{DEFAULT_REPO}/pulls?state=open&per_page=100", timeout)

    releases: list[str] = []
    latest = "unknown"
    if isinstance(package_data, dict):
        release_map = package_data.get("releases", {})
        if isinstance(release_map, dict):
            releases = sorted(release_map, key=_semantic_version_key)
        info = package_data.get("info", {})
        if isinstance(info, dict):
            latest = str(info.get("version") or latest)

    issue_count = "unknown"
    if isinstance(issues_data, list):
        issue_count = str(sum(1 for item in issues_data if isinstance(item, dict) and "pull_request" not in item))

    open_prs: list[str] = []
    if isinstance(pulls_data, list):
        for item in pulls_data:
            if isinstance(item, dict):
                number = item.get("number")
                title = item.get("title", "")
                if number:
                    open_prs.append(f"#{number} {title}".strip())
    elif pulls_error:
        open_prs.append(f"unavailable: {pulls_error}")

    return {
        "date_checked": _utc_date(),
        "mode": "live_public",
        "package": {
            "name": DEFAULT_PACKAGE,
            "latest": latest,
            "releases": releases[-5:],
            "status": "available" if package_data else "unavailable",
            "error": package_error,
        },
        "github_release": {
            "repo": DEFAULT_REPO,
            "tag": DEFAULT_RELEASE_TAG,
            "name": release_data.get("name", "unknown") if isinstance(release_data, dict) else "unknown",
            "prerelease": release_data.get("prerelease", "unknown") if isinstance(release_data, dict) else "unknown",
            "published_at": release_data.get("published_at", "unknown") if isinstance(release_data, dict) else "unknown",
            "status": "available" if release_data else "unavailable",
            "error": release_error,
        },
        "github_repo": {
            "repo": DEFAULT_REPO,
            "stars": repo_data.get("stargazers_count", "unknown") if isinstance(repo_data, dict) else "unknown",
            "forks": repo_data.get("forks_count", "unknown") if isinstance(repo_data, dict) else "unknown",
            "watchers": repo_data.get("subscribers_count", "unknown") if isinstance(repo_data, dict) else "unknown",
            "status": "available" if repo_data else "unavailable",
            "error": repo_error,
        },
        "github_issues": {
            "public_issues_returned": issue_count,
            "open_prs": open_prs,
            "status": "available" if issues_data is not None else "unavailable",
            "error": issues_error,
        },
        "marketplace": _parse_marketplace_tracker(repo_root),
    }


def _format_status_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "unknown"
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))


def _format_social(social: dict[str, Any] | None) -> str:
    if not social:
        return (
            "- Owner-provided manual social input: not provided.\n"
            "- LinkedIn or other social replies/comments are not inferred from private accounts.\n"
            "- Signal state: `no_feedback_yet` unless a public/manual source is added."
        )

    lines = ["- Owner-provided manual social input: provided and marked as owner-provided aggregate context."]
    for key in ["source", "date_checked", "public_url", "summary", "notes"]:
        value = social.get(key)
        if value:
            lines.append(f"- {key}: {value}")
    metrics = social.get("metrics")
    if isinstance(metrics, dict) and metrics:
        metric_text = ", ".join(f"{key}={value}" for key, value in sorted(metrics.items()))
        lines.append(f"- aggregate metrics: {metric_text}")
    return "\n".join(lines)


def render_rollup(snapshot: dict[str, Any], out_path: Path, social: dict[str, Any] | None) -> str:
    rollup_id = _parse_rollup_id(out_path)
    package = snapshot["package"]
    release = snapshot["github_release"]
    repo = snapshot["github_repo"]
    issues = snapshot["github_issues"]
    marketplace = snapshot["marketplace"]
    releases = ", ".join(package.get("releases") or ["unknown"])
    status_counts = _format_status_counts(marketplace.get("status_counts", {}))
    open_prs = issues.get("open_prs") or []
    open_pr_text = ", ".join(open_prs) if open_prs else "none returned"
    issue_count = issues.get("public_issues_returned", "unknown")
    latest = package.get("latest", "unknown")

    return f"""# Public-Alpha Signal Rollup {rollup_id}

Date checked: {snapshot["date_checked"]}

Scope: generated public-alpha adoption signal rollup for Unlimited Skills.
This report uses only public aggregate sources, local repository files, and
optional owner-provided manual aggregate input. It does not add telemetry,
tracking pixels, analytics SDKs, hidden identifiers, private user data,
prompt collection, tool input collection, tool output collection, or hosted
query forwarding.

Privacy boundary: no telemetry; no auto-upload; no tracking pixels; no
analytics SDKs; no hidden identifiers; no private user data; no prompt
collection; no tool input collection; no tool output collection; no hosted
query forwarding.

Blocked data paths: no hosted query forwarding; no private social scraping.

## Rollup Summary

- Distribution state: PyPI package `unlimited-skills=={latest}` is `{package.get("status")}`.
- Release state: GitHub release `{release.get("tag")}` is `{release.get("status")}`.
- Feedback state: `low_signal` / `no_feedback_yet` unless public/manual reports are added.
- Marketplace state: {status_counts}.
- Claim state: no marketplace submission, paid outreach, payment links,
  hosted/team/enterprise readiness claims, external acceptance claims, or
  delivery promises are made by this rollup.

## Data Sources Checked

| Source | Mode | Result |
| --- | --- | --- |
| PyPI JSON for `{package.get("name")}` | {snapshot["mode"]} | latest `{latest}`; recent releases: {releases}; error: {package.get("error") or "none"} |
| GitHub release `{release.get("tag")}` | {snapshot["mode"]} | name `{release.get("name")}`; prerelease `{release.get("prerelease")}`; published `{release.get("published_at")}`; error: {release.get("error") or "none"} |
| GitHub repo counters for `{repo.get("repo")}` | {snapshot["mode"]} | {repo.get("stars")} stars, {repo.get("forks")} forks, {repo.get("watchers")} watchers; error: {repo.get("error") or "none"} |
| GitHub public issues | {snapshot["mode"]} | {issue_count} non-PR issues returned; open PRs: {open_pr_text}; error: {issues.get("error") or "none"} |
| Marketplace tracker | local file | `{marketplace.get("path")}`; statuses: {status_counts}; error: {marketplace.get("error") or "none"} |

## Installation/Discovery Signals

- PyPI availability: `unlimited-skills=={latest}`.
- GitHub release availability: `{release.get("tag")}`.
- GitHub public interest counters: {repo.get("stars")} stars, {repo.get("forks")} forks, {repo.get("watchers")} watchers.
- PyPI download counts are not inferred from PyPI JSON because that endpoint
  does not expose download counts.

## First-Value Signals

- First-value reports: none included by default.
- Install-friction reports: none included by default.
- Skill-not-invoked reports: none included by default.
- MCP savings reports: none included by default.
- Decision state: `no_feedback_yet` until manual issue reports or
  owner-provided public aggregate summaries are attached.

## Feedback/Issues

- Public issues returned: {issue_count}.
- Open PRs observed: {open_pr_text}.
- The parked PR #119 remains outside this adoption rollup unless the owner
  explicitly reopens it.
- Do not infer private usage from silence. Silence means unknown, not success.

## Marketplace/Listing Status

- Tracker statuses: {status_counts}.
- A3.4 actual submission evidence remains `blocked_pending_owner_approval`
  until the owner approves exact destinations, submission owner, listing copy,
  and submission permission.
- Keep all marketplace rows `not_submitted` until there is a dated owner action
  and evidence link.

## Social/LinkedIn Launch Signal

{_format_social(social)}

## Signal Quality Assessment

- Signal quality: `low_signal`.
- Feedback state: `no_feedback_yet`.
- This rollup is useful as a reproducible baseline, not as proof of adoption.
- Next rollups should compare only public aggregate counters and manual
  redacted feedback artifacts.

## Blockers

| Blocker | Owner | Action | Fallback |
| --- | --- | --- | --- |
| No manual first-value reports | Release owner | Ask for three redacted first-value or install-friction reports | Publish a focused install/first-value request |
| Marketplace submission evidence missing | Project owner | Approve exact destinations, owner, listing copy, and submission permission | Keep all marketplace rows `not_submitted` |
| Social signal not provided | Release owner | Add owner-provided aggregate social JSON if available | Keep `no_feedback_yet` |

## Next Actions

1. Generate the next rollup with
   `python scripts/generate-public-alpha-signal-rollup.py --out docs/adoption/public-alpha-signal-rollup-002.md`.
2. Attach optional owner-provided aggregate social input with `--social-json`
   only when the owner supplies it intentionally.
3. Keep issue triage and support responses aligned with
   `docs/adoption/support-response-pack.md`.

## Non-Goals and Claim Guard

This rollup does not implement or claim telemetry, automatic upload, analytics,
private social scraping, marketplace submission, paid CTA, payment links,
hosted service readiness, team readiness, enterprise readiness, SLA/support
delivery, external acceptance, or production hosted gateway availability.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a public-alpha adoption signal rollup.")
    parser.add_argument("--fixture-mode", action="store_true", help="Use deterministic offline fixture data.")
    parser.add_argument("--out", required=True, type=Path, help="Output markdown path.")
    parser.add_argument("--repo-root", default=ROOT, type=Path, help="Repository root for local docs/tracker inputs.")
    parser.add_argument("--social-json", type=Path, help="Optional owner-provided aggregate social summary JSON.")
    parser.add_argument("--timeout", default=8.0, type=float, help="HTTP timeout in live public mode.")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    social = _load_social_input(args.social_json)
    snapshot = _fixture_snapshot(repo_root) if args.fixture_mode else _live_snapshot(repo_root, args.timeout)
    output = render_rollup(snapshot, args.out, social)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(output, encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
