#!/usr/bin/env python
"""Verify an exact Unlimited Skills release from the public PyPI index."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import venv
from pathlib import Path
from typing import Any

PACKAGE = "unlimited-skills"
PYPI_JSON = "https://pypi.org/pypi/{package}/{version}/json"
PYPI_SIMPLE = "https://pypi.org/simple"


class PublicIndexPropagationPending(RuntimeError):
    """The JSON API is live but the pip simple index has not caught up yet."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def fetch_release(version: str, *, timeout: float = 20.0) -> dict[str, Any] | None:
    url = PYPI_JSON.format(package=PACKAGE, version=version)
    request = urllib.request.Request(url, headers={"User-Agent": f"{PACKAGE}-publication-verifier/{version}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    require(isinstance(payload, dict), "PyPI version endpoint must return an object")
    return payload


def wait_for_release(
    version: str,
    *,
    wait_seconds: float = 300.0,
    poll_seconds: float = 5.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(wait_seconds, 0.0)
    while True:
        payload = fetch_release(version)
        if payload is not None:
            return payload
        if time.monotonic() >= deadline:
            raise RuntimeError(f"PyPI did not expose {PACKAGE}=={version} within {wait_seconds:g}s")
        time.sleep(max(min(poll_seconds, deadline - time.monotonic()), 0.1))


def venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_cli(root: Path) -> Path:
    return root / ("Scripts/unlimited-skills.exe" if os.name == "nt" else "bin/unlimited-skills")


def run(args: list[str], *, cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess[str]:
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


def checked(args: list[str], *, cwd: Path, label: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    proc = run(args, cwd=cwd, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"{label} failed ({proc.returncode})\nSTDOUT:\n{proc.stdout[-1600:]}\nSTDERR:\n{proc.stderr[-1600:]}"
        )
    return proc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pypi_payload(
    payload: dict[str, Any],
    version: str,
    *,
    dist_dir: Path | None = None,
) -> dict[str, Any]:
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    require(info.get("name") == PACKAGE, f"PyPI project name must be {PACKAGE}")
    require(info.get("version") == version, f"PyPI version must be {version}")
    urls = payload.get("urls") if isinstance(payload.get("urls"), list) else []
    filenames = [str(row.get("filename") or "") for row in urls if isinstance(row, dict)]
    require(any(name.endswith(".whl") for name in filenames), "PyPI release must contain a wheel")
    require(any(name.endswith(".tar.gz") for name in filenames), "PyPI release must contain an sdist")
    digest_verified = False
    if dist_dir is not None:
        local_files = sorted(
            path for path in dist_dir.iterdir() if path.is_file() and (path.name.endswith(".whl") or path.name.endswith(".tar.gz"))
        )
        require(local_files, f"no local distribution artifacts found in {dist_dir}")
        require(sorted(path.name for path in local_files) == sorted(filenames), "PyPI filenames must match local release artifacts exactly")
        remote_digests = {
            str(row.get("filename") or ""): str((row.get("digests") or {}).get("sha256") or "")
            for row in urls
            if isinstance(row, dict)
        }
        for path in local_files:
            require(remote_digests.get(path.name) == sha256_file(path), f"PyPI sha256 mismatch for {path.name}")
        digest_verified = True
    return {
        "project": info.get("name"),
        "version": info.get("version"),
        "filenames": filenames,
        "local_artifact_digests_verified": digest_verified,
    }


def clean_install_smoke(version: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="uls-pypi-publication-") as tmp:
        work = Path(tmp)
        env_dir = work / "venv"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        py = venv_python(env_dir)
        cli = venv_cli(env_dir)
        install = run(
            [
                str(py),
                "-m",
                "pip",
                "install",
                "--no-cache-dir",
                "--index-url",
                PYPI_SIMPLE,
                f"{PACKAGE}=={version}",
            ],
            cwd=work,
            timeout=900,
        )
        if install.returncode != 0:
            combined = f"{install.stdout}\n{install.stderr}"
            if "No matching distribution found" in combined or "Could not find a version that satisfies" in combined:
                raise PublicIndexPropagationPending(combined[-1600:])
            raise RuntimeError(
                f"install public wheel failed ({install.returncode})\nSTDOUT:\n{install.stdout[-1600:]}\nSTDERR:\n{install.stderr[-1600:]}"
            )

        version_output = checked([str(cli), "--version"], cwd=work, label="published CLI version").stdout.strip()
        require(version_output == f"unlimited-skills {version}", "installed CLI version mismatch")

        library = work / "library"
        quickstart = checked(
            [str(cli), "--root", str(library), "quickstart", "--json", "--skip-mcp-check"],
            cwd=work,
            label="published quickstart",
            timeout=300,
        )
        quickstart_payload = json.loads(quickstart.stdout)
        require(quickstart_payload.get("library", {}).get("skill_count", 0) >= 267, "published wheel must bundle 267+ skills")
        require(bool(quickstart_payload.get("search", {}).get("hits")), "published quickstart must prove retrieval")

        weak = checked(
            [str(cli), "--root", str(library), "suggest", "watering"],
            cwd=work,
            label="published below-floor silence",
        )
        require(not weak.stdout.strip(), "published suggest must suppress below-floor text matches")

        mixed = checked(
            [
                str(cli),
                "--root",
                str(library),
                "suggest",
                "проверить python api",
                "--json",
                "--card",
            ],
            cwd=work,
            label="published mixed-language rescue",
        )
        mixed_payload = json.loads(mixed.stdout)
        require(mixed_payload.get("delivery_tier") == 2, "mixed-language weak safe match must deliver NAME hints")
        require(mixed_payload.get("needs_english_query") is True, "mixed-language weak match must request English rescue")
        require(bool(mixed_payload.get("delivery_candidates")), "mixed-language weak match must expose safe candidates")
        require(not mixed_payload.get("skill_card"), "mixed-language uncertain matches must never inject a card")

        return {
            "version_output": version_output,
            "quickstart_skill_count": quickstart_payload["library"]["skill_count"],
            "quickstart_hit_count": len(quickstart_payload["search"]["hits"]),
            "below_floor_silent": True,
            "mixed_language_delivery_tier": mixed_payload.get("delivery_tier"),
            "mixed_language_needs_english_query": mixed_payload.get("needs_english_query"),
        }


def wait_for_clean_install(
    version: str,
    *,
    wait_seconds: float = 300.0,
    poll_seconds: float = 5.0,
) -> dict[str, Any]:
    """Retry only the known PyPI JSON/simple-index propagation race."""

    deadline = time.monotonic() + max(wait_seconds, 0.0)
    while True:
        try:
            return clean_install_smoke(version)
        except PublicIndexPropagationPending:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"PyPI simple index did not expose {PACKAGE}=={version} within {wait_seconds:g}s"
                )
            time.sleep(max(min(poll_seconds, deadline - time.monotonic()), 0.1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--wait-seconds", type=float, default=300.0)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--dist-dir", default="")
    parser.add_argument("--skip-clean-install", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = wait_for_release(
        args.version,
        wait_seconds=args.wait_seconds,
        poll_seconds=args.poll_seconds,
    )
    result = {
        "schema_version": 1,
        "status": "passed",
        "pypi": validate_pypi_payload(
            payload,
            args.version,
            dist_dir=Path(args.dist_dir).resolve() if args.dist_dir else None,
        ),
        "clean_install": None
        if args.skip_clean_install
        else wait_for_clean_install(
            args.version,
            wait_seconds=args.wait_seconds,
            poll_seconds=args.poll_seconds,
        ),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"PyPI publication verified: {PACKAGE}=={args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
