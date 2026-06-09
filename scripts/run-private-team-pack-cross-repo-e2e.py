from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from unlimited_skills.private_packs import PrivatePackClient, PrivatePackError, list_installed_private_packs, remove_private_pack
from unlimited_skills.registration import RegistrationState, register_installation, save_registration, with_install_identity
from unlimited_skills.team import TeamState, save_team_state


PACK_ID = "team_pack_acme_private_skills"
REVOKED_PACK_ID = "team_pack_revoked_fixture"


def fail(message: str) -> None:
    raise SystemExit(message)


def import_from_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        fail(f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        fail(f"{path} must contain a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_public_cli(args: list[str], *, env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "unlimited_skills.cli", *args],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        fail("CLI command failed: "
             + " ".join(args)
             + "\nstdout:\n"
             + completed.stdout
             + "\nstderr:\n"
             + completed.stderr)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        fail(f"CLI command did not return JSON: {' '.join(args)}: {exc}\n{completed.stdout}")
    if not isinstance(payload, dict):
        fail(f"CLI command returned non-object JSON: {' '.join(args)}")
    return payload


def verify_registry_org_governance(registry_repo: Path, db_url: str, owner_install_id: str) -> dict[str, Any]:
    from unlimited_registry.orgs import add_membership, assign_private_pack_ownership, create_namespace, create_organization, create_team, governance_entitlement_for_scope, set_governance_entitlement
    from unlimited_registry.storage import ProductionStorage

    storage = ProductionStorage(db_url)
    with storage.connect() as conn:
        org = create_organization(conn, org_id="org_acme_fixture", name="Acme Fixture", plan="business")
        team = create_team(
            conn,
            org_id=org["org_id"],
            team_id="team_acme_fixture",
            name="Acme Platform",
            owner_install_id=owner_install_id,
            channel="stable",
        )
        membership = add_membership(conn, team_id=team["team_id"], install_id=owner_install_id, role="owner", status="active")
        namespace = create_namespace(conn, org_id=org["org_id"], team_id=team["team_id"], namespace="team/acme")
        set_governance_entitlement(
            conn,
            scope_type="organization",
            scope_id=org["org_id"],
            plan="business",
            features=["private_team_packs", "team_sync", "community_catalog"],
            private_pack_namespaces=["team/acme"],
            active_client_limit=100,
            offline_grace_seconds=86400,
        )
        entitlement = governance_entitlement_for_scope(conn, "organization", org["org_id"])
        ownership = assign_private_pack_ownership(conn, pack_id=PACK_ID, scope_type="team", scope_id=team["team_id"], namespace=namespace["namespace"])
    if entitlement.get("plan") != "business":
        fail("Registry organization governance entitlement was not resolved")
    if ownership.get("pack_id") != PACK_ID:
        fail("Registry private pack ownership was not recorded")
    return {
        "org_id": org["org_id"],
        "team_id": team["team_id"],
        "namespace": namespace["namespace"],
        "membership_status": membership["status"],
        "entitlement_plan": entitlement["plan"],
        "private_pack_owned": True,
        "registry_repo": str(registry_repo),
    }


def build_installable_private_pack(private_root: Path) -> None:
    from unlimited_registry.private_packs import build_private_team_pack_manifest, public_summary_for_private_pack
    from unlimited_registry.signing import public_key_to_b64url

    archive_path = private_root / "archives" / "acme-private-skills-2026.01.01.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{PACK_ID}/skills/browser-qa/SKILL.md", "---\nname: browser-qa\ndescription: Browser QA\n---\n\n# Browser QA\n")

    private_key = Ed25519PrivateKey.generate()
    key_id = "private-team-pack-e2e-key"
    manifest = build_private_team_pack_manifest(
        pack_id=PACK_ID,
        team_id="team_acme_fixture",
        namespace="team/acme",
        name="acme-private-skills",
        version="2026.01.01",
        archive_path=archive_path,
        archive_url="archives/acme-private-skills-2026.01.01.zip",
        allowed_agents=["codex"],
        allowed_install_ids=["uls_inst_master", "uls_inst_worker"],
        allowed_channel="stable",
        revoked=False,
        private_key=private_key,
        key_id=key_id,
    )
    write_json(private_root / f"private-team-pack.{PACK_ID}.json", manifest)
    write_json(
        private_root / "public-keys" / "manifest-public-keys.v1.json",
        {
            "schema_version": 1,
            "keys": [
                {
                    "key_id": key_id,
                    "algorithm": "ed25519",
                    "public_key": public_key_to_b64url(private_key),
                    "status": "active",
                    "scopes": ["private-team-pack"],
                }
            ],
        },
    )
    write_json(private_root / "public-summary.json", {"schema_version": 1, "private_packs": [public_summary_for_private_pack(manifest)]})


def add_revoked_private_pack(registry_repo: Path, private_root: Path) -> None:
    from unlimited_registry.private_packs import build_private_team_pack_manifest
    from unlimited_registry.signing import public_key_to_b64url

    archive_path = private_root / "archives" / "revoked-private-skills.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{REVOKED_PACK_ID}/skills/revoked-skill/SKILL.md", "---\nname: revoked-skill\ndescription: revoked\n---\n")

    private_key = Ed25519PrivateKey.generate()
    key_id = "private-team-pack-revoked-e2e-key"
    manifest = build_private_team_pack_manifest(
        pack_id=REVOKED_PACK_ID,
        team_id="team_acme_fixture",
        namespace="team/acme",
        name="revoked-private-skills",
        version="2026.01.02",
        archive_path=archive_path,
        archive_url="archives/revoked-private-skills.zip",
        allowed_agents=["codex"],
        allowed_install_ids=["uls_inst_master"],
        allowed_channel="stable",
        revoked=True,
        private_key=private_key,
        key_id=key_id,
    )
    write_json(private_root / f"private-team-pack.{REVOKED_PACK_ID}.json", manifest)
    keys_path = private_root / "public-keys" / "manifest-public-keys.v1.json"
    keys_payload = read_json(keys_path)
    keys_payload.setdefault("keys", [])
    keys_payload["keys"].append(
        {
            "key_id": key_id,
            "algorithm": "ed25519",
            "public_key": public_key_to_b64url(private_key),
            "status": "active",
            "scopes": ["private-team-pack"],
        }
    )
    write_json(keys_path, keys_payload)


def trusted_keys_env(private_root: Path) -> str:
    payload = read_json(private_root / "public-keys" / "manifest-public-keys.v1.json")
    values = []
    for item in payload.get("keys", []):
        if isinstance(item, dict) and item.get("algorithm") == "ed25519":
            values.append(f"{item['key_id']}:{item['public_key']}")
    if not values:
        fail("Private pack fixture has no public keys")
    return ",".join(values)


def start_registry_server(registry_repo: Path, artifact_root: Path, db_url: str):
    import uvicorn
    from unlimited_registry.production_api import PUBLIC_KEYS_PATH, ProductionSettings, create_app

    settings = ProductionSettings(
        mode="production",
        db_url=db_url,
        artifact_root=artifact_root,
        public_keys_file=(artifact_root / PUBLIC_KEYS_PATH).resolve(),
        require_device_proof=True,
        audit_log=None,
        rate_limit=1000,
    )
    app = create_app(settings=settings)
    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        fail("Private registry test server did not start")
    return server, thread, f"http://127.0.0.1:{port}"


def register_client(server_url: str, *, install_id: str, agent: str, home: Path) -> RegistrationState:
    state = with_install_identity(RegistrationState(install_id=install_id, server_url=server_url))
    registered = register_installation(state, server_url=server_url, agent=agent, timeout=10)
    save_registration(registered, home=home / ".unlimited-skills")
    return registered


def grant_private_pack_entitlement(db_url: str, install_id: str) -> None:
    from unlimited_registry.storage import ProductionStorage

    ProductionStorage(db_url).set_entitlement(
        install_id,
        plan="business",
        features=["hosted_catalog", "private_team_packs"],
        active_client_limit=25,
        offline_grace_seconds=86400,
    )


def run_e2e(registry_repo: Path, *, temp_home: bool = False) -> dict[str, Any]:
    registry_repo = registry_repo.resolve()
    if not (registry_repo / "unlimited_registry" / "production_api.py").is_file():
        fail(f"Registry repo does not look valid: {registry_repo}")
    sys.path.insert(0, str(registry_repo))
    private_tests = import_from_path("uls_registry_test_helpers", registry_repo / "tests" / "test_production_registry_api.py")

    with tempfile.TemporaryDirectory(prefix="uls-private-pack-e2e-", ignore_cleanup_errors=True) as tmp:
        tmp_root = Path(tmp)
        artifact_root = private_tests.create_signed_artifact_root(tmp_root)
        private_root = artifact_root / "private-packs"
        build_installable_private_pack(private_root)
        add_revoked_private_pack(registry_repo, private_root)

        home = tmp_root / "home" if temp_home else Path(os.environ.get("UNLIMITED_SKILLS_HOME", tmp_root / "home")).parent
        library = tmp_root / "library"
        os.environ["UNLIMITED_SKILLS_HOME"] = str(home / ".unlimited-skills")
        os.environ["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"] = trusted_keys_env(private_root)

        db_url = f"sqlite:///{tmp_root / 'registry.sqlite3'}"
        server, thread, server_url = start_registry_server(registry_repo, artifact_root, db_url)
        try:
            state = register_client(server_url, install_id="uls_inst_master", agent="codex", home=home)
            grant_private_pack_entitlement(db_url, state.install_id)
            governance = verify_registry_org_governance(registry_repo, db_url, state.install_id)
            client = PrivatePackClient(state, timeout=10)

            listed = client.list()
            if PACK_ID not in {item.pack_id for item in listed}:
                fail("Authorized private pack was not listed")
            if REVOKED_PACK_ID in {item.pack_id for item in listed}:
                fail("Revoked private pack was listed")

            preview = client.preview(PACK_ID)
            if "raw" not in preview or "SKILL.md" in json.dumps(preview):
                fail("Preview leaked private skill body content")

            manifest = client.signed_manifest(PACK_ID)["manifest"]
            if manifest.get("pack_id") != PACK_ID:
                fail("Signed manifest returned unexpected pack_id")

            installed = client.install(library, PACK_ID)
            installed_path = Path(installed.target)
            if not (installed_path / "skills").is_dir():
                fail("Private pack install did not create a skills directory")

            sync_result = client.sync(library, dry_run=True)
            if sync_result["planned"][0]["action"] != "noop":
                fail("Private pack sync did not detect installed current version")

            wrong_state = register_client(server_url, install_id="uls_inst_worker", agent="unknown-agent", home=home)
            grant_private_pack_entitlement(db_url, wrong_state.install_id)
            wrong_client = PrivatePackClient(wrong_state, timeout=10)
            access = wrong_client.access_check(PACK_ID)
            if access.get("authorized") is not False:
                fail("Wrong agent was not denied by access-check")
            save_registration(wrong_state, home=home / ".unlimited-skills")
            cli_env = os.environ.copy()
            cli_env["UNLIMITED_SKILLS_HOME"] = str(home / ".unlimited-skills")
            cli_access = run_public_cli(["--root", str(library), "private-packs", "access-check", PACK_ID, "--json"], env=cli_env)
            if cli_access.get("status") != "denied" or "wrong_agent" not in cli_access.get("denial_reasons", []):
                fail("CLI access-check did not report wrong_agent denial")
            if PACK_ID in json.dumps(cli_access):
                fail("CLI access-check leaked raw private pack id")
            try:
                wrong_client.install(library, PACK_ID)
            except PrivatePackError:
                pass
            else:
                fail("Wrong agent install unexpectedly succeeded")

            try:
                client.install(library, REVOKED_PACK_ID)
            except PrivatePackError:
                pass
            else:
                fail("Revoked pack install unexpectedly succeeded")

            save_registration(state, home=home / ".unlimited-skills")
            save_team_state(
                TeamState(team_id=governance["team_id"], team_name="Acme Platform", role="owner", status="approved", approval_mode="manual"),
                home=home / ".unlimited-skills",
            )
            write_json(
                home / ".unlimited-skills" / "org-status.json",
                {
                    "schema_version": 1,
                    "plan": governance["entitlement_plan"],
                    "organization": {"org_id": governance["org_id"], "name": "Acme Fixture", "role": "owner", "status": "active"},
                    "entitlements": {"private_packs": {"status": "allowed"}, "community_catalog": {"status": "allowed"}, "team_sync": {"status": "allowed"}},
                    "last_refreshed_at": "2026-06-09T00:00:00Z",
                },
            )
            cli_org = run_public_cli(["--root", str(library), "org", "status", "--json"], env=cli_env)
            if cli_org.get("source") != "cache" or cli_org.get("entitlements", {}).get("private_packs") != "allowed":
                fail("CLI org status did not read redacted local governance cache")
            if "license_token" in json.dumps(cli_org).lower():
                fail("CLI org status leaked registration token fields")

            local_skill = library / "local" / "skills" / "manual-skill"
            local_skill.mkdir(parents=True)
            (local_skill / "SKILL.md").write_text("---\nname: manual-skill\ndescription: manual\n---\n", encoding="utf-8")
            remove_result = remove_private_pack(library, PACK_ID, dry_run=False)
            if not (local_skill / "SKILL.md").is_file():
                fail("Private pack remove deleted unrelated local skill content")
            if list_installed_private_packs(library):
                fail("Private pack metadata still lists removed pack")

            return {
                "schema_version": 1,
                "status": "passed",
                "server_url": server_url,
                "installed_pack": PACK_ID,
                "removed": remove_result["removed"],
                "wrong_agent_denied": True,
                "revoked_denied": True,
                "cli_access_check_denied": True,
                "cli_org_status_cache": True,
                "registry_org_governance": governance,
                "local_skill_preserved": True,
                "production_hosted_calls": False,
            }
        finally:
            server.should_exit = True
            thread.join(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run cross-repo private team pack E2E against the private registry checkout.")
    parser.add_argument("--registry-repo", default=os.environ.get("UNLIMITED_SKILLS_REGISTRY_REPO", r"D:\git\unlimited-skills-registry"))
    parser.add_argument("--fixture-mode", action="store_true", help="Compatibility flag: this runner is fixture-only and never calls production hosted services.")
    parser.add_argument("--temp-home", action="store_true", help="Use an isolated temporary Unlimited Skills home.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = run_e2e(Path(args.registry_repo), temp_home=args.temp_home)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("private team pack cross-repo E2E passed")
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
