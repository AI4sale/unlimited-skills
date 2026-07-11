#!/usr/bin/env python
"""Prove live 0.6.4.post1 daemon rollover to the exact 0.6.6 wheel."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "0.6.4.post1"


def python_in(venv_root: Path) -> Path:
    return venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(args: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 1200) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {args}\n{proc.stdout[-1200:]}\n{proc.stderr[-1200:]}")
    return proc


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def health(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=1.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def wait_health(url: str, predicate, seconds: float = 90.0) -> dict:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        payload = health(url)
        if payload is not None and predicate(payload):
            return payload
        time.sleep(0.25)
    raise RuntimeError(f"health timeout: {url}")


def semantic_search(url: str, query: str) -> dict:
    request = urllib.request.Request(
        f"{url}/search",
        data=json.dumps({"query": query, "mode": "vector", "limit": 5, "require_vector": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30.0) as response:
        return json.loads(response.read().decode("utf-8"))


def stop_pid(pid: int | None) -> None:
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=20)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    wheel = Path(args.wheel).resolve()
    work = Path(tempfile.mkdtemp(prefix="uls-v066-rollover-"))
    legacy: subprocess.Popen | None = None
    current_pid: int | None = None
    try:
        env_root = work / "venv"
        venv.EnvBuilder(with_pip=True).create(env_root)
        py = python_in(env_root)
        run([str(py), "-m", "pip", "install", "--no-cache-dir", "--index-url", "https://pypi.org/simple", f"unlimited-skills[all]=={BASELINE}"], cwd=work)
        library = work / "library"
        run([str(py), "-m", "unlimited_skills", "--root", str(library), "quickstart", "--skip-mcp-check", "--json"], cwd=work)
        run([str(py), "-m", "unlimited_skills", "--root", str(library), "vector-reindex"], cwd=work)
        port = free_port()
        preferred = f"http://127.0.0.1:{port}"
        legacy = subprocess.Popen(
            [str(py), "-m", "unlimited_skills", "--root", str(library), "serve", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=work,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        legacy_health = wait_health(preferred, lambda row: row.get("ok") is True)
        if legacy_health.get("runtime_contract_version") == 2:
            raise RuntimeError("official baseline unexpectedly exposes current runtime contract")

        run([str(py), "-m", "pip", "install", "--upgrade", str(wheel) + "[all]"], cwd=work)
        home = work / "home"
        env = dict(os.environ)
        env.update(
            {
                "UNLIMITED_SKILLS_HOME": str(home),
                "UNLIMITED_SKILLS_ROOT": str(library),
                "UNLIMITED_SKILLS_WARM_DAEMON_URL": preferred,
                "UNLIMITED_SKILLS_CLI": f'"{py}" -m unlimited_skills --root "{library}"',
            }
        )
        env.pop("UNLIMITED_SKILLS_NO_AUTOSERVE", None)
        run([str(py), str(ROOT / "plugin" / "hooks" / "session_start.py")], cwd=ROOT, env=env, timeout=30)
        code = "from pathlib import Path; from unlimited_skills.daemon_endpoint import warm_daemon_urls; import json; print(json.dumps(warm_daemon_urls(Path(r'%s'))))" % str(library).replace("'", "\\'")
        urls = json.loads(run([str(py), "-c", code], cwd=work, env=env).stdout)
        fallback = urls[1]
        current_health = wait_health(
            fallback,
            lambda row: row.get("ok") is True and row.get("runtime_contract_version") == 2,
        )
        state_files = sorted((home / "runtime").glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        state = json.loads(state_files[0].read_text(encoding="utf-8"))
        current_pid = int(state.get("pid") or 0) or None
        suggest = json.loads(
            run(
                [str(py), "-m", "unlimited_skills", "--root", str(library), "suggest", "проверь безопасность кода и уязвимости аутентификации", "--json", "--card", "--limit", "5"],
                cwd=work,
                env=env,
            ).stdout
        )
        delivered = [row.get("name") for row in suggest.get("delivery_candidates") or []]
        if not delivered:
            direct = semantic_search(fallback, "проверь безопасность кода и уязвимости аутентификации")
            raise RuntimeError(
                "current fallback daemon returned no semantic delivery candidates: "
                + json.dumps({"suggest": suggest, "direct": direct}, ensure_ascii=False)[:4000]
            )
        result = {
            "ok": True,
            "baseline": BASELINE,
            "legacy_health_has_runtime_contract": "runtime_contract_version" in legacy_health,
            "preferred_endpoint_occupied_by_legacy": health(preferred) is not None,
            "fallback_endpoint": fallback,
            "current_runtime_contract_version": current_health.get("runtime_contract_version"),
            "current_package_version": current_health.get("package_version"),
            "root_matches": Path(current_health.get("root", "")).resolve() == library.resolve(),
            "pid_recorded": current_pid is not None,
            "delivery_candidates": delivered,
            "vector_status": suggest.get("vector_status"),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else "v0.6.6 daemon rollover: PASS")
        return 0
    finally:
        stop_pid(current_pid)
        if legacy is not None:
            try:
                legacy.terminate()
                legacy.wait(timeout=10)
            except Exception:
                stop_pid(legacy.pid)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
