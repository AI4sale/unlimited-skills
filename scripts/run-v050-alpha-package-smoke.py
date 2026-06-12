"""Build and clean-install smoke for the v0.5.0 public alpha package.

Run with:

    python -m pip install build twine
    python scripts/run-v050-alpha-package-smoke.py --json

The smoke intentionally installs the built wheel into a fresh virtual
environment and exercises the first-value path from the installed package,
not from the checkout.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.5.0"
MIN_BUNDLED_SKILLS = 250


def run(cmd: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(
            "Command failed: "
            + " ".join(cmd)
            + f"\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def venv_script(root: Path, name: str) -> Path:
    if os.name == "nt":
        return root / "Scripts" / f"{name}.exe"
    return root / "bin" / name


def build_dist(out: Path) -> tuple[Path, Path]:
    run([sys.executable, "-m", "build", "--outdir", str(out)])
    run([sys.executable, "-m", "twine", "check", *[str(path) for path in sorted(out.iterdir())]])
    wheel = next(out.glob("unlimited_skills-*.whl"))
    sdist = next(out.glob("unlimited_skills-*.tar.gz"))
    return wheel, sdist


def inspect_dist(wheel: Path, sdist: Path) -> dict[str, Any]:
    with zipfile.ZipFile(wheel) as zf:
        wheel_names = zf.namelist()
        metadata_name = next(name for name in wheel_names if name.endswith(".dist-info/METADATA"))
        metadata = zf.read(metadata_name).decode("utf-8", errors="replace")
    with tarfile.open(sdist, "r:gz") as tf:
        sdist_names = tf.getnames()
        pkg_info_name = next(name for name in sdist_names if name.endswith("/PKG-INFO"))
        pkg_info = tf.extractfile(pkg_info_name).read().decode("utf-8", errors="replace")  # type: ignore[union-attr]
    wheel_skill_files = [name for name in wheel_names if name.startswith("unlimited_skills/bundled_packs/") and name.endswith("/SKILL.md")]
    ecc = [name for name in wheel_skill_files if "/ecc/skills/" in name]
    superpowers = [name for name in wheel_skill_files if "/superpowers/skills/" in name]
    forbidden_names = [
        name
        for name in wheel_names + sdist_names
        if any(part in name.lower() for part in ("registry/private", ".env", "id_rsa", "private_key", "secret.pem"))
    ]
    required_metadata = [
        "Project-URL: Homepage, https://github.com/AI4sale/unlimited-skills",
        "Project-URL: Repository, https://github.com/AI4sale/unlimited-skills",
        "Project-URL: Issues, https://github.com/AI4sale/unlimited-skills/issues",
    ]
    return {
        "wheel": str(wheel),
        "sdist": str(sdist),
        "wheel_file_count": len(wheel_names),
        "sdist_file_count": len(sdist_names),
        "wheel_skill_count": len(wheel_skill_files),
        "wheel_ecc_skill_count": len(ecc),
        "wheel_superpowers_skill_count": len(superpowers),
        "sdist_has_packs": any("/packs/ecc/skills/" in name for name in sdist_names),
        "forbidden_file_names": forbidden_names,
        "metadata_has_urls": all(item in metadata for item in required_metadata),
        "metadata_mentions_version": f"Version: {VERSION}" in metadata,
        "metadata_has_license_classifier": "Classifier: License :: OSI Approved :: MIT License" in metadata,
        "long_description_has_flip_marker": "A3-PYPI-FLIP" in metadata or "A3-PYPI-FLIP" in pkg_info,
        "long_description_has_git_install": "git+https://" in metadata or "git+https://" in pkg_info,
        "long_description_has_not_on_pypi": (
            "not published on PyPI" in metadata
            or "not on PyPI" in metadata
            or "not published on PyPI" in pkg_info
            or "not on PyPI" in pkg_info
        ),
    }


def clean_install_smoke(wheel: Path, work: Path) -> dict[str, Any]:
    env_dir = work / "venv"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    py = venv_python(env_dir)
    cli = venv_script(env_dir, "unlimited-skills")
    run([str(py), "-m", "pip", "install", str(wheel)], cwd=work)
    version = run([str(cli), "--version"], cwd=work).stdout.strip()
    library = work / "library"
    missing_claude = work / "missing-claude.json"
    quickstart = run(
        [
            str(py),
            "-m",
            "unlimited_skills",
            "--root",
            str(library),
            "quickstart",
            "--json",
            "--claude-config",
            str(missing_claude),
            "--timeout",
            "2",
        ],
        cwd=work,
    )
    quickstart_payload = json.loads(quickstart.stdout)
    suggest = run(
        [
            str(py),
            "-m",
            "unlimited_skills",
            "--root",
            str(library),
            "suggest",
            "review a pull request for security issues",
            "--json",
        ],
        cwd=work,
    )
    suggest_payload = json.loads(suggest.stdout)
    savings = run(
        [
            str(py),
            "-m",
            "unlimited_skills",
            "mcp",
            "savings",
            "--json",
            "--claude-config",
            str(missing_claude),
            "--timeout",
            "2",
        ],
        cwd=work,
    )
    savings_payload = json.loads(savings.stdout)
    return {
        "version_output": version,
        "quickstart_library": quickstart_payload["library"],
        "quickstart_hit_count": len(quickstart_payload["search"]["hits"]),
        "quickstart_root": quickstart_payload["root"],
        "suggest_reason_code": suggest_payload.get("reason_code"),
        "suggest_candidates": len(suggest_payload.get("top_3_skill_candidates") or []),
        "savings_has_benchmark": "benchmark" in savings_payload,
    }


def verify(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    dist = report["dist"]
    install = report["clean_install"]
    if dist["wheel_skill_count"] < MIN_BUNDLED_SKILLS:
        errors.append(f"wheel must include at least {MIN_BUNDLED_SKILLS} bundled skills")
    if not dist["wheel_ecc_skill_count"]:
        errors.append("wheel must include bundled ecc skills")
    if not dist["wheel_superpowers_skill_count"]:
        errors.append("wheel must include bundled superpowers skills")
    if not dist["sdist_has_packs"]:
        errors.append("sdist must include source packs")
    if dist["forbidden_file_names"]:
        errors.append("distribution contains forbidden private-looking filenames")
    if not dist["metadata_has_urls"]:
        errors.append("METADATA must include project URLs")
    if not dist["metadata_mentions_version"]:
        errors.append(f"METADATA must mention version {VERSION}")
    if dist["metadata_has_license_classifier"]:
        errors.append("deprecated MIT license classifier must be absent")
    if dist["long_description_has_flip_marker"]:
        errors.append("built long description must not contain A3-PYPI-FLIP")
    if dist["long_description_has_git_install"]:
        errors.append("built long description must not contain git+ install instructions")
    if dist["long_description_has_not_on_pypi"]:
        errors.append("built long description must not say the package is not on PyPI")
    if install["version_output"] != f"unlimited-skills {VERSION}":
        errors.append("installed CLI version output mismatch")
    if install["quickstart_library"]["status"] != "imported":
        errors.append("clean install quickstart must import bundled packs")
    if install["quickstart_library"]["skill_count"] < MIN_BUNDLED_SKILLS:
        errors.append("clean install quickstart imported too few skills")
    if install["quickstart_hit_count"] < 1:
        errors.append("clean install quickstart must return a first-search hit")
    if install["quickstart_root"] != "<local-library>":
        errors.append("quickstart JSON must redact the local library path")
    if install["suggest_candidates"] < 1:
        errors.append("clean install suggest must return at least one candidate")
    if not install["savings_has_benchmark"]:
        errors.append("clean install mcp savings must return the lab benchmark without config")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)

    tmp = Path(tempfile.mkdtemp(prefix="uls-v050-package-smoke-"))
    try:
        dist_dir = tmp / "dist"
        dist_dir.mkdir()
        wheel, sdist = build_dist(dist_dir)
        report = {
            "schema_version": 1,
            "version": VERSION,
            "dist": inspect_dist(wheel, sdist),
            "clean_install": clean_install_smoke(wheel, tmp / "install"),
        }
        report["errors"] = verify(report)
        report["ok"] = not report["errors"]
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print("v0.5.0-alpha package smoke: " + ("PASS" if report["ok"] else "FAIL"))
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
