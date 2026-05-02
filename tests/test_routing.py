from pathlib import Path

import pytest

from qqbridge.clients import GitHubClient, HermesClient, NapCatClient
from qqbridge.commands import build_registry, default_release_title
from qqbridge.message_store import MessageStore
from qqbridge.router import BridgeService
from qqbridge.app import _next_ambient_delay
from qqbridge.settings import GroupConfig, Settings
from qqbridge.state import BridgeState


class FakeHermes(HermesClient):
    def __init__(self, answer: str = "收到") -> None:
        self.answer = answer
        self.model = "hermes-agent"
        self.calls: list[dict[str, object]] = []

    async def chat(
        self,
        system_prompt: str,
        history: list[dict[str, str]],
        user_content: str,
        *,
        session_id: str | None = None,
    ) -> str:
        self.calls.append({"prompt": system_prompt, "history": history, "user": user_content, "session_id": session_id})
        return self.answer

    async def health(self) -> dict[str, object]:
        return {"status": "ok"}


class FakeNapCat(NapCatClient):
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_msg(self, *, message_type: str, message: object, user_id: str | None = None, group_id: str | None = None) -> dict[str, object]:
        self.sent.append({"message_type": message_type, "message": message, "user_id": user_id, "group_id": group_id})
        return {"status": "ok", "retcode": 0, "data": {"message_id": len(self.sent)}}

    async def health(self) -> dict[str, object]:
        return {"status": "ok"}


class FakeGitHub(GitHubClient):
    def __init__(self) -> None:
        self.triggered: list[dict[str, object]] = []
        self.workflow_queries: list[dict[str, object]] = []

    async def trigger_workflow(self, repo, workflow_id: str, ref: str, inputs: dict[str, str] | None = None) -> None:
        self.triggered.append({"repo": repo.slug, "workflow_id": workflow_id, "ref": ref, "inputs": inputs or {}})

    async def list_workflow_runs(
        self,
        repo,
        workflow_id: str | None = None,
        *,
        branch: str | None = None,
        per_page: int = 5,
    ) -> list[dict[str, object]]:
        self.workflow_queries.append(
            {"repo": repo.slug, "workflow_id": workflow_id, "branch": branch, "per_page": per_page}
        )
        return [
            {
                "run_number": 1,
                "name": "Build",
                "head_branch": branch or "main",
                "conclusion": "success",
                "html_url": "https://example.test/actions/1",
            }
        ]


@pytest.fixture
def service(tmp_path: Path) -> BridgeService:
    settings = Settings(
        bot_qq_id="999",
        bot_names=["桥桥"],
        admin_qq_ids=["111"],
        ambient_enabled=True,
        group_default_autonomous_enabled=True,
        state_path=tmp_path / "state.json",
        message_store_path=tmp_path / "messages.sqlite3",
        qqbridge_config=None,
        github_owner="org",
        github_repo="repo",
        github_release_workflow="release.yml",
        github_deploy_workflow="deploy.yml",
    )
    from qqbridge.settings import load_bridge_config

    config = load_bridge_config(settings)
    config.default_group.keywords.append("发版")
    return BridgeService(
        settings=settings,
        config=config,
        state=BridgeState(settings.state_path, settings.max_history_messages),
        store=MessageStore(settings.message_store_path, tmp_path / "archive"),
        hermes=FakeHermes(),
        napcat=FakeNapCat(),
        github=FakeGitHub(),
        commands=build_registry(settings.admin_prefix, settings.public_prefix),
    )


@pytest.mark.asyncio
async def test_private_message_routes_to_hermes(service: BridgeService) -> None:
    result = await service.handle_event(
        {
            "post_type": "message",
            "message_type": "private",
            "self_id": 999,
            "user_id": 222,
            "message_id": 1,
            "message": "你好",
        }
    )

    assert result["action"] == "agent_handoff"
    assert service.hermes.calls
    assert "qq.send_private_message" in service.hermes.calls[0]["user"]
    assert not service.napcat.sent


@pytest.mark.asyncio
async def test_group_message_without_trigger_is_ignored(service: BridgeService) -> None:
    service.config.default_group.autonomous_enabled = False
    result = await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 222,
            "message_id": 2,
            "message": "今天吃什么",
        }
    )

    assert result["action"] == "ignored"
    assert not service.hermes.calls


@pytest.mark.asyncio
async def test_group_llm_uses_hermes_group_session(service: BridgeService) -> None:
    result = await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 222,
            "message_id": 20,
            "message": "桥桥 你好",
        }
    )

    assert result["action"] == "agent_handoff"
    assert service.hermes.calls[0]["history"] == []
    assert service.hermes.calls[0]["session_id"] == service.state.hermes_session_id("group:333")


@pytest.mark.asyncio
async def test_mention_opens_group_attention_window(service: BridgeService) -> None:
    service.settings.group_attention_batch_interval_seconds = 0
    first = await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 222,
            "message_id": 22,
            "message": "桥桥 你怎么看？",
        }
    )
    second = await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 222,
            "message_id": 23,
            "message": "快点说",
        }
    )
    tick = await service.tick_group_attention()

    assert first["reason"] == "mention"
    assert second["action"] == "queued"
    assert second["reason"] == "active_group_attention"
    assert tick["groups"][0]["action"] == "agent_handoff"
    assert len(service.hermes.calls) == 2
    assert "active_group_attention" in service.hermes.calls[1]["user"]
    assert "快点说" in service.hermes.calls[1]["user"]


@pytest.mark.asyncio
async def test_group_attention_batches_messages_from_the_whole_group(service: BridgeService) -> None:
    service.settings.group_attention_batch_interval_seconds = 0
    await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 222,
            "message_id": 24,
            "message": "桥桥 你怎么看？",
        }
    )
    first_followup = await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 444,
            "message_id": 25,
            "message": "我插一句",
        }
    )
    second_followup = await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 222,
            "message_id": 26,
            "message": "那你快说",
        }
    )
    tick = await service.tick_group_attention()

    assert first_followup["action"] == "queued"
    assert second_followup["action"] == "queued"
    assert tick["groups"][0]["messages"] == 2
    assert len(service.hermes.calls) == 2
    assert "我插一句" in service.hermes.calls[1]["user"]
    assert "那你快说" in service.hermes.calls[1]["user"]


@pytest.mark.asyncio
async def test_forget_resets_hermes_session(service: BridgeService) -> None:
    old_session = service.state.hermes_session_id("group:333")
    result = await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 111,
            "message_id": 21,
            "message": "。忘记",
        }
    )

    assert result["action"] == "command"
    assert service.state.hermes_session_id("group:333") != old_session


@pytest.mark.asyncio
async def test_admin_release_triggers_github_and_private_ack(service: BridgeService) -> None:
    result = await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 111,
            "message_id": 3,
            "message": "。release main tag=v1.0.0",
        }
    )

    assert result["action"] == "command"
    assert service.github.triggered == [
        {
            "repo": "org/repo",
            "workflow_id": "release.yml",
            "ref": "main",
            "inputs": {"tag": "v1.0.0", "release_title": default_release_title()},
        }
    ]
    assert service.napcat.sent[0]["message_type"] == "private"


@pytest.mark.asyncio
async def test_admin_chinese_release_without_args_uses_defaults(service: BridgeService) -> None:
    result = await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 111,
            "message_id": 30,
            "message": "。发布",
        }
    )

    assert result["action"] == "command"
    assert service.github.triggered == [
        {
            "repo": "org/repo",
            "workflow_id": "release.yml",
            "ref": "main",
            "inputs": {"release_title": default_release_title()},
        }
    ]
    assert service.napcat.sent[0]["message_type"] == "private"


@pytest.mark.asyncio
async def test_admin_chinese_release_alias_triggers_github(service: BridgeService) -> None:
    result = await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 111,
            "message_id": 31,
            "message": "。发布 main 标题=2026.0501",
        }
    )

    assert result["action"] == "command"
    assert service.github.triggered == [
        {
            "repo": "org/repo",
            "workflow_id": "release.yml",
            "ref": "main",
            "inputs": {"release_title": "2026.0501"},
        }
    ]
    assert service.napcat.sent[0]["message_type"] == "private"


@pytest.mark.asyncio
async def test_admin_chinese_group_keyword_alias(service: BridgeService) -> None:
    result = await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 111,
            "message_id": 32,
            "message": "。群 关键词 添加 编译",
        }
    )

    assert result["action"] == "command"
    cfg = service.state.effective_group_config("333", service.config.group_config("333"))
    assert "编译" in cfg.keywords
    assert service.napcat.sent[0]["message_type"] == "private"


@pytest.mark.asyncio
async def test_chinese_status_workflow_alias(service: BridgeService) -> None:
    result = await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 111,
            "message_id": 33,
            "message": "。状态 发布 分支=main",
        }
    )

    assert result["action"] == "command"
    assert service.github.workflow_queries == [
        {"repo": "org/repo", "workflow_id": "release.yml", "branch": "main", "per_page": 5}
    ]
    assert "success" in service.napcat.sent[0]["message"]


@pytest.mark.asyncio
async def test_admin_model_command_reports_configuration(service: BridgeService) -> None:
    result = await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 111,
            "message_id": 34,
            "message": "。模型 pro",
        }
    )

    assert result["action"] == "command"
    assert service.hermes.model == "hermes-agent"
    assert "实际底层模型" in service.napcat.sent[0]["message"]
    assert service.napcat.sent[0]["message_type"] == "private"


@pytest.mark.asyncio
async def test_non_admin_admin_prefix_is_silent(service: BridgeService) -> None:
    result = await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 222,
            "message_id": 4,
            "message": "。release main",
        }
    )

    assert result["reason"] == "unknown_or_unauthorized_command"
    assert not service.github.triggered
    assert not service.napcat.sent


@pytest.mark.asyncio
async def test_ambient_tick_hands_unread_to_hermes(service: BridgeService) -> None:
    service.hermes.answer = "已通过 qq.send_message 处理"
    await service.handle_event(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "group_id": 333,
            "user_id": 222,
            "message_id": 5,
            "message": "release 好像失败了",
        }
    )

    result = await service.tick_ambient()

    assert result["groups"][0]["action"] == "agent_handoff"
    assert not service.napcat.sent
    assert service.state.unread_group_messages("333") == []


def test_ambient_delay_is_random_but_clamped() -> None:
    settings = Settings(
        ambient_interval_seconds=3600,
        ambient_jitter_min_seconds=300,
        ambient_jitter_max_seconds=10800,
    )

    delays = [_next_ambient_delay(settings) for _ in range(200)]

    assert all(300 <= delay <= 10800 for delay in delays)
    assert len({round(delay, 2) for delay in delays}) > 50
