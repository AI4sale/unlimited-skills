"""Updater/launcher durability smoke (R1 / O064-R1-UPDATER-IMPL).

Builds the wheel, clean-installs it into a throwaway venv, and proves the
post-upgrade repair path end to end FROM THE INSTALLED PACKAGE (never the source
checkout):

1. the installed CLI reports a version and runs as a module;
2. the shipped launcher renderer writes a launcher with NO self-injected source
   PYTHONPATH and a current contract stamp, and that launcher resolves the
   INSTALLED package version when run from a neutral cwd (the original
   stale-launcher bug: the launcher pinned a checkout via PYTHONPATH);
3. `doctor` flags a planted legacy launcher (the PYTHONPATH=<repo> form) as stale;
4. `sync-inject --heal-launchers` rewrites planted legacy launchers for
   Claude/Codex/OpenClaw/Hermes to the current clean contract, and a second run is
   idempotent;
5. `doctor` is clean after the heal.

No repo assets are needed at runtime — everything is driven through the installed
wheel, which is the whole point: the launcher must run what `pip` installed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import venv
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_cli(root: Path) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return root / ("Scripts" if os.name == "nt" else "bin") / f"unlimited-skills{suffix}"


def run(args: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, env=env,
    )


def require_ok(proc: subprocess.CompletedProcess[str], label: str) -> str:
    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed:\nSTDOUT:\n{proc.stdout[-1500:]}\nSTDERR:\n{proc.stderr[-1500:]}")
    return proc.stdout


def build_dist(dist_dir: Path) -> Path:
    require_ok(run(["python", "-m", "pip", "install", "--upgrade", "build"], cwd=ROOT), "install build")
    require_ok(run(["python", "-m", "build", "--wheel", "--outdir", str(dist_dir)], cwd=ROOT), "build wheel")
    wheels = sorted(dist_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one wheel, got {[w.name for w in wheels]}")
    return wheels[0]


_RENDER_AND_WRITE = (
    "import sys, json\n"
    "from unlimited_skills import __version__\n"
    "from unlimited_skills.launchers import write_launchers, LAUNCHER_CONTRACT_VERSION\n"
    "sh, lib = sys.argv[1], sys.argv[2]\n"
    "fb = write_launchers(sh_launcher=sh, python_executable=sys.executable, library_root=lib)\n"
    "print(json.dumps({'version': __version__, 'contract': LAUNCHER_CONTRACT_VERSION, 'fallback': fb}))\n"
)

_LEGACY_SH = (
    "#!/usr/bin/env bash\nset -euo pipefail\nexport PYTHONPATH=/old/repo\n"
    'exec /old/py -m unlimited_skills --root /old/lib "$@"\n'
)


def _bash() -> str | None:
    return shutil.which("bash") or shutil.which("/usr/bin/bash") or shutil.which("/bin/bash")


def _launcher_version(sh_path: Path, py: Path, neutral: Path) -> str:
    """Run the rendered launcher (or the module directly if no bash) and return its --version output."""
    bash = _bash()
    if bash is not None:
        proc = run([bash, str(sh_path), "--version"], cwd=neutral)
        if proc.returncode == 0:
            return proc.stdout.strip()
    return run([str(py), "-m", "unlimited_skills", "--version"], cwd=neutral).stdout.strip()


def _install_legacy_router(home: Path, *, ps: bool = False) -> Path:
    router = home / "skills" / "unlimited-skills"
    scripts = router / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (router / "SKILL.md").write_text("---\nname: unlimited-skills\n---\nrouter\n", encoding="utf-8")
    legacy = scripts / "unlimited-skills.sh"
    legacy.write_text(_LEGACY_SH, encoding="utf-8")
    if ps:
        (scripts / "unlimited-skills.ps1").write_text(
            "param()\n$env:PYTHONPATH='/old/repo'\n& /old/py -m unlimited_skills --root /old/lib @Args\n",
            encoding="utf-8",
        )
    return legacy


def _agent_heal_summary(heal: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {}
    for item in heal.get("launchers", []):
        if item.get("kind") == "sh":
            rows[item.get("agent", "")] = item
    return rows


def smoke(wheel: Path, work: Path) -> dict[str, Any]:
    env_dir = work / "venv"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    py = venv_python(env_dir)
    cli = venv_cli(env_dir)
    require_ok(run([str(py), "-m", "pip", "install", str(wheel)], cwd=work), "install wheel")

    installed_version = require_ok(run([str(cli), "--version"], cwd=work), "cli --version").strip()

    # (2) the shipped renderer writes a clean launcher; it resolves the installed version.
    scripts = work / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    sh_path = scripts / "unlimited-skills.sh"
    render = json.loads(
        require_ok(run([str(py), "-c", _RENDER_AND_WRITE, str(sh_path), str(work / "lib")], cwd=work), "render launcher")
    )
    launcher_text = sh_path.read_text(encoding="utf-8")
    neutral = work / "neutral"
    neutral.mkdir(exist_ok=True)
    launcher_version = _launcher_version(sh_path, py, neutral)

    # (3-5) doctor flags a planted legacy launcher; sync-inject --heal-launchers fixes it.
    claude_home = work / "claude-home"
    legacy_sh = _install_legacy_router(claude_home, ps=True)

    doctor_env = dict(os.environ)
    doctor_env["CLAUDE_HOME"] = str(claude_home)
    doctor_before = json.loads(
        require_ok(run([str(cli), "doctor", "--agent", "claude-code", "--json"], cwd=work, env=doctor_env), "doctor before")
    )

    heal = json.loads(
        require_ok(
            run(
                [str(cli), "sync-inject", "--heal-launchers", "--agent", "claude-code",
                 "--claude-home", str(claude_home), "--library-root", str(work / "lib"),
                 "--no-project", "--no-global", "--json"],
                cwd=work,
            ),
            "sync-inject --heal-launchers",
        )
    )
    healed_text = legacy_sh.read_text(encoding="utf-8")

    all_root = work / "all-agents"
    all_claude_home = all_root / "claude-home"
    all_codex_home = all_root / "codex-home"
    all_openclaw_home = all_root / "openclaw-home"
    all_openclaw_workspace = all_openclaw_home / "workspace"
    all_hermes_home = all_root / "hermes-home"
    project_root = all_root / "project"
    project_root.mkdir(parents=True)
    legacy_paths = {
        "claude-code": _install_legacy_router(all_claude_home, ps=True),
        "codex": _install_legacy_router(all_codex_home),
        "openclaw": _install_legacy_router(all_openclaw_workspace),
        "hermes": _install_legacy_router(all_hermes_home, ps=True),
    }

    all_heal = json.loads(
        require_ok(
            run(
                [str(cli), "sync-inject", "--heal-launchers",
                 "--claude-home", str(all_claude_home),
                 "--codex-home", str(all_codex_home),
                 "--openclaw-home", str(all_openclaw_home),
                 "--openclaw-workspace", str(all_openclaw_workspace),
                 "--hermes-home", str(all_hermes_home),
                 "--project-root", str(project_root),
                 "--library-root", str(work / "lib"),
                 "--no-project", "--no-global", "--json"],
                cwd=work,
            ),
            "sync-inject --heal-launchers (all agents)",
        )
    )
    all_rows = _agent_heal_summary(all_heal)
    all_heal2 = json.loads(
        require_ok(
            run(
                [str(cli), "sync-inject", "--heal-launchers",
                 "--claude-home", str(all_claude_home),
                 "--codex-home", str(all_codex_home),
                 "--openclaw-home", str(all_openclaw_home),
                 "--openclaw-workspace", str(all_openclaw_workspace),
                 "--hermes-home", str(all_hermes_home),
                 "--project-root", str(project_root),
                 "--library-root", str(work / "lib"),
                 "--no-project", "--no-global", "--json"],
                cwd=work,
            ),
            "sync-inject --heal-launchers (all agents, 2)",
        )
    )
    all_rows2 = _agent_heal_summary(all_heal2)

    heal2 = json.loads(
        require_ok(
            run(
                [str(cli), "sync-inject", "--heal-launchers", "--agent", "claude-code",
                 "--claude-home", str(claude_home), "--library-root", str(work / "lib"),
                 "--no-project", "--no-global", "--json"],
                cwd=work,
            ),
            "sync-inject --heal-launchers (2)",
        )
    )
    doctor_after = json.loads(
        require_ok(run([str(cli), "doctor", "--agent", "claude-code", "--json"], cwd=work, env=doctor_env), "doctor after")
    )

    sh_heal = next((l for l in heal["launchers"] if l["kind"] == "sh"), {})
    sh_heal2 = next((l for l in heal2["launchers"] if l["kind"] == "sh"), {})
    return {
        "installed_version": installed_version,
        "render_version": render["version"],
        "render_fallback": render["fallback"],
        "launcher_contract": render["contract"],
        "launcher_has_self_pythonpath": "export PYTHONPATH=" in launcher_text,
        "launcher_runs_installed_version": launcher_version,
        "doctor_before_launcher_stale": doctor_before["agents"]["claude-code"].get("launcher_stale"),
        "heal_from_contract": sh_heal.get("from_contract"),
        "heal_to_contract": sh_heal.get("to_contract"),
        "heal_changed": sh_heal.get("changed"),
        "healed_has_self_pythonpath": "export PYTHONPATH=" in healed_text,
        "heal_idempotent": sh_heal2.get("changed"),
        "all_agents_healed": sorted(all_rows),
        "all_agents_changed": {agent: row.get("changed") for agent, row in sorted(all_rows.items())},
        "all_agents_idempotent": {agent: row.get("changed") for agent, row in sorted(all_rows2.items())},
        "all_agents_still_clean": {
            agent: "export PYTHONPATH=" not in path.read_text(encoding="utf-8")
            for agent, path in sorted(legacy_paths.items())
        },
        "doctor_after_launcher_stale": doctor_after["agents"]["claude-code"].get("launcher_stale"),
    }


def verify_report(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    r = report.get("smoke", {})
    iv = r.get("installed_version", "")
    if not iv.startswith("unlimited-skills "):
        errors.append("installed CLI did not report a version")
    installed_ver = iv.split()[-1] if iv else ""
    if not installed_ver or r.get("render_version") != installed_ver:
        errors.append("renderer version does not match the installed package version")
    if r.get("render_fallback") is not None:
        errors.append("clean wheel install must render a launcher with no source PYTHONPATH fallback")
    if r.get("launcher_has_self_pythonpath") is not False:
        errors.append("written launcher must not self-inject a source PYTHONPATH (the stale-launcher bug)")
    # The launcher runs `-m unlimited_skills`, so argparse's prog is the module
    # name; the VERSION NUMBER is the proof it resolved the installed package.
    if not installed_ver or not r.get("launcher_runs_installed_version", "").endswith(installed_ver):
        errors.append("rendered launcher must resolve the INSTALLED package version, not a stale checkout")
    if r.get("doctor_before_launcher_stale") is not True:
        errors.append("doctor must flag the planted legacy launcher as stale")
    if r.get("heal_from_contract") != 0 or r.get("heal_to_contract") != r.get("launcher_contract"):
        errors.append("heal must upgrade the legacy launcher (contract 0) to the current contract")
    if r.get("heal_changed") is not True:
        errors.append("first heal must rewrite the legacy launcher")
    if r.get("healed_has_self_pythonpath") is not False:
        errors.append("healed launcher must not contain a self-injected source PYTHONPATH")
    if r.get("heal_idempotent") is not False:
        errors.append("second heal must be idempotent (no change)")
    expected_agents = ["claude-code", "codex", "hermes", "openclaw"]
    if r.get("all_agents_healed") != expected_agents:
        errors.append("live temp-agent smoke must cover Claude/Codex/OpenClaw/Hermes")
    if any(v is not True for v in (r.get("all_agents_changed") or {}).values()):
        errors.append("first all-agent heal must rewrite every planted legacy launcher")
    if any(v is not False for v in (r.get("all_agents_idempotent") or {}).values()):
        errors.append("second all-agent heal must be idempotent for every agent")
    if any(v is not True for v in (r.get("all_agents_still_clean") or {}).values()):
        errors.append("healed temp-agent launchers must not contain self-injected PYTHONPATH")
    if r.get("doctor_after_launcher_stale") is not False:
        errors.append("doctor must be clean after healing the launcher")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)

    tmp = Path(tempfile.mkdtemp(prefix="uls-r1-updater-smoke-"))
    try:
        dist_dir = tmp / "dist"
        dist_dir.mkdir()
        wheel = build_dist(dist_dir)
        report = {"schema_version": 1, "wheel": wheel.name, "smoke": smoke(wheel, tmp / "work")}
        report["errors"] = verify_report(report)
        report["ok"] = not report["errors"]
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print("R1 updater/launcher smoke: " + ("PASS" if report["ok"] else "FAIL"))
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
