from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .registration import is_secure_or_local_url
from .updates import safe_extract_zip, sha256_file

DEFAULT_PUBLIC_REPO = "AI4sale/unlimited-skills"
DEFAULT_API_BASE = "https://api.github.com"
IGNORED_ARCHIVE_COPY_NAMES = {
    ".git",
    ".chroma-skills",
    ".learning",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".unlimited-skills-index.json",
    ".unlimited-skills-vector.json",
    ".venv",
    "__pycache__",
    "node_modules",
}


class SelfUpdateError(RuntimeError):
    """Raised when public repo self-update cannot be checked or applied."""


@dataclass(frozen=True)
class PublicRelease:
    tag: str
    name: str
    html_url: str
    zipball_url: str
    published_at: str
    body: str = ""

    @property
    def version(self) -> str:
        return normalize_version(self.tag)

    def to_json(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class SelfUpdateStatus:
    repo: str
    install_root: str
    current_version: str
    latest_version: str
    latest_tag: str
    update_available: bool
    is_git_checkout: bool
    dirty: bool
    current_ref: str
    release_url: str
    zipball_url: str
    published_at: str
    notes: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SelfUpdateResult:
    repo: str
    install_root: str
    from_version: str
    to_version: str
    ref: str
    method: str
    archive_sha256: str = ""
    reindex_recommended: bool = True

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def normalize_version(value: str) -> str:
    text = (value or "").strip()
    return text[1:] if text.lower().startswith("v") else text


def detect_install_root() -> Path:
    return Path(__file__).resolve().parents[1]


def release_api_url(repo: str, api_base: str = DEFAULT_API_BASE) -> str:
    return f"{api_base.rstrip('/')}/repos/{repo}/releases/latest"


def tags_api_url(repo: str, api_base: str = DEFAULT_API_BASE) -> str:
    return f"{api_base.rstrip('/')}/repos/{repo}/tags"


def fetch_latest_release(repo: str = DEFAULT_PUBLIC_REPO, *, api_base: str = DEFAULT_API_BASE, timeout: float = 30.0) -> PublicRelease:
    url = release_api_url(repo, api_base)
    if not is_secure_or_local_url(url):
        raise SelfUpdateError("Public repo release API URL must use HTTPS. Plain HTTP is allowed only for localhost development.")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"unlimited-skills/{__version__}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return fetch_latest_tag_as_release(repo, api_base=api_base, timeout=timeout)
        message = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise SelfUpdateError(f"GitHub releases returned HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise SelfUpdateError(f"GitHub releases are unreachable: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise SelfUpdateError("GitHub releases returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise SelfUpdateError("GitHub releases returned a non-object JSON payload.")
    return release_from_json(data)


def fetch_latest_tag_as_release(repo: str = DEFAULT_PUBLIC_REPO, *, api_base: str = DEFAULT_API_BASE, timeout: float = 30.0) -> PublicRelease:
    url = tags_api_url(repo, api_base)
    if not is_secure_or_local_url(url):
        raise SelfUpdateError("Public repo tags API URL must use HTTPS. Plain HTTP is allowed only for localhost development.")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"unlimited-skills/{__version__}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise SelfUpdateError(f"GitHub tags returned HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise SelfUpdateError(f"GitHub tags are unreachable: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise SelfUpdateError("GitHub tags returned invalid JSON.") from exc
    if not isinstance(data, list) or not data:
        raise SelfUpdateError("Public repo has no GitHub releases or tags yet.")
    first = data[0]
    if not isinstance(first, dict):
        raise SelfUpdateError("GitHub tags returned an invalid tag payload.")
    tag = str(first.get("name") or "")
    zipball_url = str(first.get("zipball_url") or "")
    if not tag or not zipball_url:
        raise SelfUpdateError("Latest tag must include name and zipball_url.")
    return PublicRelease(
        tag=tag,
        name=tag,
        html_url=f"https://github.com/{repo}/releases/tag/{tag}",
        zipball_url=zipball_url,
        published_at="",
        body="Latest GitHub tag. Create GitHub Releases to provide release notes.",
    )


def release_from_json(data: dict[str, Any]) -> PublicRelease:
    tag = str(data.get("tag_name") or "")
    zipball_url = str(data.get("zipball_url") or "")
    if not tag or not zipball_url:
        raise SelfUpdateError("Latest release must include tag_name and zipball_url.")
    return PublicRelease(
        tag=tag,
        name=str(data.get("name") or tag),
        html_url=str(data.get("html_url") or ""),
        zipball_url=zipball_url,
        published_at=str(data.get("published_at") or ""),
        body=str(data.get("body") or ""),
    )


def run_git(root: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise SelfUpdateError(f"git {' '.join(args)} failed: {message}")
    return completed


def is_git_checkout(root: Path) -> bool:
    completed = run_git(root, ["rev-parse", "--is-inside-work-tree"], check=False)
    return completed.returncode == 0 and completed.stdout.strip() == "true"


def git_current_ref(root: Path) -> str:
    completed = run_git(root, ["rev-parse", "--short", "HEAD"], check=False)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def git_dirty(root: Path) -> bool:
    completed = run_git(root, ["status", "--porcelain"], check=False)
    return completed.returncode == 0 and bool(completed.stdout.strip())


def check_public_repo_update(
    *,
    repo: str = DEFAULT_PUBLIC_REPO,
    install_root: Path | None = None,
    timeout: float = 30.0,
    api_base: str = DEFAULT_API_BASE,
) -> SelfUpdateStatus:
    root = (install_root or detect_install_root()).expanduser()
    current = normalize_version(__version__)
    git_checkout = is_git_checkout(root)
    try:
        release = fetch_latest_release(repo, api_base=api_base, timeout=timeout)
    except SelfUpdateError as exc:
        if "no GitHub releases or tags yet" not in str(exc):
            raise
        return SelfUpdateStatus(
            repo=repo,
            install_root=str(root),
            current_version=current,
            latest_version=current,
            latest_tag="",
            update_available=False,
            is_git_checkout=git_checkout,
            dirty=git_dirty(root) if git_checkout else False,
            current_ref=git_current_ref(root) if git_checkout else "",
            release_url="",
            zipball_url="",
            published_at="",
            notes="Public repo has no GitHub releases or tags yet.",
        )
    latest = release.version
    return SelfUpdateStatus(
        repo=repo,
        install_root=str(root),
        current_version=current,
        latest_version=latest,
        latest_tag=release.tag,
        update_available=current != latest,
        is_git_checkout=git_checkout,
        dirty=git_dirty(root) if git_checkout else False,
        current_ref=git_current_ref(root) if git_checkout else "",
        release_url=release.html_url,
        zipball_url=release.zipball_url,
        published_at=release.published_at,
        notes=release.body[:1000],
    )


def _post_upgrade_repair() -> None:
    """First thing after an upgrade: deliver/repair the runtime extras via doctor.

    Runs the freshly-updated CLI (`doctor --fix`) in a subprocess so the new
    repair logic applies and the native-language search extras ([server]+[vector])
    are present. Best-effort and fully guarded — a repair failure must NEVER turn
    a successful upgrade into an error.
    """
    try:
        subprocess.run(
            [sys.executable, "-m", "unlimited_skills", "doctor", "--fix", "--json"],
            capture_output=True,
            timeout=600,
        )
    except Exception:
        return


def apply_public_repo_update(
    status: SelfUpdateStatus,
    *,
    allow_dirty: bool = False,
    method: str = "auto",
    timeout: float = 30.0,
) -> SelfUpdateResult:
    root = Path(status.install_root).expanduser()
    if not status.update_available:
        return SelfUpdateResult(
            repo=status.repo,
            install_root=str(root),
            from_version=status.current_version,
            to_version=status.latest_version,
            ref=status.latest_tag,
            method="none",
            reindex_recommended=False,
        )
    if method not in {"auto", "git", "archive"}:
        raise SelfUpdateError("Self-update method must be one of: auto, git, archive.")
    if status.is_git_checkout and status.dirty and not allow_dirty:
        raise SelfUpdateError("Install root has uncommitted git changes. Commit/stash them or pass --allow-dirty.")
    if method in {"auto", "git"} and status.is_git_checkout:
        apply_git_release(root, status.latest_tag)
        _post_upgrade_repair()
        return SelfUpdateResult(
            repo=status.repo,
            install_root=str(root),
            from_version=status.current_version,
            to_version=status.latest_version,
            ref=status.latest_tag,
            method="git",
        )
    if method == "git":
        raise SelfUpdateError("Install root is not a git checkout; use --method archive or reinstall from the public repo.")
    digest = apply_archive_release(root, status.zipball_url, timeout=timeout)
    _post_upgrade_repair()
    return SelfUpdateResult(
        repo=status.repo,
        install_root=str(root),
        from_version=status.current_version,
        to_version=status.latest_version,
        ref=status.latest_tag,
        method="archive",
        archive_sha256=digest,
    )


def apply_git_release(root: Path, tag: str) -> None:
    safe_ref = validate_git_ref(tag)
    run_git(root, ["fetch", "--tags", "origin"])
    run_git(root, ["checkout", safe_ref])


def validate_git_ref(ref: str) -> str:
    value = ref.strip()
    if not value or not re.match(r"^[A-Za-z0-9][A-Za-z0-9._/@+-]{0,200}$", value):
        raise SelfUpdateError(f"Unsafe git ref: {ref}")
    if ".." in value or value.endswith(".lock"):
        raise SelfUpdateError(f"Unsafe git ref: {ref}")
    return value


def apply_archive_release(root: Path, zipball_url: str, *, timeout: float = 30.0) -> str:
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="unlimited-skills-self-update-") as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / "source.zip"
        download_release_archive(zipball_url, archive, timeout=timeout)
        digest = sha256_file(archive)
        extracted = tmp_path / "extracted"
        safe_extract_zip(archive, extracted)
        source = resolve_source_archive_root(extracted)
        copy_archive_tree(source, root)
        return digest


def download_release_archive(url: str, target: Path, *, timeout: float = 30.0) -> None:
    if not is_secure_or_local_url(url):
        raise SelfUpdateError("Public repo release archive URL must use HTTPS. Plain HTTP is allowed only for localhost development.")
    request = urllib.request.Request(url, headers={"User-Agent": f"unlimited-skills/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            with target.open("wb") as handle:
                shutil.copyfileobj(response, handle)
    except urllib.error.URLError as exc:
        raise SelfUpdateError(f"Cannot download public repo release archive: {exc.reason}") from exc


def resolve_source_archive_root(extracted: Path) -> Path:
    if (extracted / "pyproject.toml").is_file() and (extracted / "unlimited_skills").is_dir():
        return extracted
    candidates = [path for path in extracted.iterdir() if path.is_dir() and (path / "pyproject.toml").is_file() and (path / "unlimited_skills").is_dir()]
    if len(candidates) != 1:
        raise SelfUpdateError("Release archive must contain the unlimited-skills repository root.")
    return candidates[0]


def copy_archive_tree(source: Path, target: Path) -> None:
    for item in source.iterdir():
        if item.name in IGNORED_ARCHIVE_COPY_NAMES:
            continue
        destination = target / item.name
        if item.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(item, destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
