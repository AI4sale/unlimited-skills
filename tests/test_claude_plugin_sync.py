from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills.native import claude_plugin_sources, sync_native_sources


def write_skill(root: Path, name: str, description: str = "plugin skill") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\nPlugin body marker.\n",
        encoding="utf-8",
    )
    return skill_dir


def write_installed_plugins(claude_home: Path, key: str, install_path: Path | None) -> None:
    plugins_root = claude_home / "plugins"
    plugins_root.mkdir(parents=True, exist_ok=True)
    entry: dict = {"scope": "user", "version": "1.0.0"}
    if install_path is not None:
        entry["installPath"] = str(install_path)
    payload = {"version": 2, "plugins": {key: [entry]}}
    (plugins_root / "installed_plugins.json").write_text(json.dumps(payload), encoding="utf-8")


def write_plugin_manifest(plugin_root: Path, skills: list[str] | None = None) -> None:
    manifest_dir = plugin_root / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {"name": plugin_root.name, "version": "1.0.0"}
    if skills is not None:
        payload["skills"] = skills
    (manifest_dir / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")


def test_plugin_skills_synced_from_cache_install_path(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / ".claude"
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
    plugin_root = claude_home / "plugins" / "cache" / "mp" / "toolkit" / "1.0.0"
    write_plugin_manifest(plugin_root, skills=["./skills/"])
    write_skill(plugin_root / "skills", "plugin-review", "review with plugin skill")
    write_installed_plugins(claude_home, "toolkit@mp", plugin_root)
    root = tmp_path / ".unlimited-skills" / "library"

    results = sync_native_sources(root, agents=["claude-code"])

    plugin_results = [item for item in results if item.collection == "claude-code-plugin-mp-toolkit"]
    assert plugin_results and plugin_results[0].imported_count == 1
    mirrored = root / "local" / "claude-code-plugin-mp-toolkit" / "skills" / "plugin-review" / "SKILL.md"
    assert mirrored.is_file()


def test_plugin_skills_fall_back_to_marketplace_clone(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / ".claude"
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
    plugins_root = claude_home / "plugins"
    clone = plugins_root / "marketplaces" / "mp"
    clone.mkdir(parents=True)
    (clone / ".claude-plugin").mkdir()
    (clone / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "mp", "plugins": [{"name": "toolkit", "source": "./"}]}),
        encoding="utf-8",
    )
    write_skill(clone / ".claude" / "skills", "clone-skill", "skill from marketplace clone")
    # installPath points at a pruned cache directory that no longer exists
    write_installed_plugins(claude_home, "toolkit@mp", plugins_root / "cache" / "mp" / "toolkit" / "9.9.9")
    (plugins_root / "known_marketplaces.json").write_text(
        json.dumps({"mp": {"installLocation": str(clone)}}),
        encoding="utf-8",
    )
    root = tmp_path / ".unlimited-skills" / "library"

    results = sync_native_sources(root, agents=["claude-code"])

    plugin_results = [item for item in results if item.collection == "claude-code-plugin-mp-toolkit"]
    assert plugin_results and plugin_results[0].imported_count == 1
    assert (root / "local" / "claude-code-plugin-mp-toolkit" / "skills" / "clone-skill" / "SKILL.md").is_file()


def test_plugin_sync_disabled_by_env(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / ".claude"
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
    monkeypatch.setenv("UNLIMITED_SKILLS_DISABLE_PLUGIN_SYNC", "1")
    plugin_root = claude_home / "plugins" / "cache" / "mp" / "toolkit" / "1.0.0"
    write_plugin_manifest(plugin_root, skills=["./skills/"])
    write_skill(plugin_root / "skills", "plugin-review")
    write_installed_plugins(claude_home, "toolkit@mp", plugin_root)

    assert claude_plugin_sources(claude_home) == []


def test_declared_skill_path_may_not_escape_plugin_root(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / ".claude"
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
    outside = tmp_path / "outside-skills"
    write_skill(outside, "escaped-skill")
    plugin_root = claude_home / "plugins" / "cache" / "mp" / "toolkit" / "1.0.0"
    write_plugin_manifest(plugin_root, skills=["../../../../../outside-skills"])
    write_installed_plugins(claude_home, "toolkit@mp", plugin_root)

    sources = claude_plugin_sources(claude_home)

    assert all("outside-skills" not in str(source.root) for source in sources)


def test_missing_plugin_state_yields_no_sources(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / ".claude"
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))

    assert claude_plugin_sources(claude_home) == []
