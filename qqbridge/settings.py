from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _csv(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    qqbridge_host: str = "0.0.0.0"
    qqbridge_port: int = 8787
    qqbridge_webhook_path: str = "/onebot"
    qqbridge_webhook_token: str | None = None
    qqbridge_skill_token: str | None = None
    log_level: str = "INFO"

    napcat_base_url: str = "http://127.0.0.1:3000"
    napcat_access_token: str | None = None

    hermes_base_url: str = "http://127.0.0.1:8642"
    hermes_model: str = "hermes-agent"
    hermes_api_key: str | None = None
    hermes_timeout_seconds: float = 120

    bot_qq_id: str | None = None
    bot_names: list[str] = Field(default_factory=lambda: ["bridge", "agent", "bot"])
    admin_qq_ids: list[str] = Field(default_factory=list)
    admin_prefix: str = "。"
    public_prefix: str = "/"
    bot_persona: str = "你说话自然、简洁、带一点机灵劲，但不油腻，不自称“作为AI”。"

    group_default_autonomous_enabled: bool = False
    group_min_seconds_between_replies: int = 90
    ambient_enabled: bool = True
    ambient_interval_seconds: int = 3600
    ambient_min_unread_messages: int = 1
    ambient_max_unread_messages: int = 120
    ambient_jitter_min_seconds: int = 300
    ambient_jitter_max_seconds: int = 10800
    agent_run_ttl_seconds: int = 900
    skill_onebot_level: str = "group_admin"

    max_history_messages: int = 16
    max_group_context_messages: int = 8
    max_message_chars: int = 850
    user_rate_limit_per_minute: int = 12
    state_path: Path = Path("data/state.json")
    message_store_path: Path = Path("data/messages.sqlite3")
    message_archive_dir: Path = Path("data/message_archive")
    qqbridge_config: Path | None = Path("config.yaml")

    github_token: str | None = None
    github_owner: str | None = None
    github_repo: str | None = None
    github_default_ref: str = "main"
    github_release_workflow: str = "release.yml"
    github_deploy_workflow: str = "deploy.yml"
    github_api_version: str = "2026-03-10"

    @model_validator(mode="before")
    @classmethod
    def normalize_env_aliases(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        normalized = dict(values)
        for key in list(normalized):
            lower = key.lower()
            if lower != key and lower not in normalized:
                normalized[lower] = normalized[key]
        return normalized

    @field_validator("bot_names", "admin_qq_ids", mode="before")
    @classmethod
    def parse_csv_list(cls, value: Any) -> list[str]:
        return _csv(value)

    @field_validator(
        "bot_qq_id",
        "qqbridge_webhook_token",
        "qqbridge_skill_token",
        "napcat_access_token",
        "hermes_api_key",
        "github_token",
        mode="before",
    )
    @classmethod
    def empty_to_none(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


@dataclass(slots=True)
class GroupConfig:
    autonomous_enabled: bool
    min_seconds_between_replies: int
    keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RepoConfig:
    alias: str
    owner: str
    repo: str
    default_ref: str = "main"
    workflows: dict[str, str] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"

    def workflow_id(self, alias_or_id: str) -> str:
        return self.workflows.get(alias_or_id, alias_or_id)


@dataclass(slots=True)
class BridgeConfig:
    bot_qq_id: str | None
    bot_names: list[str]
    admin_qq_ids: set[str]
    default_group: GroupConfig
    groups: dict[str, GroupConfig]
    repos: dict[str, RepoConfig]
    default_repo_alias: str

    def group_config(self, group_id: str | None) -> GroupConfig:
        if group_id and group_id in self.groups:
            return self.groups[group_id]
        return self.default_group

    def repo(self, alias: str | None = None) -> RepoConfig:
        repo_alias = alias or self.default_repo_alias
        if repo_alias not in self.repos:
            available = ", ".join(sorted(self.repos)) or "none"
            raise KeyError(f"unknown repo alias: {repo_alias}; available: {available}")
        return self.repos[repo_alias]


def load_bridge_config(settings: Settings) -> BridgeConfig:
    data = _load_yaml(settings.qqbridge_config)

    default_group = GroupConfig(
        autonomous_enabled=settings.group_default_autonomous_enabled,
        min_seconds_between_replies=settings.group_min_seconds_between_replies,
        keywords=[],
    )

    bot_data = data.get("bot", {}) if isinstance(data.get("bot"), dict) else {}
    bot_qq_id = _coalesce(bot_data.get("qq_id"), settings.bot_qq_id)
    bot_names = _csv(bot_data.get("names") or settings.bot_names)
    admin_qq_ids = set(_csv(bot_data.get("admins") or settings.admin_qq_ids))

    groups = _load_groups(data.get("groups"), default_group)
    repos, default_repo_alias = _load_repos(data.get("github"), settings)

    return BridgeConfig(
        bot_qq_id=str(bot_qq_id) if bot_qq_id else None,
        bot_names=bot_names,
        admin_qq_ids=admin_qq_ids,
        default_group=default_group,
        groups=groups,
        repos=repos,
        default_repo_alias=default_repo_alias,
    )


def _load_yaml(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return loaded


def _load_groups(raw_groups: Any, default_group: GroupConfig) -> dict[str, GroupConfig]:
    if not isinstance(raw_groups, dict):
        return {}
    groups: dict[str, GroupConfig] = {}
    for raw_id, raw_config in raw_groups.items():
        if not isinstance(raw_config, dict):
            continue
        group_id = str(raw_id)
        groups[group_id] = GroupConfig(
            autonomous_enabled=bool(raw_config.get("autonomous_enabled", default_group.autonomous_enabled)),
            min_seconds_between_replies=int(
                raw_config.get("min_seconds_between_replies", default_group.min_seconds_between_replies)
            ),
            keywords=_csv(raw_config.get("keywords", default_group.keywords)),
        )
    return groups


def _load_repos(raw_github: Any, settings: Settings) -> tuple[dict[str, RepoConfig], str]:
    repos: dict[str, RepoConfig] = {}
    default_repo_alias = "default"

    if settings.github_owner and settings.github_repo:
        repos["default"] = RepoConfig(
            alias="default",
            owner=settings.github_owner,
            repo=settings.github_repo,
            default_ref=settings.github_default_ref,
            workflows={
                "release": settings.github_release_workflow,
                "deploy": settings.github_deploy_workflow,
            },
        )

    if isinstance(raw_github, dict):
        default_repo_alias = str(raw_github.get("default_repo") or default_repo_alias)
        raw_repos = raw_github.get("repos")
        if isinstance(raw_repos, dict):
            for alias, repo_data in raw_repos.items():
                if not isinstance(repo_data, dict):
                    continue
                owner = repo_data.get("owner")
                repo = repo_data.get("repo")
                if not owner or not repo:
                    continue
                repos[str(alias)] = RepoConfig(
                    alias=str(alias),
                    owner=str(owner),
                    repo=str(repo),
                    default_ref=str(repo_data.get("default_ref") or settings.github_default_ref),
                    workflows={str(k): str(v) for k, v in (repo_data.get("workflows") or {}).items()},
                )

        if raw_github.get("owner") and raw_github.get("repo"):
            repos["default"] = RepoConfig(
                alias="default",
                owner=str(raw_github["owner"]),
                repo=str(raw_github["repo"]),
                default_ref=str(raw_github.get("default_ref") or settings.github_default_ref),
                workflows={str(k): str(v) for k, v in (raw_github.get("workflows") or {}).items()},
            )

    if repos and default_repo_alias not in repos:
        default_repo_alias = next(iter(repos))

    return repos, default_repo_alias


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None and str(value).strip():
            return value
    return None
