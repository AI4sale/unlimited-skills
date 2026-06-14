"""Local MCP profile bundle publisher and signing ceremony (E19, dev/fixture only).

Turns a raw E09/E10 tool-profile file into a SIGNED profile bundle package
(`docs/mcp-signed-profile-bundles.md` format, verified by
`unlimited_skills/mcp/bundles.py`) entirely on the local machine:

    raw profile -> validate -> sign -> package -> verify -> handoff bundle

Hard boundaries, by construction:

- **Dev/fixture keys only.** ``keygen`` produces a clearly marked
  ``DEV KEY -- do not use in production`` Ed25519 keypair for local
  ceremonies, fixtures, and team pilots. Production signing keys are
  explicitly out of scope and are never generated, requested, or handled
  here.
- **Private-key hygiene.** The private key exists ONLY in the keygen
  ``--out`` directory. Its bytes never appear in the bundle, the manifest,
  the validation report, the rollback metadata, stdout, stderr, logs, or
  audit rows -- results carry paths, fingerprints, and hashes only.
- **The real verification path.** The ceremony's verify step (and the
  automatic post-package self-check) is :func:`resolve_bundle_state` from
  E14 -- never a reimplementation, never a bypass. A bundle that does not
  verify is never left on disk: packaging is atomic (temp file +
  ``os.replace``) and any ceremony failure removes the unsigned temp.
- **Offline.** No network, no registry sync, no hosted calls, no telemetry.

Canonicalization is :func:`canonical_bundle_bytes` (the normative E13/E14
signing input), reused -- not duplicated. Profile validation is the real
E09/E10 loader (:func:`load_profile_document`). The PUBLIC half of a keygen
pair is emitted in the ``mcp trust import --key-file`` format so the
ceremony hands the public key straight to the E15 managed trust store.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .bundles import (
    AUDIENCE_RE,
    BUNDLE_AUDIENCE_MISMATCH,
    BUNDLE_EXPIRED,
    BUNDLE_KEY_MISSING,
    BUNDLE_REVOKED,
    BUNDLE_SIGNATURE_INVALID,
    ED25519_PUBLIC_KEY_BYTES,
    MAX_AUDIENCE,
    MAX_DISPLAY_LENGTH,
    MAX_NAMESPACES,
    BundleFailClosed,
    canonical_bundle_bytes,
    resolve_bundle_state,
)
from .profiles import (
    KEY_ID_RE,
    MAX_KEY_ID_LENGTH,
    PROFILE_INVALID,
    PROFILE_NOT_FOUND,
    RULE_RE,
    ActiveProfile,
    ProfileLoadError,
    _rule_covered,
    load_profile_document,
)
from .trust_store import SHA256_RE, _atomic_write_json, key_fingerprint

PUBLISHER_VERSION = 1
ED25519_SEED_BYTES = 32

DEV_KEY_WARNING = "DEV KEY -- do not use in production"
SIGNING_KEY_FORMAT = "unlimited-skills-dev-signing-key"
PUBLIC_KEY_FORMAT = "unlimited-skills-trusted-key"

BUNDLE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

DEFAULT_EXPIRES_DAYS = 30
DEFAULT_ISSUER_DISPLAY = "Local dev bundle issuer (DEV KEY)"

BUNDLE_SUFFIX = ".bundle.json"
MANIFEST_SUFFIX = ".MANIFEST.json"
VALIDATION_REPORT_SUFFIX = ".VALIDATION-REPORT.json"
ROLLBACK_SUFFIX = ".ROLLBACK.json"

REFUSAL_NAMES = {
    PROFILE_NOT_FOUND: "profile_not_found",
    PROFILE_INVALID: "profile_invalid",
    BUNDLE_SIGNATURE_INVALID: "bundle_signature_invalid",
    BUNDLE_EXPIRED: "bundle_expired",
    BUNDLE_REVOKED: "bundle_revoked",
    BUNDLE_AUDIENCE_MISMATCH: "bundle_audience_mismatch",
    BUNDLE_KEY_MISSING: "bundle_key_missing",
}


class PublisherError(ValueError):
    """The ceremony was refused; no signed bundle was written."""


def _utc_text(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cryptography_available() -> bool:
    """True when the optional ``cryptography`` package can do real Ed25519."""
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401
    except Exception:  # pragma: no cover - exercised only without cryptography
        return False
    return True


def _require_cryptography(action: str) -> None:
    if not cryptography_available():
        raise PublisherError(
            f"{action} needs the optional 'cryptography' package for real Ed25519 "
            "signing (pip install cryptography); refusing -- there is no fallback "
            "signature scheme and nothing was written"
        )


def _validate_key_id(key_id: str) -> str:
    if (
        not isinstance(key_id, str)
        or not 1 <= len(key_id) <= MAX_KEY_ID_LENGTH
        or not KEY_ID_RE.match(key_id)
    ):
        raise PublisherError("key_id must be a bounded opaque identifier (E09 key_id grammar)")
    return key_id


# ---------------------------------------------------------------------------
# keygen: a DEV/FIXTURE Ed25519 keypair. The private key is written ONLY to
# the operator-specified out directory; the public half is emitted in the
# `mcp trust import --key-file` format.


def generate_keypair(
    out_dir: Path,
    key_id: str = "dev-signing-key",
    display: str = "",
    force: bool = False,
    now: float | None = None,
) -> dict:
    """Generate a DEV/FIXTURE Ed25519 keypair into ``out_dir``.

    Writes ``<key_id>.signing-key.json`` (PRIVATE -- loud DEV warning header,
    best-effort restrictive permissions; the ONLY place the private key ever
    exists) and ``<key_id>.public-key.json`` (PUBLIC -- the trust-store
    import format). The result carries paths and the abbreviated fingerprint
    only, never key material.
    """
    import time as _time

    if now is None:
        now = _time.time()
    _require_cryptography("mcp bundle keygen")
    key_id = _validate_key_id(key_id)
    display = display or f"{key_id} (DEV)"
    if len(display) > MAX_DISPLAY_LENGTH:
        raise PublisherError(f"display must be at most {MAX_DISPLAY_LENGTH} characters")

    out = Path(out_dir).expanduser()
    private_path = out / f"{key_id}.signing-key.json"
    public_path = out / f"{key_id}.public-key.json"
    if not force:
        collisions = [path.name for path in (private_path, public_path) if path.exists()]
        if collisions:
            raise PublisherError(
                f"keygen out dir already contains {', '.join(collisions)}; pass --force "
                "to overwrite (nothing was written)"
            )

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    private = Ed25519PrivateKey.generate()
    seed = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    fingerprint = key_fingerprint(public)
    created_at = _utc_text(now)

    private_document = {
        "warning": DEV_KEY_WARNING,
        "format": SIGNING_KEY_FORMAT,
        "schema_version": 1,
        "key_id": key_id,
        "algorithm": "ed25519",
        "private_key": base64.b64encode(seed).decode("ascii"),
        "public_key": base64.b64encode(public).decode("ascii"),
        "created_at": created_at,
        "comment": (
            "Dev/fixture signing key generated by 'unlimited-skills mcp bundle keygen'. "
            "Never import it into a trust store, never commit it, never publish it."
        ),
    }
    private_text = (
        f"# {DEV_KEY_WARNING}\n"
        "# unlimited-skills dev/fixture Ed25519 SIGNING key (E19 ceremony).\n"
        "# This file contains PRIVATE key material. It must never leave this\n"
        "# directory: never import it, never commit it, never share it.\n"
        + json.dumps(private_document, ensure_ascii=False, indent=2)
        + "\n"
    )
    public_document = {
        "format": PUBLIC_KEY_FORMAT,
        "key_id": key_id,
        "algorithm": "ed25519",
        "public_key": base64.b64encode(public).decode("ascii"),
        "display": display,
        "comment": f"PUBLIC half of dev keypair {key_id!r} ({DEV_KEY_WARNING}); "
        "import with: unlimited-skills mcp trust import --key-file <this file>",
    }

    out.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=private_path.name + ".", suffix=".tmp", dir=str(out)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(private_text)
        try:  # restrictive perms, best-effort (POSIX bits; advisory on Windows)
            os.chmod(tmp_name, 0o600)
        except OSError:  # pragma: no cover - exotic filesystems
            pass
        os.replace(tmp_name, private_path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    _atomic_write_json(public_path, public_document)
    return {
        "generated": True,
        "dev_only": True,
        "warning": DEV_KEY_WARNING,
        "key_id": key_id,
        "algorithm": "ed25519",
        "fingerprint": fingerprint,
        "created_at": created_at,
        "private_key_path": str(private_path),
        "public_key_path": str(public_path),
        "trust_import_command": (
            f"unlimited-skills mcp trust import --key-file {public_path.name}"
        ),
    }


# ---------------------------------------------------------------------------
# Signing-key loading (publish input). Refuses anything that is not the
# keygen private format -- in particular files that look PUBLIC-only.


@dataclass(frozen=True)
class SigningKey:
    key_id: str
    seed: bytes
    public_key: bytes

    @property
    def fingerprint(self) -> str:
        return key_fingerprint(self.public_key)


def load_signing_key(path: Path) -> SigningKey:
    """Load a keygen-produced DEV signing key for the publish step.

    Refusals (nothing signed is ever written): missing/unreadable file,
    non-JSON content, a file that looks PUBLIC-only (the keygen public file,
    a trusted-keys file, or anything without private material), wrong
    algorithm, or private material that is not a raw 32-byte Ed25519 seed.
    """
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        raise PublisherError(
            f"signing key file {path.name} is missing or unreadable"
        ) from None
    body = "\n".join(
        line for line in raw.splitlines() if not line.lstrip().startswith("#")
    )
    try:
        document = json.loads(body)
    except json.JSONDecodeError:
        raise PublisherError(
            f"signing key file {path.name} is not a keygen signing-key file (not valid JSON)"
        ) from None
    if not isinstance(document, dict):
        raise PublisherError(f"signing key file {path.name} must be a JSON object")
    if "private_key" not in document:
        if "public_key" in document or "keys" in document:
            raise PublisherError(
                f"signing key file {path.name} looks like a PUBLIC key file (no "
                "private material); publish needs the PRIVATE signing key written by "
                "'unlimited-skills mcp bundle keygen' -- the public half belongs in "
                "the trust store, not here"
            )
        raise PublisherError(
            f"signing key file {path.name} has no private_key field; expected the "
            "keygen signing-key format"
        )
    if document.get("algorithm") != "ed25519":
        raise PublisherError(f"signing key file {path.name}: algorithm must be 'ed25519'")
    key_id = document.get("key_id")
    if (
        not isinstance(key_id, str)
        or not 1 <= len(key_id) <= MAX_KEY_ID_LENGTH
        or not KEY_ID_RE.match(key_id)
    ):
        raise PublisherError(f"signing key file {path.name}: key_id is missing or malformed")
    try:
        seed = base64.b64decode(str(document["private_key"]), validate=True)
    except (ValueError, TypeError):
        raise PublisherError(
            f"signing key file {path.name}: private_key is not valid base64"
        ) from None
    if len(seed) != ED25519_SEED_BYTES:
        raise PublisherError(
            f"signing key file {path.name}: private_key must be a raw "
            f"{ED25519_SEED_BYTES}-byte Ed25519 seed (got {len(seed)} bytes)"
        )
    _require_cryptography("mcp bundle publish")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    public = (
        Ed25519PrivateKey.from_private_bytes(seed)
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    declared = document.get("public_key")
    if isinstance(declared, str):
        try:
            declared_bytes = base64.b64decode(declared, validate=True)
        except (ValueError, TypeError):
            declared_bytes = b""
        if declared_bytes != public:
            raise PublisherError(
                f"signing key file {path.name}: the declared public key does not match "
                "the private seed (corrupt or hand-edited key file)"
            )
    return SigningKey(key_id=key_id, seed=seed, public_key=public)


def _sign_document(document: dict, key: SigningKey) -> dict:
    """Attach the detached Ed25519 signature over the canonical JSON
    (:func:`canonical_bundle_bytes` -- the normative E13/E14 input)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    message = canonical_bundle_bytes(document)
    signature = Ed25519PrivateKey.from_private_bytes(key.seed).sign(message)
    document["signature"] = {
        "algorithm": "ed25519",
        "key_id": key.key_id,
        "value": base64.b64encode(signature).decode("ascii"),
    }
    return document


# ---------------------------------------------------------------------------
# verify: a thin wrapper over the REAL E14 verification. Also the ceremony's
# automatic post-package self-check.


def verify_report(
    bundle_path: Path,
    trusted_keys_path: Path,
    audience_ids: Sequence[str] | None = None,
    now: float | None = None,
    profile_name: str = "",
) -> dict:
    """Run :func:`resolve_bundle_state` (the real E14 path) and report.

    ``ok`` with the resolved profile name and provenance fields on success;
    the refusal code/name and fail-closed message otherwise. Never raises on
    a refusal -- the exit-code decision belongs to the caller.
    ``profile_name`` is the CLI-precedence selection (the publish self-check
    uses it for bundles without a ``default_profile``).
    """
    state = resolve_bundle_state(
        Path(bundle_path),
        trusted_keys_path=Path(trusted_keys_path) if trusted_keys_path else None,
        cli_name=profile_name or "",
        env_name="",
        audience_ids=list(audience_ids or []),
        now=now,
    )
    if isinstance(state, ActiveProfile):
        provenance = state.provenance
        return {
            "ok": True,
            "code": 0,
            "refusal": "",
            "message": "",
            "bundle_sha256": provenance.bundle_sha256 if provenance else state.file_sha256,
            "profile": state.name,
            "issuer_key_id": provenance.issuer_key_id if provenance else "",
            "audience": list(provenance.audience) if provenance else [],
            "expires_at": provenance.expires_at if provenance else "",
            "verified_via": "resolve_bundle_state (E14)",
        }
    assert isinstance(state, BundleFailClosed)
    return {
        "ok": False,
        "code": state.code,
        "refusal": REFUSAL_NAMES.get(state.code, "unknown"),
        "message": state.message,
        "bundle_sha256": state.bundle_sha256,
        "profile": "",
        "issuer_key_id": "",
        "audience": [],
        "expires_at": "",
        "verified_via": "resolve_bundle_state (E14)",
    }


# ---------------------------------------------------------------------------
# publish: validate -> sign -> package -> verify -> handoff bundle.


def _derive_namespaces(profiles: dict) -> list[str]:
    """Whole-upstream ceiling derived from every rule in the profile map."""
    upstreams: set[str] = set()
    for spec in profiles.values():
        if not isinstance(spec, dict):
            continue
        for field in ("visible", "callable"):
            for rule in spec.get(field) or []:
                if isinstance(rule, str) and "." in rule:
                    upstreams.add(rule.split(".", 1)[0])
    return sorted(f"{upstream}.*" for upstream in upstreams)


def _profile_rules(profiles: dict) -> list[tuple[str, str, str]]:
    """(profile name, field, rule) for every declared rule."""
    rules: list[tuple[str, str, str]] = []
    for name, spec in profiles.items():
        for field in ("visible", "callable"):
            for rule in spec.get(field) or []:
                rules.append((name, field, rule))
    return rules


def _resolve_previous_sha(previous: str) -> str:
    """``--previous``: a 64-hex SHA-256 literal, or a path to the previous
    bundle file whose bytes are hashed."""
    candidate = previous.strip().lower()
    if SHA256_RE.match(candidate):
        return candidate
    path = Path(previous).expanduser()
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        raise PublisherError(
            "--previous must be a 64-hex bundle SHA-256 or a readable previous "
            f"bundle file (could not read {path.name})"
        ) from None


def publish_bundle(
    profiles_path: Path,
    signing_key_path: Path,
    issuer_key_id: str = "",
    audience: Sequence[str] | None = None,
    expires_days: int = DEFAULT_EXPIRES_DAYS,
    namespaces: Sequence[str] | None = None,
    out_dir: Path | str = ".",
    name: str = "",
    display: str = "",
    previous: str = "",
    crl_path: str = "",
    dry_run: bool = False,
    force: bool = False,
    now: float | None = None,
) -> dict:
    """Run the full local signing ceremony over one raw profile file.

    Pipeline: validate the raw profile with the REAL E09/E10 loader, build
    the bundle document, sign it over :func:`canonical_bundle_bytes`,
    package atomically into ``<out>/<name>.bundle.json`` plus MANIFEST /
    VALIDATION-REPORT / ROLLBACK sidecars, and self-check the packaged bytes
    through the REAL E14 verification before the signed bundle ever gets its
    final name. Any refusal raises :class:`PublisherError` and leaves no
    signed bundle behind. ``dry_run`` performs every step (including the
    self-check, against a private temp copy) but writes nothing to ``out``.
    """
    import time as _time

    if now is None:
        now = _time.time()
    checks: list[dict] = []

    def check(step: str, detail: str) -> None:
        checks.append({"check": step, "ok": True, "detail": detail})

    _require_cryptography("mcp bundle publish")

    # 1. Validate: the real E09/E10 loader (shape + static semantic checks).
    try:
        profile_document, source_sha = load_profile_document(Path(profiles_path))
    except ProfileLoadError as exc:
        raise PublisherError(f"raw profile is invalid (E09/E10 static checks): {exc}") from None
    profiles = profile_document["profiles"]
    check(
        "profile_static_checks",
        f"E09/E10 loader accepted {len(profiles)} profile(s); source sha256 {source_sha}",
    )

    # 2. The signing key (private, keygen format; public-only files refused).
    key = load_signing_key(Path(signing_key_path))
    if issuer_key_id and issuer_key_id != key.key_id:
        raise PublisherError(
            f"--issuer-key-id {issuer_key_id!r} does not match the signing key file's "
            f"key_id {key.key_id!r}; refusing to sign under a mismatched identity"
        )
    issuer_key_id = key.key_id
    check("signing_key", f"key_id {issuer_key_id!r}, fingerprint {key.fingerprint} (DEV key)")

    display = display or DEFAULT_ISSUER_DISPLAY
    if not 1 <= len(display) <= MAX_DISPLAY_LENGTH:
        raise PublisherError(f"issuer display must be 1-{MAX_DISPLAY_LENGTH} characters")

    # 3. Audience: mandatory, non-empty, bounded grammar.
    cleaned_audience = [item.strip() for item in (audience or []) if item and item.strip()]
    if not cleaned_audience:
        raise PublisherError(
            "a bundle audience is required and must be non-empty: pass at least one "
            "--audience 'team:NAME' / 'org:NAME' / 'host:NAME'"
        )
    if len(cleaned_audience) > MAX_AUDIENCE:
        raise PublisherError(f"at most {MAX_AUDIENCE} audience identifiers are allowed")
    if len(set(cleaned_audience)) != len(cleaned_audience):
        raise PublisherError("audience identifiers must be unique")
    for item in cleaned_audience:
        if len(item) > MAX_DISPLAY_LENGTH or not AUDIENCE_RE.match(item):
            raise PublisherError(
                f"audience identifier {item!r} must be 'team:'/'org:'/'host:' + name"
            )
    check("audience", f"{len(cleaned_audience)} identifier(s): {', '.join(cleaned_audience)}")

    # 4. Validity window: issued now, expiring a positive number of days out.
    try:
        expires_days = int(expires_days)
    except (TypeError, ValueError):
        raise PublisherError("--expires-days must be an integer number of days") from None
    if expires_days < 1:
        raise PublisherError(
            f"--expires-days must be >= 1 (got {expires_days}); a bundle that expires "
            "in the past or an inverted validity window is refused"
        )
    issued_at = _utc_text(now)
    expires_at = _utc_text(now + expires_days * 86400.0)
    check("validity_window", f"{issued_at} .. {expires_at} ({expires_days} day(s))")

    # 5. Namespace ceiling: explicit rules validated against the E09 rule
    # grammar, or derived whole-upstream rules; every profile rule must be
    # covered BEFORE signing (the same containment E14 re-checks later).
    cleaned_namespaces = [item.strip() for item in (namespaces or []) if item and item.strip()]
    if cleaned_namespaces:
        if len(cleaned_namespaces) > MAX_NAMESPACES:
            raise PublisherError(f"at most {MAX_NAMESPACES} namespace rules are allowed")
        if len(set(cleaned_namespaces)) != len(cleaned_namespaces):
            raise PublisherError("namespace rules must be unique")
        for rule in cleaned_namespaces:
            if not RULE_RE.match(rule):
                raise PublisherError(
                    f"namespace rule {rule!r} is not '<upstream>.<tool>' or "
                    "'<upstream>.*' (E09 rule grammar)"
                )
        ceiling = cleaned_namespaces
        ceiling_note = "explicit"
    else:
        ceiling = _derive_namespaces(profiles)
        ceiling_note = "derived from the profile rules"
        if not ceiling:
            raise PublisherError(
                "could not derive allowed_upstream_namespaces (the profiles declare no "
                "rules); pass --namespaces explicitly"
            )
    for profile_name, field, rule in _profile_rules(profiles):
        if not _rule_covered(rule, ceiling):
            raise PublisherError(
                f"profile {profile_name!r} {field} rule {rule!r} is outside the "
                "allowed_upstream_namespaces ceiling; widen --namespaces or narrow "
                "the profile (the E14 verifier would refuse this bundle with "
                "bundle_audience_mismatch)"
            )
    check("namespace_ceiling", f"{len(ceiling)} rule(s) ({ceiling_note}); every profile rule covered")

    # 6. Optional revocation pointer slot (local CRL path; absolute only).
    crl_path = (crl_path or "").strip()
    if crl_path and not os.path.isabs(os.path.expanduser(crl_path)):
        raise PublisherError("--crl-path must be an absolute path after '~' expansion")

    # 7. Package name.
    name = (name or Path(profiles_path).stem).strip()
    if not BUNDLE_NAME_RE.match(name):
        raise PublisherError(
            f"bundle name {name!r} must match {BUNDLE_NAME_RE.pattern} (pass --name)"
        )

    previous_sha = _resolve_previous_sha(previous) if previous else ""

    # 8. Build and sign the bundle document.
    document: dict = {
        "bundle_version": 1,
        "comment": f"published locally by unlimited-skills mcp bundle publish ({DEV_KEY_WARNING})",
        "issuer": {"key_id": issuer_key_id, "display": display},
        "audience": cleaned_audience,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "allowed_upstream_namespaces": ceiling,
        "profiles": profiles,
    }
    if "default_profile" in profile_document:
        document["default_profile"] = profile_document["default_profile"]
    if crl_path:
        document["revocation"] = {"crl_path": crl_path}
    _sign_document(document, key)
    bundle_bytes = (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    check("signature", f"detached ed25519 over canonical JSON; bundle sha256 {bundle_sha}")

    out = Path(out_dir).expanduser()
    bundle_path = out / f"{name}{BUNDLE_SUFFIX}"
    manifest_path = out / f"{name}{MANIFEST_SUFFIX}"
    report_path = out / f"{name}{VALIDATION_REPORT_SUFFIX}"
    rollback_path = out / f"{name}{ROLLBACK_SUFFIX}"
    artifact_paths = (bundle_path, manifest_path, report_path, rollback_path)
    if not dry_run and not force:
        collisions = [path.name for path in artifact_paths if path.exists()]
        if collisions:
            raise PublisherError(
                f"out dir already contains {', '.join(collisions)}; pass --force to "
                "overwrite (nothing was written)"
            )

    # 9. Self-check: the packaged BYTES must verify through the REAL E14
    # path (resolve_bundle_state) before the signed bundle gets its final
    # name. The ephemeral trusted-keys file holds the PUBLIC key only.
    if dry_run:
        staging = Path(tempfile.mkdtemp(prefix="uls-bundle-publish-dry-"))
        temp_bundle = staging / f"{name}{BUNDLE_SUFFIX}.tmp"
        temp_keys = staging / "self-check-trusted-keys.json.tmp"
    else:
        out.mkdir(parents=True, exist_ok=True)
        staging = out
        fd, tmp_name = tempfile.mkstemp(
            prefix=bundle_path.name + ".", suffix=".tmp", dir=str(out)
        )
        os.close(fd)
        temp_bundle = Path(tmp_name)
        fd, tmp_keys_name = tempfile.mkstemp(
            prefix="self-check-trusted-keys.", suffix=".tmp", dir=str(out)
        )
        os.close(fd)
        temp_keys = Path(tmp_keys_name)
    written_this_ceremony: list[Path] = []
    try:
        temp_bundle.write_bytes(bundle_bytes)
        temp_keys.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "comment": "ephemeral self-check trusted-keys (PUBLIC key only)",
                    "keys": [
                        {
                            "key_id": issuer_key_id,
                            "algorithm": "ed25519",
                            "public_key": base64.b64encode(key.public_key).decode("ascii"),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        selection = document.get("default_profile") or sorted(profiles)[0]
        verification = verify_report(
            temp_bundle,
            temp_keys,
            audience_ids=[cleaned_audience[0]],
            now=now,
            profile_name=selection,
        )
        if not verification["ok"]:
            raise PublisherError(
                "ceremony self-check FAILED: the packaged bundle does not verify "
                f"through the real E14 path ({verification['code']} "
                f"{verification['refusal']}): {verification['message']} -- no signed "
                "bundle was written"
            )
        check(
            "post_package_verification",
            f"resolve_bundle_state ok (profile {verification['profile']!r})",
        )

        rule_counts = {
            profile_name: {
                "visible_rules": len(spec.get("visible") or []),
                "callable_rules": len(spec.get("callable") or []),
            }
            for profile_name, spec in profiles.items()
        }
        revoke_command = f"unlimited-skills mcp trust revoke --bundle-sha256 {bundle_sha}"
        manifest = {
            "format": "mcp-bundle-manifest",
            "schema_version": 1,
            "name": name,
            "bundle_file": bundle_path.name,
            "bundle_sha256": bundle_sha,
            "issuer_key_id": issuer_key_id,
            "issuer_fingerprint": key.fingerprint,
            "created_at": issued_at,
            "expires_at": expires_at,
            "audience": cleaned_audience,
            "allowed_upstream_namespaces": ceiling,
            "source_profile_sha256": source_sha,
            "profile_count": len(profiles),
            "profiles": rule_counts,
            "visible_rule_count": sum(item["visible_rules"] for item in rule_counts.values()),
            "callable_rule_count": sum(item["callable_rules"] for item in rule_counts.values()),
            "publisher_version": PUBLISHER_VERSION,
            "dev_key_warning": DEV_KEY_WARNING,
        }
        validation_report = {
            "format": "mcp-bundle-validation-report",
            "schema_version": 1,
            "checked_at": issued_at,
            "bundle_sha256": bundle_sha,
            "checks": checks,
            "verification": {
                "ok": True,
                "code": 0,
                "via": "resolve_bundle_state (E14)",
                "profile": verification["profile"],
            },
        }
        rollback = {
            "format": "mcp-bundle-rollback",
            "schema_version": 1,
            "bundle_sha256": bundle_sha,
            "previous_bundle_sha256": previous_sha,
            "revoke_command": revoke_command,
            "rollback_steps": [
                f"revoke this bundle in the local CRL: {revoke_command} "
                "(append --reason <why>)",
                (
                    f"restore the previous bundle (sha256 {previous_sha}) and restart "
                    "the gateway against it"
                    if previous_sha
                    else "no previous bundle recorded; fall back to the raw --profiles "
                    "file (or re-publish a corrected bundle) and restart the gateway"
                ),
                "confirm: unlimited-skills mcp bundle verify --bundle <file> "
                "--trusted-keys <file> refuses the revoked bundle (-32017) and "
                "accepts the restored one",
            ],
        }
        result = {
            "published": not dry_run,
            "dry_run": bool(dry_run),
            "name": name,
            "out_dir": str(out),
            "bundle_sha256": bundle_sha,
            "issuer_key_id": issuer_key_id,
            "issuer_fingerprint": key.fingerprint,
            "audience": cleaned_audience,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "profile_count": len(profiles),
            "source_profile_sha256": source_sha,
            "previous_bundle_sha256": previous_sha,
            "revoke_command": revoke_command,
            "verification": verification,
            "checks": checks,
            "artifacts": [path.name for path in artifact_paths],
        }
        if dry_run:
            result["note"] = (
                "dry run: validated, signed in memory, and self-checked; NO signed "
                "bundle or sidecar was written to the out dir"
            )
            return result

        # 10. Package atomically: sidecars first, the signed bundle LAST --
        # it only appears under its final name once everything else (and the
        # self-check) succeeded. Any failure removes the temp; nothing
        # signed remains.
        _atomic_write_json(report_path, validation_report)
        written_this_ceremony.append(report_path)
        _atomic_write_json(manifest_path, manifest)
        written_this_ceremony.append(manifest_path)
        _atomic_write_json(rollback_path, rollback)
        written_this_ceremony.append(rollback_path)
        os.replace(temp_bundle, bundle_path)
        result["bundle_path"] = str(bundle_path)
        result["manifest_path"] = str(manifest_path)
        result["validation_report_path"] = str(report_path)
        result["rollback_path"] = str(rollback_path)
        return result
    except BaseException:
        # Ceremony failure: never leave a signed bundle (or half a package).
        # Only artifacts written by THIS ceremony are removed -- a previous
        # good package's files are never touched.
        for leftover in [temp_bundle, *written_this_ceremony]:
            try:
                leftover.unlink()
            except OSError:
                pass
        raise
    finally:
        try:
            temp_keys.unlink()
        except OSError:
            pass
        if dry_run:
            import shutil

            shutil.rmtree(staging, ignore_errors=True)


# ---------------------------------------------------------------------------
# Human renderers (text mode; --json prints the result dicts verbatim).
# Key material NEVER appears here: paths, fingerprints, and hashes only.


def format_keygen(result: dict) -> str:
    return "\n".join(
        [
            f"generated DEV Ed25519 keypair '{result['key_id']}' "
            f"(fingerprint {result['fingerprint']})",
            f"*** {result['warning']} ***",
            f"private signing key: {result['private_key_path']}",
            "  -> stays HERE; never import it, never commit it, never share it",
            f"public key (trust-store import format): {result['public_key_path']}",
            f"  -> hand to consumers: {result['trust_import_command']}",
        ]
    )


def format_publish(result: dict) -> str:
    lines = [
        (
            "DRY RUN -- would publish bundle "
            if result["dry_run"]
            else "published signed bundle "
        )
        + f"'{result['name']}' (sha256 {result['bundle_sha256']})",
        f"issuer: {result['issuer_key_id']} (fingerprint {result['issuer_fingerprint']}; DEV key)",
        f"audience: {', '.join(result['audience'])}",
        f"validity: {result['issued_at']} .. {result['expires_at']}",
        f"profiles: {result['profile_count']} (source sha256 {result['source_profile_sha256']})",
    ]
    for item in result["checks"]:
        lines.append(f"  [ok] {item['check']}: {item['detail']}")
    if result["dry_run"]:
        lines.append(
            "would write: " + ", ".join(result["artifacts"]) + f" into {result['out_dir']}"
        )
        lines.append(result["note"])
    else:
        lines.append("wrote: " + ", ".join(result["artifacts"]) + f" into {result['out_dir']}")
        lines.append(f"rollback/revoke: {result['revoke_command']}")
    return "\n".join(lines)


def format_verify(report: dict) -> str:
    if report["ok"]:
        return (
            f"bundle VERIFIED (sha256 {report['bundle_sha256']}): profile "
            f"{report['profile']!r}, issuer {report['issuer_key_id']}, audience "
            f"[{', '.join(report['audience'])}], expires {report['expires_at']} "
            f"-- via {report['verified_via']}"
        )
    return (
        f"bundle REFUSED ({report['code']} {report['refusal']}): {report['message']} "
        f"-- via {report['verified_via']}"
    )
