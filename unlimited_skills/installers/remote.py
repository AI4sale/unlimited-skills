from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from unlimited_skills.hub import save_remote_config


FALLBACK_MODES = {"local_allowed", "hub_required"}


@dataclass
class RemoteHubInstallOptions:
    remote_first: bool = False
    remote_hub_url: str = ""
    hub_token_env: str = ""
    hub_token: str = ""
    remote_fallback: str = "local_allowed"
    no_remote: bool = False

    @property
    def enabled(self) -> bool:
        return not self.no_remote and bool(self.remote_first or self.remote_hub_url or self.hub_token_env or self.hub_token)


def validate_remote_options(options: RemoteHubInstallOptions) -> None:
    if options.no_remote and (options.remote_first or options.remote_hub_url or options.hub_token_env or options.hub_token):
        raise ValueError("--no-remote cannot be combined with remote hub options.")
    if options.remote_fallback not in FALLBACK_MODES:
        raise ValueError("remote_fallback must be local_allowed or hub_required.")
    if options.hub_token and options.hub_token_env:
        raise ValueError("Use either --hub-token or --hub-token-env, not both.")
    if options.enabled and not options.remote_hub_url:
        raise ValueError("--remote-hub-url is required when remote-first mode is enabled.")
    if options.enabled and not (options.hub_token or options.hub_token_env):
        raise ValueError("Remote-first mode requires --hub-token-env or --hub-token.")


def configure_remote_if_enabled(options: RemoteHubInstallOptions, install_root: Path) -> str:
    validate_remote_options(options)
    if not options.enabled:
        return ""
    path = save_remote_config(
        options.remote_hub_url,
        token=options.hub_token,
        token_env=options.hub_token_env,
        fallback_mode=options.remote_fallback,
        home=install_root,
    )
    return str(path)


def remote_report_lines(options: RemoteHubInstallOptions, remote_config_path: str = "") -> list[str]:
    if not options.enabled:
        return ["Remote hub:", "  remote-first: no"]
    token_source = f"env:{options.hub_token_env}" if options.hub_token_env else "private remote.json"
    lines = [
        "Remote hub:",
        "  remote-first: yes",
        f"  url: {options.remote_hub_url}",
        f"  fallback: {options.remote_fallback}",
        f"  token source: {token_source}",
    ]
    if remote_config_path:
        lines.append(f"  config: {remote_config_path}")
    return lines


def remote_messages(options: RemoteHubInstallOptions) -> list[str]:
    if not options.enabled:
        return []
    messages = ["Remote-first router mode enabled. Router instructions prefer remote resolve before local search."]
    if options.hub_token:
        messages.append("Hub token stored in private remote.json. Prefer --hub-token-env for shared machines.")
    return messages


def render_remote_router_block(agent: str, launcher: str, options: RemoteHubInstallOptions) -> str:
    if not options.enabled:
        return ""
    fallback = options.remote_fallback
    token_source = f"environment variable `{options.hub_token_env}`" if options.hub_token_env else "private `remote.json`"
    fallback_text = (
        "If the hub is unavailable, the CLI may use local fallback because fallback mode is `local_allowed`."
        if fallback == "local_allowed"
        else "If the hub is unavailable, fail clearly because fallback mode is `hub_required`."
    )
    return "\n".join(
        [
            "## Remote-First Local Skill Hub Mode",
            "",
            "This install is configured for remote-first skill routing through Local Skill Hub.",
            "",
            f"- Hub URL: `{options.remote_hub_url}`",
            f"- Token source: {token_source}",
            f"- Fallback policy: `{fallback}`",
            "",
            "Before local `search`/`view`, prefer remote resolution:",
            "",
            "```bash",
            f"\"{launcher}\" remote resolve \"<task or skill name>\" --agent {agent} --max-skills 2 --max-chars 12000",
            "```",
            "",
            "Use only the selected skill bodies returned by the hub. If a selected skill is metadata-only or requires a local install plan, surface the missing capability warning instead of pretending the skill is ready.",
            "",
            fallback_text,
            "",
            "After useful or wrong matches, record use or feedback where practical:",
            "",
            "```bash",
            f"\"{launcher}\" remote search \"<task or skill name>\" --limit 8",
            "```",
            "",
            "Never print, paste, or store the raw hub token in visible router files, prompts, or logs.",
            "",
        ]
    )
