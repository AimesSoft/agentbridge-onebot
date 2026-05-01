from fastapi import FastAPI
import httpx
import pytest

from qqbridge.clients import GitHubClient, NapCatClient
from qqbridge.capabilities import GROUP_AMBIENT_TOOLS
from qqbridge.message_store import MessageStore
from qqbridge.settings import Settings, load_bridge_config
from qqbridge.skill_api import build_skill_router
from qqbridge.state import BridgeState


class FakeNapCat(NapCatClient):
    def __init__(self) -> None:
        self.sent = []
        self.calls = []

    async def send_msg(self, *, message_type: str, message, user_id: str | None = None, group_id: str | None = None):
        self.sent.append({"message_type": message_type, "message": message, "user_id": user_id, "group_id": group_id})
        return {"ok": True, "retcode": 0, "data": {"message_id": 99}}

    async def call(self, action: str, payload: dict):
        self.calls.append({"action": action, "payload": payload})
        return {"ok": True, "retcode": 0, "data": {"action": action, "message_id": 101}}


class FakeGitHub(GitHubClient):
    async def list_open_prs(self, repo, per_page: int = 5):
        return [{"number": 7, "title": "Fix workflow", "state": "open", "html_url": "https://example.test/pr/7"}]


def make_client(tmp_path, *, onebot_level: str = "group_admin"):
    settings = Settings(
        qqbridge_skill_token="secret",
        skill_onebot_level=onebot_level,
        state_path=tmp_path / "state.json",
        message_store_path=tmp_path / "messages.sqlite3",
        qqbridge_config=None,
        github_owner="org",
        github_repo="repo",
    )
    config = load_bridge_config(settings)
    state = BridgeState(settings.state_path, settings.max_history_messages)
    store = MessageStore(settings.message_store_path, tmp_path / "archive")
    napcat = FakeNapCat()
    github = FakeGitHub(settings)
    app = FastAPI()
    app.include_router(
        build_skill_router(settings=settings, config=config, state=state, store=store, napcat=napcat, github=github)
    )
    return app, state, store, napcat


async def post_json(app: FastAPI, path: str, *, headers=None, json=None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(path, headers=headers, json=json)


def create_run(state: BridgeState, group_id: str = "123"):
    return state.create_agent_run(
        mode="ambient",
        group_id=group_id,
        allowed_tools=GROUP_AMBIENT_TOOLS,
        allowed_repos=["default"],
        ttl_seconds=900,
    )["run_id"]


@pytest.mark.asyncio
async def test_skill_auth_required(tmp_path) -> None:
    app, _, _, _ = make_client(tmp_path)

    response = await post_json(app, "/skills/qq/send_message", json={"run_id": "missing", "group_id": "1", "text": "hi"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_run_id_required(tmp_path) -> None:
    app, _, _, _ = make_client(tmp_path)

    response = await post_json(
        app,
        "/skills/qq/send_message",
        headers={"X-QQBridge-Skill-Token": "secret"},
        json={"run_id": "missing", "group_id": "1", "text": "hi"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reply_message_skill(tmp_path) -> None:
    app, state, store, napcat = make_client(tmp_path)
    state.append_group_message("123", "Alice", "1", "hello", "42")
    store.add_message(
        message_id="42",
        message_type="group",
        group_id="123",
        user_id="1",
        sender_name="Alice",
        plain_text="hello",
        raw_message="hello",
        segments=[],
    )
    run_id = create_run(state)

    response = await post_json(
        app,
        "/skills/qq/reply_message",
        headers={"X-QQBridge-Skill-Token": "secret"},
        json={"run_id": run_id, "message_id": "42", "text": "收到"},
    )

    assert response.status_code == 200
    assert response.json()["group_id"] == "123"
    assert napcat.sent[0]["message"][0] == {"type": "reply", "data": {"id": "42"}}


@pytest.mark.asyncio
async def test_wrong_group_denied(tmp_path) -> None:
    app, state, _, _ = make_client(tmp_path)
    run_id = create_run(state, group_id="123")

    response = await post_json(
        app,
        "/skills/qq/send_message",
        headers={"X-QQBridge-Skill-Token": "secret"},
        json={"run_id": run_id, "group_id": "999", "text": "不该发"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_onebot_call_allows_group_admin_action(tmp_path) -> None:
    app, state, _, napcat = make_client(tmp_path)
    run_id = create_run(state, group_id="123")

    response = await post_json(
        app,
        "/skills/onebot/call",
        headers={"X-QQBridge-Skill-Token": "secret"},
        json={"run_id": run_id, "action": "set_group_ban", "params": {"group_id": 123, "user_id": 456, "duration": 60}},
    )

    assert response.status_code == 200
    assert napcat.calls[0]["action"] == "set_group_ban"


@pytest.mark.asyncio
async def test_onebot_call_respects_level(tmp_path) -> None:
    app, state, _, _ = make_client(tmp_path, onebot_level="group_read")
    run_id = create_run(state, group_id="123")

    response = await post_json(
        app,
        "/skills/onebot/call",
        headers={"X-QQBridge-Skill-Token": "secret"},
        json={"run_id": run_id, "action": "set_group_ban", "params": {"group_id": 123, "user_id": 456, "duration": 60}},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_github_list_prs_skill(tmp_path) -> None:
    app, state, _, _ = make_client(tmp_path)
    run_id = create_run(state)

    response = await post_json(
        app,
        "/skills/github/list_prs",
        headers={"X-QQBridge-Skill-Token": "secret"},
        json={"run_id": run_id},
    )

    assert response.status_code == 200
    assert response.json()["pull_requests"][0]["number"] == 7
