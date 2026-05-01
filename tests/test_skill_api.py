from fastapi import FastAPI
from fastapi.testclient import TestClient

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
    return TestClient(app), state, store, napcat


def create_run(state: BridgeState, group_id: str = "123"):
    return state.create_agent_run(
        mode="ambient",
        group_id=group_id,
        allowed_tools=GROUP_AMBIENT_TOOLS,
        allowed_repos=["default"],
        ttl_seconds=900,
    )["run_id"]


def test_skill_auth_required(tmp_path) -> None:
    client, _, _, _ = make_client(tmp_path)

    response = client.post("/skills/qq/send_message", json={"run_id": "missing", "group_id": "1", "text": "hi"})

    assert response.status_code == 401


def test_run_id_required(tmp_path) -> None:
    client, _, _, _ = make_client(tmp_path)

    response = client.post(
        "/skills/qq/send_message",
        headers={"X-QQBridge-Skill-Token": "secret"},
        json={"run_id": "missing", "group_id": "1", "text": "hi"},
    )

    assert response.status_code == 403


def test_reply_message_skill(tmp_path) -> None:
    client, state, store, napcat = make_client(tmp_path)
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

    response = client.post(
        "/skills/qq/reply_message",
        headers={"X-QQBridge-Skill-Token": "secret"},
        json={"run_id": run_id, "message_id": "42", "text": "收到"},
    )

    assert response.status_code == 200
    assert response.json()["group_id"] == "123"
    assert napcat.sent[0]["message"][0] == {"type": "reply", "data": {"id": "42"}}


def test_wrong_group_denied(tmp_path) -> None:
    client, state, _, _ = make_client(tmp_path)
    run_id = create_run(state, group_id="123")

    response = client.post(
        "/skills/qq/send_message",
        headers={"X-QQBridge-Skill-Token": "secret"},
        json={"run_id": run_id, "group_id": "999", "text": "不该发"},
    )

    assert response.status_code == 403


def test_onebot_call_allows_group_admin_action(tmp_path) -> None:
    client, state, _, napcat = make_client(tmp_path)
    run_id = create_run(state, group_id="123")

    response = client.post(
        "/skills/onebot/call",
        headers={"X-QQBridge-Skill-Token": "secret"},
        json={"run_id": run_id, "action": "set_group_ban", "params": {"group_id": 123, "user_id": 456, "duration": 60}},
    )

    assert response.status_code == 200
    assert napcat.calls[0]["action"] == "set_group_ban"


def test_onebot_call_respects_level(tmp_path) -> None:
    client, state, _, _ = make_client(tmp_path, onebot_level="group_read")
    run_id = create_run(state, group_id="123")

    response = client.post(
        "/skills/onebot/call",
        headers={"X-QQBridge-Skill-Token": "secret"},
        json={"run_id": run_id, "action": "set_group_ban", "params": {"group_id": 123, "user_id": 456, "duration": 60}},
    )

    assert response.status_code == 403


def test_github_list_prs_skill(tmp_path) -> None:
    client, state, _, _ = make_client(tmp_path)
    run_id = create_run(state)

    response = client.post(
        "/skills/github/list_prs",
        headers={"X-QQBridge-Skill-Token": "secret"},
        json={"run_id": run_id},
    )

    assert response.status_code == 200
    assert response.json()["pull_requests"][0]["number"] == 7
