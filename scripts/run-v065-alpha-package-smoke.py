"""Build and clean-install smoke for the v0.6.5 retrieval/learning reliability package."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERSION = "0.6.5"
PYPI_UPGRADE_BASELINE = "0.6.4.post1"


def _version_at_least(value: str, floor: tuple[int, int, int]) -> bool:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value)
    return bool(match and tuple(int(part) for part in match.groups()) >= floor)


LINKEDIN_QUERY = "напиши пост для линкедин"


def venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_script(root: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return root / ("Scripts" if os.name == "nt" else "bin") / f"{name}{suffix}"


def run(args: list[str], *, cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
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


def require_ok(proc: subprocess.CompletedProcess[str], label: str) -> str:
    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed:\nSTDOUT:\n{proc.stdout[-1600:]}\nSTDERR:\n{proc.stderr[-1600:]}")
    return proc.stdout


def load_json(text: str) -> Any:
    return json.loads(text)


def build_dist(dist_dir: Path) -> tuple[Path, Path]:
    require_ok(run([sys.executable, "-m", "pip", "install", "--upgrade", "build", "twine"], cwd=ROOT), "install build tools")
    require_ok(run([sys.executable, "-m", "build", "--outdir", str(dist_dir)], cwd=ROOT), "build dist")
    require_ok(run([sys.executable, "-m", "twine", "check", str(dist_dir / "*")], cwd=ROOT), "twine check")
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise RuntimeError("expected exactly one wheel and one sdist")
    return wheels[0], sdists[0]


def existing_dist(dist_dir: Path) -> tuple[Path, Path]:
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise RuntimeError(f"expected exactly one wheel and one sdist in {dist_dir}")
    require_ok(run([sys.executable, "-m", "twine", "check", str(wheels[0]), str(sdists[0])], cwd=ROOT), "twine check existing dist")
    return wheels[0], sdists[0]


def write_skill(root: Path, name: str, description: str, body: str = "") -> None:
    skill_dir = root / "registry" / "ecc" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )


def seed_retrieval_fixture(root: Path) -> None:
    write_skill(root, "marketing-campaign", "Plan launch messaging, LinkedIn posts, GTM copy, and campaign assets.")
    write_skill(root, "content-engine", "Write LinkedIn posts, social content, newsletters, articles, and repurposed launch content.")
    write_skill(root, "social-publisher", "Prepare social posts for LinkedIn, X, Threads, and other social channels.")
    write_skill(root, "router-upgrade-maintenance", "Repair stale launchers after pip upgrade and package refresh.")
    write_skill(root, "inject-refresh", "Refresh router inject artifacts, CLAUDE.md, AGENTS.md, and agent hooks.")


def clean_install_retrieval_smoke(wheel: Path, work: Path, expected_version: str) -> dict[str, Any]:
    env_dir = work / "venv"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    py = venv_python(env_dir)
    cli = venv_script(env_dir, "unlimited-skills")
    require_ok(run([str(py), "-m", "pip", "install", str(wheel)], cwd=work), "install wheel")

    library = work / "library"
    seed_retrieval_fixture(library)

    def run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
        proc = run([str(cli), "--root", str(library), *args], cwd=work, timeout=300)
        require_ok(proc, "unlimited-skills " + " ".join(args))
        return proc

    version_output = require_ok(run([str(cli), "--version"], cwd=work), "version").strip()
    suggest = load_json(run_cli(["suggest", LINKEDIN_QUERY, "--json", "--card", "--limit", "5"]).stdout)
    search = load_json(run_cli(["search", LINKEDIN_QUERY, "--mode", "hybrid", "--json", "--limit", "5", "--no-native-sync"]).stdout)
    learning = load_json(run_cli(["learning-summary", "--events", "--json"]).stdout)

    candidate_names = [row.get("name") for row in suggest.get("top_3_skill_candidates", []) if isinstance(row, dict)]
    search_names = [row.get("name") for row in search if isinstance(row, dict)]
    return {
        "version_output": version_output,
        "expected_version_output": f"unlimited-skills {expected_version}",
        "suggest_reason_code": suggest.get("reason_code"),
        "suggest_delivery_tier": suggest.get("delivery_tier"),
        "suggest_candidate_names": candidate_names,
        "suggest_needs_english_query": suggest.get("needs_english_query"),
        "suggest_delivery_mode": (suggest.get("delivery") or {}).get("mode"),
        "search_candidate_names": search_names,
        "search_candidate_sources_present": all(bool(row.get("candidate_sources")) for row in search if isinstance(row, dict)),
        "learning_summary_has_effectiveness": isinstance(learning, dict) and "effectiveness" in learning,
    }


def upgrade_from_public_pypi_smoke(wheel: Path, work: Path, expected_version: str) -> dict[str, Any]:
    env_dir = work / "venv"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    py = venv_python(env_dir)
    cli = venv_script(env_dir, "unlimited-skills")
    require_ok(
        run(
            [str(py), "-m", "pip", "install", "--no-cache-dir", "--index-url", "https://pypi.org/simple", f"unlimited-skills=={PYPI_UPGRADE_BASELINE}"],
            cwd=work,
            timeout=900,
        ),
        "install official PyPI baseline",
    )
    before = require_ok(run([str(cli), "--version"], cwd=work), "baseline version").strip()
    library = work / "library"
    baseline_quickstart = load_json(
        require_ok(
            run([str(cli), "--root", str(library), "quickstart", "--json", "--skip-mcp-check"], cwd=work, timeout=300),
            "baseline quickstart",
        )
    )
    sentinel = library / "local" / "skills" / "upgrade-sentinel" / "SKILL.md"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text(
        "---\nname: upgrade-sentinel\ndescription: Must survive the public package upgrade smoke.\n---\n",
        encoding="utf-8",
    )
    require_ok(run([str(py), "-m", "pip", "install", "--upgrade", str(wheel)], cwd=work, timeout=900), "upgrade to exact wheel")
    after = require_ok(run([str(cli), "--version"], cwd=work), "upgraded version").strip()

    quickstart = load_json(
        require_ok(
            run([str(cli), "--root", str(library), "quickstart", "--json", "--skip-mcp-check"], cwd=work, timeout=300),
            "upgraded quickstart",
        )
    )
    doctor = load_json(require_ok(run([str(cli), "--root", str(library), "doctor", "--json"], cwd=work), "upgraded doctor"))
    suggest_payload = load_json(
        require_ok(run([str(cli), "--root", str(library), "suggest", "code review checklist", "--json"], cwd=work), "upgraded suggest")
    )
    search_payload = load_json(
        require_ok(
            run([str(cli), "--root", str(library), "search", "code review checklist", "--mode", "lexical", "--json", "--no-native-sync"], cwd=work),
            "upgraded search",
        )
    )
    learning = load_json(
        require_ok(run([str(cli), "--root", str(library), "learning-summary", "--events", "--json"], cwd=work), "upgraded learning summary")
    )
    return {
        "baseline_version_output": before,
        "baseline_quickstart_skill_count": baseline_quickstart.get("library", {}).get("skill_count", 0),
        "upgraded_version_output": after,
        "quickstart_skill_count": quickstart.get("library", {}).get("skill_count", 0),
        "quickstart_index_refreshed": quickstart.get("library", {}).get("index_refreshed"),
        "local_sentinel_preserved": sentinel.is_file(),
        "doctor_index_current": doctor.get("library", {}).get("index_current"),
        "suggest_candidates": len(suggest_payload.get("top_3_skill_candidates") or []),
        "search_candidates": len(search_payload) if isinstance(search_payload, list) else 0,
        "learning_effectiveness_present": isinstance(learning, dict) and "effectiveness" in learning,
        "expected_version_output": f"unlimited-skills {expected_version}",
    }


def run_source_release_smokes() -> dict[str, Any]:
    release_smoke = load_json(
        require_ok(
            run([sys.executable, "scripts/verify-v065-retrieval-learning-release-smoke.py", "--skip-installed-library", "--json"], cwd=ROOT, timeout=900),
            "source combined release smoke",
        )
    )
    learning_loop = load_json(require_ok(run([sys.executable, "scripts/verify-v065-learning-loop.py", "--json"], cwd=ROOT), "source learning-loop smoke"))
    return {
        "release_smoke_ok": release_smoke.get("ok"),
        "release_smoke_schema": release_smoke.get("schema_version"),
        "learning_loop_ok": learning_loop.get("ok"),
        "learning_loop_manual_no_query": learning_loop.get("rows", {}).get("manual_search_view_use_without_query", {}).get("query_on_use") is False,
    }


def verify_report(report: dict[str, Any], expected_version: str = DEFAULT_VERSION) -> list[str]:
    errors: list[str] = []
    if report.get("version") != expected_version:
        errors.append("version mismatch")
    dist = report.get("dist") if isinstance(report.get("dist"), dict) else {}
    normalized = expected_version.replace("-", "_")
    if f"-{normalized}-" not in str(dist.get("wheel", "")):
        errors.append(f"wheel filename must include {expected_version}")
    installed = report.get("clean_install_retrieval_learning") or {}
    if installed.get("version_output") != f"unlimited-skills {expected_version}":
        errors.append(f"installed CLI version output mismatch for {expected_version}")
    if installed.get("suggest_reason_code") != "match_found":
        errors.append("LinkedIn suggest smoke must find candidates")
    rescue_only = (
        _version_at_least(expected_version, (0, 6, 6))
        and installed.get("suggest_needs_english_query") is True
        and installed.get("suggest_delivery_mode") == "rescue"
        and installed.get("suggest_delivery_tier") == 1
    )
    if not installed.get("suggest_candidate_names") and not rescue_only:
        errors.append("LinkedIn suggest smoke must return safe candidate names or an explicit English-query rescue")
    if not installed.get("search_candidate_names"):
        errors.append("LinkedIn search smoke must return candidate names")
    if installed.get("search_candidate_sources_present") is not True:
        errors.append("search smoke must include candidate source metadata")
    if installed.get("learning_summary_has_effectiveness") is not True:
        errors.append("installed CLI learning-summary must include effectiveness")
    source = report.get("source_release_gates") or {}
    if source.get("release_smoke_ok") is not True:
        errors.append("source combined release smoke must pass")
    if source.get("learning_loop_ok") is not True:
        errors.append("source learning-loop smoke must pass")
    if source.get("learning_loop_manual_no_query") is not True:
        errors.append("learning-loop smoke must prove manual search -> view -> use without --query")
    if _version_at_least(expected_version, (0, 6, 6)):
        upgrade = report.get("upgrade_from_public_pypi") or {}
        if upgrade.get("baseline_version_output") != f"unlimited-skills {PYPI_UPGRADE_BASELINE}":
            errors.append("upgrade smoke must start from the official PyPI baseline")
        if upgrade.get("upgraded_version_output") != f"unlimited-skills {expected_version}":
            errors.append("upgrade smoke must install the exact release wheel")
        if int(upgrade.get("baseline_quickstart_skill_count") or 0) < 267:
            errors.append("upgrade smoke baseline must create a real pre-upgrade library")
        if int(upgrade.get("quickstart_skill_count") or 0) < 267:
            errors.append("upgraded quickstart must import 267+ bundled skills")
        if upgrade.get("quickstart_index_refreshed") is not True:
            errors.append("upgraded quickstart must migrate the legacy lexical index in place")
        if upgrade.get("local_sentinel_preserved") is not True:
            errors.append("upgrade smoke must preserve local skills")
        if upgrade.get("doctor_index_current") is not True:
            errors.append("upgraded doctor must report the lexical index current")
        if int(upgrade.get("suggest_candidates") or 0) < 1 or int(upgrade.get("search_candidates") or 0) < 1:
            errors.append("upgraded retrieval commands must return candidates")
        if upgrade.get("learning_effectiveness_present") is not True:
            errors.append("upgraded learning summary must remain available")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", default=DEFAULT_VERSION)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument("--dist-dir", default="", help="Use one already-built wheel/sdist pair instead of rebuilding.")
    args = parser.parse_args(argv)

    tmp = Path(tempfile.mkdtemp(prefix="uls-v065-package-smoke-"))
    try:
        if args.dist_dir:
            wheel, sdist = existing_dist(Path(args.dist_dir).resolve())
        else:
            dist_dir = tmp / "dist"
            dist_dir.mkdir()
            wheel, sdist = build_dist(dist_dir)
        report = {
            "schema_version": 1,
            "version": args.expected_version,
            "dist": {"wheel": wheel.name, "sdist": sdist.name},
            "clean_install_retrieval_learning": clean_install_retrieval_smoke(wheel, tmp / "installed", args.expected_version),
            "upgrade_from_public_pypi": upgrade_from_public_pypi_smoke(wheel, tmp / "upgrade", args.expected_version),
            "source_release_gates": run_source_release_smokes(),
        }
        report["errors"] = verify_report(report, args.expected_version)
        report["ok"] = not report["errors"]
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"v0.6.5 package smoke ({args.expected_version}): " + ("PASS" if report["ok"] else "FAIL"))
            for error in report["errors"]:
                print(f"- {error}")
        return 0 if report["ok"] else 1
    finally:
        if args.keep_temp:
            print(f"kept temp: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
