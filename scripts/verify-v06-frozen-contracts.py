#!/usr/bin/env python
"""Verify the frozen v0.6 public-alpha CLI/stdout/privacy contracts.

The verifier runs against the current working tree by default. With
``--wheel`` it installs the given wheel into a temporary virtual environment
and runs the CLI from that clean install. All checks use a temporary library
root and must not mutate the user's real Unlimited Skills library.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import venv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPECTED_VERSION = "0.6.5.post1"
TASK_QUERY = "Design a REST API for a service"
OWNER = "release owner"
ACTION = "Fix the frozen contract drift before publishing or tagging another v0.6 release."
FALLBACK = "Keep the release gate blocked and document the drift until a fix lands."

FORBIDDEN_PATTERNS = [
    re.compile(r"[A-Za-z]:\\[^\s\"']+", re.IGNORECASE),
    re.compile(r"/(?:Users|home|private|tmp|var|etc)/[^\s\"']+", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|glpat|xoxb|uls)_[A-Za-z0-9_\-]{8,}\b", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(inputSchema|tool_input|tool_output|license_token|private_key)\b", re.IGNORECASE),
    re.compile(r"\b(customer secret query|private customer task|Prompt:)\b", re.IGNORECASE),
]


@dataclass
class Row:
    surface: str
    command: str
    status: str
    owner: str
    action: str
    fallback: str
    evidence: dict[str, Any]


def venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if sys.platform.startswith("win") else "bin/python")


def venv_script(root: Path, name: str) -> Path:
    return root / (f"Scripts/{name}.exe" if sys.platform.startswith("win") else f"bin/{name}")


def run(args: list[str], *, cwd: Path, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def load_json(text: str, surface: str) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"{surface} did not emit valid JSON: {exc}"
    if not isinstance(payload, (dict, list)):
        return None, f"{surface} JSON must be an object or list"
    return payload, None


def forbidden_hits(text: str) -> list[str]:
    return [pattern.pattern for pattern in FORBIDDEN_PATTERNS if pattern.search(text)]


def assert_roi_schema(payload: dict[str, Any]) -> list[str]:
    schema = json.loads((ROOT / "schemas" / "roi-receipt.schema.json").read_text(encoding="utf-8"))
    missing = [key for key in schema.get("required", []) if key not in payload]
    errors = [f"missing ROI schema keys: {missing}"] if missing else []
    if payload.get("schema_version") != 1:
        errors.append("ROI schema_version must be 1")
    if payload.get("report_type") != "local_roi_receipt":
        errors.append("ROI report_type must be local_roi_receipt")
    privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
    if privacy.get("local_only") is not True:
        errors.append("ROI privacy.local_only must be true")
    for key in ("telemetry", "upload", "analytics", "tracking_pixel"):
        if privacy.get(key) is not False:
            errors.append(f"ROI privacy.{key} must be false")
    if payload.get("privacy_notice") != schema["properties"]["privacy_notice"]["const"]:
        errors.append("ROI privacy_notice mismatch")
    return errors


def pass_row(surface: str, command: str, evidence: dict[str, Any]) -> Row:
    return Row(surface, command, "pass", OWNER, "No action required.", "No fallback required.", evidence)


def drift_row(surface: str, command: str, reason: str, evidence: dict[str, Any] | None = None) -> Row:
    payload = {"reason": reason}
    if evidence:
        payload.update(evidence)
    return Row(surface, command, "drift", OWNER, ACTION, FALLBACK, payload)


def blocked_row(surface: str, command: str, reason: str, evidence: dict[str, Any] | None = None) -> Row:
    payload = {"reason": reason}
    if evidence:
        payload.update(evidence)
    return Row(
        surface,
        command,
        "blocked",
        OWNER,
        "Unblock the local verifier environment, then rerun the frozen-contract harness.",
        FALLBACK,
        payload,
    )


class Runner:
    def __init__(self, cli: list[str], py: Path, root: Path) -> None:
        self.cli = cli
        self.py = py
        self.root = root
        self.missing_claude = root / "missing-claude.json"
        self.project = root / "project"

    def cli_cmd(self, *args: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
        return run([*self.cli, *args], cwd=ROOT, timeout=timeout)

    def py_cmd(self, *args: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
        return run([str(self.py), *args], cwd=ROOT, timeout=timeout)


def check_json_command(
    runner: Runner,
    surface: str,
    display: str,
    args: list[str],
    validator,
    *,
    timeout: int = 180,
) -> Row:
    proc = runner.cli_cmd(*args, timeout=timeout)
    if proc.returncode != 0:
        return drift_row(surface, display, "command exited non-zero", {"returncode": proc.returncode, "stderr_tail": proc.stderr[-800:]})
    payload, error = load_json(proc.stdout, surface)
    if error:
        return drift_row(surface, display, error, {"stdout_tail": proc.stdout[-800:]})
    assert payload is not None
    errors = validator(payload, proc.stdout)
    if errors:
        return drift_row(surface, display, "; ".join(errors), {"payload_keys": list(payload[0].keys()) if isinstance(payload, list) and payload and isinstance(payload[0], dict) else list(payload.keys()) if isinstance(payload, dict) else []})
    return pass_row(surface, display, {"json": True, "bytes": len(proc.stdout.encode("utf-8"))})


def validate_quickstart(payload: dict[str, Any] | list[Any], _text: str) -> list[str]:
    if not isinstance(payload, dict):
        return ["quickstart payload must be an object"]
    errors = []
    for key in ("library", "root", "search", "next_steps"):
        if key not in payload:
            errors.append(f"quickstart missing {key}")
    if payload.get("root") != "<local-library>":
        errors.append("quickstart root must be redacted")
    search = payload.get("search") if isinstance(payload.get("search"), dict) else {}
    if not isinstance(search.get("hits"), list):
        errors.append("quickstart search.hits must be a list")
    return errors


def validate_suggest(payload: dict[str, Any] | list[Any], text: str) -> list[str]:
    if not isinstance(payload, dict):
        return ["suggest payload must be an object"]
    errors = []
    for key in ("task_summary_hash", "top_3_skill_candidates", "reason_code", "recommended_next_action", "latency_ms"):
        if key not in payload:
            errors.append(f"suggest missing {key}")
    if TASK_QUERY.lower() in text.lower():
        errors.append("suggest output must not echo raw task text")
    if not isinstance(payload.get("top_3_skill_candidates"), list):
        errors.append("suggest candidates must be a list")
    return errors


def validate_mcp_install(payload: dict[str, Any] | list[Any], text: str) -> list[str]:
    if not isinstance(payload, dict):
        return ["mcp install payload must be an object"]
    errors = []
    lowered = json.dumps(payload, ensure_ascii=False).lower()
    for needle in ("dry", "claude", "gateway"):
        if needle not in lowered:
            errors.append(f"mcp install output missing {needle}")
    if forbidden_hits(text):
        errors.append("mcp install output contains forbidden private markers")
    return errors


def validate_mcp_savings(payload: dict[str, Any] | list[Any], _text: str) -> list[str]:
    if not isinstance(payload, dict):
        return ["mcp savings payload must be an object"]
    errors = []
    for key in ("servers", "total_bytes", "gateway_bytes", "savings_bytes", "savings_pct"):
        if key not in payload:
            errors.append(f"mcp savings missing {key}")
    if not isinstance(payload.get("servers"), list):
        errors.append("mcp savings servers must be a list")
    return errors


def validate_feedback(payload: dict[str, Any] | list[Any], text: str) -> list[str]:
    if not isinstance(payload, dict):
        return ["feedback prepare payload must be an object"]
    errors = []
    for key in ("schema_version", "report_type", "privacy"):
        if key not in payload:
            errors.append(f"feedback prepare missing {key}")
    if payload.get("schema_version") != 1:
        errors.append("feedback schema_version must be 1")
    privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
    if payload.get("local_only") is not True:
        errors.append("feedback local_only must be true")
    if payload.get("network_calls") is not False or payload.get("hosted_calls") is not False:
        errors.append("feedback hosted/network calls must be false")
    for key in ("telemetry", "auto_upload"):
        if privacy.get(key) is not False:
            errors.append(f"feedback privacy.{key} must be false")
    if forbidden_hits(text):
        errors.append("feedback output contains forbidden private markers")
    return errors


def validate_learning(payload: dict[str, Any] | list[Any], _text: str) -> list[str]:
    if not isinstance(payload, dict):
        return ["learning-summary payload must be an object"]
    errors = []
    for key in ("effectiveness", "feedback"):
        if key not in payload:
            errors.append(f"learning-summary missing {key}")
    return errors


def validate_roi_json(payload: dict[str, Any] | list[Any], text: str) -> list[str]:
    if not isinstance(payload, dict):
        return ["ROI receipt JSON payload must be an object"]
    errors = assert_roi_schema(payload)
    if forbidden_hits(text):
        errors.append("ROI receipt JSON contains forbidden private markers")
    return errors


def check_text_command(runner: Runner, surface: str, display: str, args: list[str], validator, *, timeout: int = 180) -> Row:
    proc = runner.cli_cmd(*args, timeout=timeout)
    if proc.returncode != 0:
        return drift_row(surface, display, "command exited non-zero", {"returncode": proc.returncode, "stderr_tail": proc.stderr[-800:]})
    errors = validator(proc.stdout)
    if errors:
        return drift_row(surface, display, "; ".join(errors), {"stdout_tail": proc.stdout[-800:]})
    return pass_row(surface, display, {"bytes": len(proc.stdout.encode("utf-8"))})


def validate_roi_markdown(text: str) -> list[str]:
    errors = []
    for required in ("# Unlimited Skills local ROI receipt", "not telemetry", "not a benchmark guarantee", "not a paid ROI promise"):
        if required not in text:
            errors.append(f"ROI markdown missing {required}")
    if forbidden_hits(text):
        errors.append("ROI markdown contains forbidden private markers")
    return errors


def validate_roi_since(text: str) -> list[str]:
    errors = validate_roi_markdown(text)
    if "Window: 7d" not in text:
        errors.append("ROI --since 7d output must include Window: 7d")
    return errors


def check_version(runner: Runner, expected_version: str) -> Row:
    display = "unlimited-skills --version"
    proc = runner.cli_cmd("--version")
    expected = f"unlimited-skills {expected_version}"
    if proc.returncode != 0:
        return drift_row("version", display, "command exited non-zero", {"returncode": proc.returncode, "stderr_tail": proc.stderr[-800:]})
    actual = proc.stdout.strip()
    if actual != expected and actual != f"__main__.py {expected_version}":
        return drift_row("version", display, "version output mismatch", {"expected": expected, "actual": actual})
    return pass_row("version", display, {"actual": actual})


def check_signal_rollup(runner: Runner) -> Row:
    out_path = runner.root / "public-alpha-signal-rollup-generated.md"
    display = "python scripts/generate-public-alpha-signal-rollup.py --fixture-mode --out <tmp>"
    proc = runner.py_cmd("scripts/generate-public-alpha-signal-rollup.py", "--fixture-mode", "--out", str(out_path))
    if proc.returncode != 0:
        return drift_row("signal_rollup_fixture", display, "command exited non-zero", {"returncode": proc.returncode, "stderr_tail": proc.stderr[-800:]})
    if not out_path.is_file():
        return drift_row("signal_rollup_fixture", display, "rollup file was not written")
    text = out_path.read_text(encoding="utf-8", errors="replace")
    missing = [needle for needle in ("Public-Alpha Signal Rollup", "fixture", "blocked_pending_owner_approval") if needle.lower() not in text.lower()]
    if missing:
        return drift_row("signal_rollup_fixture", display, "rollup output missing expected markers", {"missing": missing})
    return pass_row("signal_rollup_fixture", display, {"path": "<tmp>/public-alpha-signal-rollup-generated.md", "bytes": len(text.encode("utf-8"))})


def install_wheel(wheel_arg: str, work: Path) -> tuple[list[str], Path, Row | None]:
    matches = sorted(ROOT.glob(wheel_arg)) if any(char in wheel_arg for char in "*?[]") else [Path(wheel_arg)]
    if not matches:
        return [], Path(), blocked_row("wheel_install", f"install wheel {wheel_arg}", "wheel path did not match any file")
    wheel = matches[-1].resolve()
    if not wheel.is_file():
        return [], Path(), blocked_row("wheel_install", f"install wheel {wheel}", "wheel path is not a file")
    env_dir = work / "venv"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    py = venv_python(env_dir)
    proc = run([str(py), "-m", "pip", "install", "--no-cache-dir", str(wheel)], cwd=work, timeout=300)
    if proc.returncode != 0:
        return [], py, blocked_row("wheel_install", f"pip install {wheel.name}", "wheel install failed", {"returncode": proc.returncode, "stderr_tail": proc.stderr[-1200:]})
    return [str(venv_script(env_dir, "unlimited-skills"))], py, pass_row("wheel_install", f"pip install {wheel.name}", {"wheel": wheel.name})


def verify(expected_version: str, wheel: str | None = None, only: set[str] | None = None) -> dict[str, Any]:
    rows: list[Row] = []

    def selected(surface: str) -> bool:
        return only is None or surface in only

    with tempfile.TemporaryDirectory(prefix="uls-v06-contracts-") as tmp_dir:
        work = Path(tmp_dir)
        root = work / "library"
        root.mkdir()
        if wheel:
            cli, py, wheel_row = install_wheel(wheel, work)
            if wheel_row:
                rows.append(wheel_row)
            if not cli:
                return report(rows, expected_version, wheel_mode=True)
        else:
            cli = [str(Path(sys.executable)), "-m", "unlimited_skills"]
            py = Path(sys.executable)

        runner = Runner(cli, py, root)
        if selected("version"):
            rows.append(check_version(runner, expected_version))
        if selected("quickstart_json"):
            rows.append(
                check_json_command(
                    runner,
                    "quickstart_json",
                    "unlimited-skills quickstart --json",
                    ["--root", str(root), "quickstart", "--json", "--claude-config", str(runner.missing_claude), "--timeout", "2"],
                    validate_quickstart,
                    timeout=240,
                )
            )
        if selected("suggest_json"):
            rows.append(
                check_json_command(
                    runner,
                    "suggest_json",
                    f'unlimited-skills suggest "{TASK_QUERY}" --json',
                    ["--root", str(root), "suggest", TASK_QUERY, "--json"],
                    validate_suggest,
                )
            )
        if selected("mcp_install_dry_run"):
            rows.append(
                check_json_command(
                    runner,
                    "mcp_install_dry_run",
                    "unlimited-skills mcp install --claude-code --dry-run",
                    [
                        "--root",
                        str(root),
                        "mcp",
                        "install",
                        "--claude-code",
                        "--dry-run",
                        "--json",
                        "--project-root",
                        str(runner.project),
                        "--claude-config",
                        str(runner.missing_claude),
                    ],
                    validate_mcp_install,
                )
            )
        if selected("mcp_savings_json"):
            rows.append(
                check_json_command(
                    runner,
                    "mcp_savings_json",
                    "unlimited-skills mcp savings --json",
                    ["--root", str(root), "mcp", "savings", "--json", "--claude-config", str(runner.missing_claude), "--timeout", "2"],
                    validate_mcp_savings,
                )
            )
        if selected("feedback_prepare_json"):
            rows.append(
                check_json_command(
                    runner,
                    "feedback_prepare_json",
                    "unlimited-skills feedback prepare --json",
                    ["--root", str(root), "feedback", "prepare", "--json"],
                    validate_feedback,
                )
            )
        if selected("learning_summary_events_json"):
            rows.append(
                check_json_command(
                    runner,
                    "learning_summary_events_json",
                    "unlimited-skills learning-summary --events --json",
                    ["--root", str(root), "learning-summary", "--events", "--json"],
                    validate_learning,
                )
            )
        if selected("roi_receipt_markdown"):
            rows.append(check_text_command(runner, "roi_receipt_markdown", "unlimited-skills roi receipt", ["--root", str(root), "roi", "receipt"], validate_roi_markdown))
        if selected("roi_receipt_json"):
            rows.append(
                check_json_command(
                    runner,
                    "roi_receipt_json",
                    "unlimited-skills roi receipt --format json",
                    ["--root", str(root), "roi", "receipt", "--format", "json"],
                    validate_roi_json,
                )
            )
        if selected("roi_receipt_since_7d"):
            rows.append(check_text_command(runner, "roi_receipt_since_7d", "unlimited-skills roi receipt --since 7d", ["--root", str(root), "roi", "receipt", "--since", "7d"], validate_roi_since))
        if selected("signal_rollup_fixture"):
            rows.append(check_signal_rollup(runner))
    return report(rows, expected_version, wheel_mode=bool(wheel))


def report(rows: list[Row], expected_version: str, *, wheel_mode: bool) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row.status] = status_counts.get(row.status, 0) + 1
    return {
        "schema_version": 1,
        "report_type": "v06_frozen_contracts",
        "expected_version": expected_version,
        "wheel_mode": wheel_mode,
        "ok": status_counts.get("drift", 0) == 0 and status_counts.get("blocked", 0) == 0,
        "status_counts": status_counts,
        "rows": [row.__dict__ for row in rows],
    }


def render_text(payload: dict[str, Any]) -> str:
    lines = [
        "v0.6 frozen contract verification: " + ("PASS" if payload["ok"] else "FAIL"),
        f"expected_version: {payload['expected_version']}",
        f"wheel_mode: {str(payload['wheel_mode']).lower()}",
        "",
    ]
    for row in payload["rows"]:
        lines.append(f"- {row['status']}: {row['surface']} :: {row['command']}")
        if row["status"] != "pass":
            lines.append(f"  reason: {row['evidence'].get('reason', '')}")
            lines.append(f"  owner: {row['owner']}")
            lines.append(f"  action: {row['action']}")
            lines.append(f"  fallback: {row['fallback']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", default=DEFAULT_EXPECTED_VERSION)
    parser.add_argument("--wheel", help="Optional wheel path or glob to verify in a clean temporary venv.")
    parser.add_argument("--only", action="append", help="Development/test helper: run only the named surface. Repeat for multiple surfaces.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = verify(args.expected_version, args.wheel, set(args.only) if args.only else None)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_text(payload))
    if payload["ok"]:
        return 0
    if payload["status_counts"].get("drift", 0):
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
