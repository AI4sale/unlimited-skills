"""Select each package separately while preserving every unrelated package."""
from __future__ import annotations
import os
import secrets
import shutil
from .adapter import RuntimeAttestation
from .claude_code import (_read_json_object, _optional_json_object, _atomic_write_json,
    _tree_digest, _opaque_segment, _inventory_row, managed_inventory_digest,
    _state_digest, _runtime_marker_matches_history, _utc_now)


def _remove_owned_tree(path):
    # Installed payloads are read-only, including their directories. Only
    # private staging/backup copies are made writable for cleanup.
    for current, directories, files in os.walk(path, followlinks=False):
        os.chmod(current, 0o700)
        for name in files:
            child = os.path.join(current, name)
            if not os.path.islink(child): os.chmod(child, 0o600)
    shutil.rmtree(path)


def activate(adapter, item):
    adapter._assert_state_root()
    pack = str(item['pack_id'])
    manifest = adapter.pack_client.signed_manifest(pack, request_context=item).get('manifest')
    if not isinstance(manifest, dict):
        raise adapter.error_type('pack_manifest_invalid')
    adapter._validate_manifest(item, manifest)
    release = adapter._release_root(pack, str(item['release_id']))
    meta = _read_json_object(release/'installed.json', 'installed_revision_invalid')
    source = release/'payload'
    if (_tree_digest(source) != meta['skills_tree_sha256'] or
        any(str(meta.get(k)) != str(item[k]) for k in ('pack_id','release_id','version','archive_sha256'))):
        raise adapter.error_type('activation_payload_mismatch')
    state_path = adapter.state_root/'active.json'
    state = _optional_json_object(state_path, 'active_state_invalid') or {}
    if state and not state.get('independent_items'):
        raise adapter.error_type('independent_layout_migration_required')
    packs = {p['pack_id']:p for p in state.get('active_packs', [])}
    names = [adapter._skill_name(p) for p in source.iterdir() if p.is_dir() and not p.is_symlink()]
    if not names or len(names) != len(set(names)):
        raise adapter.error_type('pack_skills_layout_invalid')
    occupied = {name for key,p in packs.items() if key != pack for name in p.get('skill_names', [])}
    if set(names) & (occupied | adapter._unmanaged_skill_names()):
        raise adapter.error_type('managed_skill_collision')
    adapter._assert_runtime_parent(create=True)
    adapter.skills_root.mkdir(exist_ok=True)
    directory = 'pack-'+_opaque_segment(pack)
    target = adapter.skills_root/directory
    if target.is_symlink():
        raise adapter.error_type('managed_skills_symlink_forbidden')
    staged = adapter.skills_root.parent/('.package-'+secrets.token_hex(12))
    backup = adapter.skills_root.parent/('.previous-package-'+secrets.token_hex(12))
    had_previous = target.exists()
    changed = False
    try:
        shutil.copytree(source, staged)
        if _tree_digest(staged) != meta['skills_tree_sha256']:
            raise adapter.error_type('activation_payload_mismatch')
        # POSIX needs write permission when moving a directory to a different
        # parent. copytree preserves the immutable release's 0555 mode.
        os.chmod(staged, 0o700)
        if had_previous:
            os.chmod(target, 0o700)
            os.replace(target, backup)
        try:
            os.replace(staged, target)
            changed = True
            os.chmod(target, 0o555)
            packs[pack] = {**_inventory_row(item), 'version':item['version'], 'activation_nonce':item['activation_nonce'],
                'skills_tree_sha256':meta['skills_tree_sha256'], 'skill_names':names,
                'skill_directory':directory}
            active = sorted(packs.values(), key=lambda p:p['pack_id'])
            inventory = [_inventory_row(p) for p in active]
            value = {'schema_version':1,'adapter_id':adapter.adapter_id,'adapter_version':adapter.adapter_version,
                'installation_id':adapter.registration.install_id,'independent_items':True,
                'active_packs':active,'managed_inventory':inventory,
                'activation_marker':'activation_'+secrets.token_urlsafe(24),
                'expected_inventory_digest':managed_inventory_digest(inventory),
                'skills_tree_sha256':_state_digest({p['pack_id']:p['skills_tree_sha256'] for p in active}),
                'activated_at':_utc_now()}
            _atomic_write_json(state_path,value)
        except Exception:
            if changed: _remove_owned_tree(target)
            if backup.exists():
                os.replace(backup,target)
                os.chmod(target, 0o555)
            raise
    finally:
        if staged.exists(): _remove_owned_tree(staged)
        if backup.exists(): _remove_owned_tree(backup)


def attest(adapter, item):
    state = _read_json_object(adapter.state_root/'active.json','active_state_invalid')
    pack = next((p for p in state.get('active_packs',[]) if p['pack_id']==item['pack_id']),None)
    if not pack or any(pack.get(k) != item[k] for k in ('release_id','archive_sha256','activation_nonce')):
        raise adapter.error_type('runtime_attestation_pending')
    path = adapter.skills_root/pack['skill_directory']
    if path.is_symlink() or _tree_digest(path) != pack['skills_tree_sha256']:
        raise adapter.error_type('runtime_attestation_invalid')
    marker = _read_json_object(adapter.state_root/'runtime-current.json','runtime_attestation_pending')
    if not _runtime_marker_matches_history(adapter.managed_root,marker):
        raise adapter.error_type('runtime_attestation_invalid')
    if (marker.get('active_state_sha256') != _state_digest(state) or
        marker.get('activation_nonces',{}).get(item['pack_id']) != item['activation_nonce'] or
        marker.get('active_revisions',{}).get(item['pack_id']) != item['release_id'] or
        marker.get('active_archive_sha256',{}).get(item['pack_id']) != item['archive_sha256']):
        raise adapter.error_type('runtime_attestation_pending')
    return RuntimeAttestation(runtime_generation=marker['runtime_generation'],activation_nonce=item['activation_nonce'],
        pack_id=item['pack_id'],release_id=item['release_id'],active_archive_sha256=item['archive_sha256'],
        active_inventory_digest=marker['active_inventory_digest'],adapter_version=adapter.adapter_version)
