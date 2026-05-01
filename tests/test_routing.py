from pathlib import Path

import pytest

from qqbridge.clients import GitHubClient, HermesClient, NapCatClient
from qqbridge.commands import build_registry
from qqbridge.message_store import MessageStore
from qqbridge.router import BridgeService
from qqbridge.app import _next_ambient_delay
from qqbridge.settings import GroupConfig, Settings
from qqbridge.state import BridgeState


class FakeHermes(HermesClient):
    def __init__(self, answer: str = "收到") -> None:
        self.answer = answer
        self.calls: list[dict[str, object]] = []

    async def chat(self, system_prompt: str, history: list[dict[str, str]], user_content: str) -> str:
        self.calls.append({"prompt": system_prompt, "history": history, "user": user_content})
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

    async def trigger_workflow(self, repo, workflow_id: str, ref: str, inputs: dict[str, str] | None = None) -> None:
        self.triggered.append({"repo": repo.slug, "workflow_id": workflow_id, "ref": ref, "inputs": inputs or {}})


@pytest.fixture
def service(tmp_path: Path) -> BridgeService:
    settings = Settings(
        bot_qq_id="999",
        bot_names=["桥桥"],
        admin_qq_ids=["111"],
        group_default_autonomous_enabled=True,
        state_path=tmp_path / "state.json",
        message_store_path=tmp_path / "messages.sqlite3",
        github_owner="org",
        github_repo="repo",
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

    assert result["action"] == "llm_reply"
    assert service.hermes.calls
    assert service.napcat.sent[0]["message_type"] == "private"


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
        {"repo": "org/repo", "workflow_id": "release.yml", "ref": "main", "inputs": {"tag": "v1.0.0"}}
    ]
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
async def test_ambient_tick_sends_structured_agent_reply(service: BridgeService) -> None:
    service.hermes.answer = '{"actions":[{"type":"send","reply_to":"5","text":"这个我可以看一下，先别急发版。"}]}'
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

    assert result["groups"][0]["action"] == "replied"
    assert service.napcat.sent[0]["message_type"] == "group"
    assert service.napcat.sent[0]["message"][0] == {"type": "reply", "data": {"id": "5"}}


def test_ambient_delay_is_random_but_clamped() -> None:
    settings = Settings(
        ambient_interval_seconds=3600,
        ambient_jitter_min_seconds=300,
        ambient_jitter_max_seconds=10800,
    )

    delays = [_next_ambient_delay(settings) for _ in range(200)]

    assert all(300 <= delay <= 10800 for delay in delays)
    assert len({round(delay, 2) for delay in delays}) > 50
