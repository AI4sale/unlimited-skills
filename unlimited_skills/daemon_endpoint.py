"""Deterministic loopback endpoint selection for the warm search daemon."""
from __future__ import annotations

import hashlib
import os
import urllib.parse
from pathlib import Path

DEFAULT_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_DAEMON_URL = "http://127.0.0.1:8765"
HASHED_PORT_BASE = 18000
HASHED_PORT_SPAN = 1000


def warm_daemon_url(root: Path, model: str = DEFAULT_EMBED_MODEL) -> str:
    explicit = os.environ.get("UNLIMITED_SKILLS_WARM_DAEMON_URL", "").strip()
    if explicit:
        candidate = explicit.rstrip("/")
        try:
            parsed = urllib.parse.urlparse(candidate)
            if (
                parsed.scheme == "http"
                and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                and parsed.username is None
                and parsed.password is None
                and parsed.path in {"", "/"}
                and not parsed.params
                and not parsed.query
                and not parsed.fragment
            ):
                return candidate
        except ValueError:
            pass
        return ""
    resolved = root.expanduser().resolve()
    default_root = (Path.home() / ".unlimited-skills" / "library").resolve()
    if resolved == default_root:
        return DEFAULT_DAEMON_URL
    identity = f"{os.path.normcase(str(resolved))}\0{model}".encode("utf-8")
    port = HASHED_PORT_BASE + (int(hashlib.sha256(identity).hexdigest()[:8], 16) % HASHED_PORT_SPAN)
    return f"http://127.0.0.1:{port}"
