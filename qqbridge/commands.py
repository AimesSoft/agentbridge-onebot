from __future__ import annotations

from dataclasses import dataclass
import shlex
from typing import Awaitable, Callable

from .clients import GitHubClient, HermesClient, NapCatClient
from .settings import BridgeConfig, GroupConfig, RepoConfig
from .state import BridgeState


@dataclass(slots=True)
class CommandContext:
    user_id: str
    group_id: str | None
    is_admin: bool
    conversation_key: str
    config: BridgeConfig
    group_config: GroupConfig | None
    state: BridgeState
    github: GitHubClient
    hermes: HermesClient
    napcat: NapCatClient


@dataclass(slots=True)
class CommandResult:
    text: str
    private: bool = False


CommandHandler = Callable[[CommandContext, list[str]], Awaitable[CommandResult]]


@dataclass(slots=True)
class CommandSpec:
    name: str
    handler: CommandHandler
    prefixes: tuple[str, ...]
    requires_admin: bool = False
    aliases: tuple[str, ...] = ()
    help_text: str = ""
    sensitive: bool = False


class CommandRegistry:
    def __init__(self, admin_prefix: str, public_prefix: str = "/") -> None:
        self.admin_prefix = admin_prefix
        self.public_prefix = public_prefix
        self._commands: dict[str, CommandSpec] = {}

    def register(
        self,
        name: str,
        *,
        requires_admin: bool = False,
        aliases: tuple[str, ...] = (),
        help_text: str = "",
        sensitive: bool = False,
        prefixes: tuple[str, ...] | None = None,
    ) -> Callable[[CommandHandler], CommandHandler]:
        def decorator(handler: CommandHandler) -> CommandHandler:
            allowed_prefixes = prefixes or ((self.admin_prefix,) if requires_admin else (self.admin_prefix, self.public_prefix))
            spec = CommandSpec(
                name=name,
                handler=handler,
                prefixes=allowed_prefixes,
                requires_admin=requires_admin,
                aliases=aliases,
                help_text=help_text,
                sensitive=sensitive,
            )
            for key in (name, *aliases):
                self._commands[key.lower()] = spec
            return handler

        return decorator

    def is_command_text(self, text: str) -> bool:
        stripped = text.strip()
        return any(stripped.startswith(prefix) for prefix in self._prefixes())

    async def dispatch(self, text: str, ctx: CommandContext) -> CommandResult | None:
        stripped = text.strip()
        matched_prefix = self._match_prefix(stripped)
        if matched_prefix is None:
            return None
        if matched_prefix == self.admin_prefix and matched_prefix != self.public_prefix and not ctx.is_admin:
            return None
        body = stripped[len(matched_prefix) :].strip()
        if not body:
            return None
        try:
            parts = shlex.split(body)
        except ValueError as exc:
            return CommandResult(f"命令解析失败：{exc}", private=True)
        if not parts:
            return None
        name = parts[0].lower()
        spec = self._commands.get(name)
        if not spec:
            if ctx.is_admin:
                return CommandResult(f"未知命令：{parts[0]}。发送 {self.admin_prefix}help 查看可用命令。", private=True)
            return None
        if matched_prefix not in spec.prefixes:
            return None
        if spec.requires_admin and not ctx.is_admin:
            return CommandResult("权限不够。", private=True)
        try:
            result = await spec.handler(ctx, parts[1:])
        except Exception as exc:
            return CommandResult(f"命令执行失败：{exc}", private=spec.sensitive or spec.requires_admin)
        if spec.sensitive or spec.requires_admin:
            result.private = True
        return result

    def help_lines(self, is_admin: bool) -> list[str]:
        seen: set[str] = set()
        lines: list[str] = []
        for spec in self._commands.values():
            if spec.name in seen:
                continue
            seen.add(spec.name)
            if spec.requires_admin and not is_admin:
                continue
            suffix = "（管理员）" if spec.requires_admin else ""
            prefix = self.admin_prefix if spec.requires_admin else self.public_prefix
            lines.append(f"{prefix}{spec.name} {spec.help_text}{suffix}".strip())
        return lines

    def _prefixes(self) -> tuple[str, ...]:
        prefixes = tuple(dict.fromkeys(prefix for prefix in (self.admin_prefix, self.public_prefix) if prefix))
        return tuple(sorted(prefixes, key=len, reverse=True))

    def _match_prefix(self, text: str) -> str | None:
        for prefix in self._prefixes():
            if text.startswith(prefix):
                return prefix
        return None


def build_registry(admin_prefix: str, public_prefix: str = "/") -> CommandRegistry:
    registry = CommandRegistry(admin_prefix, public_prefix)

    @registry.register("help", aliases=("h",), help_text="查看命令")
    async def help_cmd(ctx: CommandContext, _: list[str]) -> CommandResult:
        lines = ["可用命令：", *registry.help_lines(ctx.is_admin)]
        return CommandResult("\n".join(lines))

    @registry.register("ping", help_text="检查 bridge 是否在线")
    async def ping_cmd(_: CommandContext, __: list[str]) -> CommandResult:
        return CommandResult("pong")

    @registry.register("forget", help_text="清空当前对话上下文")
    async def forget_cmd(ctx: CommandContext, _: list[str]) -> CommandResult:
        ctx.state.clear_conversation(ctx.conversation_key)
        return CommandResult("已清空这条对话线的上下文。")

    @registry.register("status", help_text="[workflow] [repo=alias] [branch=name] 查看 GitHub Actions 状态")
    async def status_cmd(ctx: CommandContext, args: list[str]) -> CommandResult:
        options = parse_options(args)
        repo = resolve_repo(ctx.config, options)
        workflow_name = options.kv.get("workflow") or (options.positionals[0] if options.positionals else None)
        workflow_id = repo.workflow_id(workflow_name) if workflow_name else None
        branch = options.kv.get("branch")
        runs = await ctx.github.list_workflow_runs(repo, workflow_id=workflow_id, branch=branch, per_page=5)
        if not runs:
            target = workflow_id or "all workflows"
            return CommandResult(f"{repo.slug} 暂时没有 {target} 的 workflow run。")
        lines = [f"{repo.slug} 最近 Actions："]
        for run in runs[:5]:
            status = run.get("conclusion") or run.get("status") or "unknown"
            title = run.get("name") or run.get("display_title") or "workflow"
            ref = run.get("head_branch") or "-"
            number = run.get("run_number") or run.get("id")
            url = run.get("html_url") or ""
            lines.append(f"#{number} {title} [{ref}] {status}\n{url}".strip())
        return CommandResult("\n".join(lines))

    @registry.register("pr", help_text="[repo=alias] 列出打开的 PR")
    async def pr_cmd(ctx: CommandContext, args: list[str]) -> CommandResult:
        options = parse_options(args)
        repo = resolve_repo(ctx.config, options)
        prs = await ctx.github.list_open_prs(repo)
        if not prs:
            return CommandResult(f"{repo.slug} 现在没有打开的 PR。")
        lines = [f"{repo.slug} 打开的 PR："]
        for pr in prs[:5]:
            lines.append(f"#{pr.get('number')} {pr.get('title')}\n{pr.get('html_url')}")
        return CommandResult("\n".join(lines))

    @registry.register(
        "release",
        requires_admin=True,
        sensitive=True,
        help_text="[ref] [repo=alias] [key=value...] 触发 release workflow",
    )
    async def release_cmd(ctx: CommandContext, args: list[str]) -> CommandResult:
        return await dispatch_workflow(ctx, args, default_workflow="release")

    @registry.register(
        "deploy",
        requires_admin=True,
        sensitive=True,
        help_text="[ref] [repo=alias] [key=value...] 触发 deploy workflow",
    )
    async def deploy_cmd(ctx: CommandContext, args: list[str]) -> CommandResult:
        return await dispatch_workflow(ctx, args, default_workflow="deploy")

    @registry.register("repos", requires_admin=True, help_text="查看 repo 配置")
    async def repos_cmd(ctx: CommandContext, _: list[str]) -> CommandResult:
        if not ctx.config.repos:
            return CommandResult("尚未配置 GitHub repo。", private=True)
        lines = ["已配置 repo："]
        for alias, repo in ctx.config.repos.items():
            marker = "*" if alias == ctx.config.default_repo_alias else "-"
            workflows = ", ".join(f"{k}:{v}" for k, v in repo.workflows.items()) or "none"
            lines.append(f"{marker} {alias} = {repo.slug} ref={repo.default_ref} workflows=[{workflows}]")
        return CommandResult("\n".join(lines), private=True)

    @registry.register("group", requires_admin=True, help_text="show|on|off|cooldown S|keyword add/del WORD")
    async def group_cmd(ctx: CommandContext, args: list[str]) -> CommandResult:
        if not ctx.group_id:
            return CommandResult("这个命令需要在群聊里使用。", private=True)
        if not args or args[0] == "show":
            cfg = ctx.state.effective_group_config(ctx.group_id, ctx.config.group_config(ctx.group_id))
            return CommandResult(format_group_config(ctx.group_id, cfg), private=True)

        action = args[0].lower()
        if action in {"on", "enable"}:
            ctx.state.set_group_override(ctx.group_id, {"autonomous_enabled": True})
            return CommandResult("已开启本群自主互动。", private=True)
        if action in {"off", "disable"}:
            ctx.state.set_group_override(ctx.group_id, {"autonomous_enabled": False})
            return CommandResult("已关闭本群自主互动。", private=True)
        if action == "cooldown" and len(args) >= 2:
            cooldown = max(0, int(args[1]))
            ctx.state.set_group_override(ctx.group_id, {"min_seconds_between_replies": cooldown})
            return CommandResult(f"本群自主回复冷却已设为 {cooldown}s。", private=True)
        if action == "keyword" and len(args) >= 3:
            op = args[1].lower()
            word = " ".join(args[2:]).strip()
            cfg = ctx.state.effective_group_config(ctx.group_id, ctx.config.group_config(ctx.group_id))
            keywords = list(dict.fromkeys(cfg.keywords))
            if op in {"add", "+"} and word:
                keywords.append(word)
                keywords = list(dict.fromkeys(keywords))
                ctx.state.set_group_override(ctx.group_id, {"keywords": keywords})
                return CommandResult(f"已添加关键词：{word}", private=True)
            if op in {"del", "remove", "-"} and word:
                keywords = [item for item in keywords if item != word]
                ctx.state.set_group_override(ctx.group_id, {"keywords": keywords})
                return CommandResult(f"已删除关键词：{word}", private=True)
        return CommandResult(
            "用法：group show|on|off|cooldown S|keyword add/del WORD",
            private=True,
        )

    @registry.register("health", requires_admin=True, help_text="检查 Hermes/NapCat")
    async def health_cmd(ctx: CommandContext, _: list[str]) -> CommandResult:
        parts = ["bridge: ok"]
        try:
            hermes = await ctx.hermes.health()
            parts.append(f"hermes: {hermes.get('status', 'ok')}")
        except Exception as exc:
            parts.append(f"hermes: error {exc}")
        try:
            napcat = await ctx.napcat.health()
            parts.append(f"napcat: {napcat.get('status', 'ok')}")
        except Exception as exc:
            parts.append(f"napcat: error {exc}")
        return CommandResult("\n".join(parts), private=True)

    return registry


@dataclass(slots=True)
class ParsedOptions:
    positionals: list[str]
    kv: dict[str, str]


def parse_options(args: list[str]) -> ParsedOptions:
    positionals: list[str] = []
    kv: dict[str, str] = {}
    for arg in args:
        if "=" in arg:
            key, value = arg.split("=", 1)
            kv[key.strip().lower()] = value.strip()
        else:
            positionals.append(arg)
    return ParsedOptions(positionals=positionals, kv=kv)


def resolve_repo(config: BridgeConfig, options: ParsedOptions) -> RepoConfig:
    alias = options.kv.pop("repo", None)
    return config.repo(alias)


async def dispatch_workflow(ctx: CommandContext, args: list[str], *, default_workflow: str) -> CommandResult:
    options = parse_options(args)
    repo = resolve_repo(ctx.config, options)
    workflow_alias = options.kv.pop("workflow", default_workflow)
    workflow_id = repo.workflow_id(workflow_alias)
    ref = options.kv.pop("ref", None) or (options.positionals[0] if options.positionals else repo.default_ref)
    inputs = dict(options.kv)
    await ctx.github.trigger_workflow(repo, workflow_id=workflow_id, ref=ref, inputs=inputs)
    input_text = f" inputs={inputs}" if inputs else ""
    return CommandResult(
        f"已触发 {repo.slug} 的 {workflow_alias} workflow。\nworkflow={workflow_id}\nref={ref}{input_text}",
        private=True,
    )


def format_group_config(group_id: str, cfg: GroupConfig) -> str:
    keywords = ", ".join(cfg.keywords) or "none"
    return (
        f"群 {group_id} 配置：\n"
        f"autonomous_enabled={cfg.autonomous_enabled}\n"
        f"cooldown={cfg.min_seconds_between_replies}s\n"
        f"keywords={keywords}"
    )
