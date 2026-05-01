from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import capabilities as cap
from .clients import GitHubClient, NapCatClient
from .message_store import MessageStore
from .settings import BridgeConfig, Settings
from .state import BridgeState


class OneBotCallRequest(BaseModel):
    run_id: str
    action: str = Field(min_length=1, max_length=100)
    params: dict[str, Any] = Field(default_factory=dict)


class SendMessageRequest(BaseModel):
    run_id: str
    group_id: str
    text: str = Field(min_length=1, max_length=4000)


class ReplyMessageRequest(BaseModel):
    run_id: str
    message_id: str
    text: str = Field(min_length=1, max_length=4000)


class SendFaceRequest(BaseModel):
    run_id: str
    group_id: str
    face_id: str


class SetGroupCardRequest(BaseModel):
    run_id: str
    group_id: str
    user_id: str
    card: str = Field(max_length=60)


class SetGroupBanRequest(BaseModel):
    run_id: str
    group_id: str
    user_id: str
    duration: int = Field(ge=0, le=2_592_000)


class DeleteMsgRequest(BaseModel):
    run_id: str
    message_id: str


class GroupInfoRequest(BaseModel):
    run_id: str
    group_id: str


class GroupMemberInfoRequest(BaseModel):
    run_id: str
    group_id: str
    user_id: str
    no_cache: bool = False


class GroupMemberListRequest(BaseModel):
    run_id: str
    group_id: str


class RepoRequest(BaseModel):
    run_id: str
    repo: str | None = None


class PrRequest(RepoRequest):
    number: int = Field(ge=1)


class WorkflowStatusRequest(RepoRequest):
    workflow: str | None = None
    branch: str | None = None
    limit: int = Field(default=5, ge=1, le=20)


def build_skill_router(
    *,
    settings: Settings,
    config: BridgeConfig,
    state: BridgeState,
    store: MessageStore,
    napcat: NapCatClient,
    github: GitHubClient,
) -> APIRouter:
    router = APIRouter(prefix="/skills", tags=["skills"])

    @router.post("/onebot/call")
    async def onebot_call(payload: OneBotCallRequest, request: Request) -> dict[str, Any]:
        _verify_skill_token(request, settings)
        group_id = _group_id_from_params(payload.params)
        _authorize(state, run_id=payload.run_id, tool=cap.ONEBOT_CALL, group_id=group_id)
        _authorize_onebot_action(settings, payload.action)
        data = await napcat.call(payload.action, payload.params)
        message_id = _response_message_id(data)
        if message_id and group_id:
            state.add_bot_message_id(group_id, message_id)
        return {"ok": True, "action": payload.action, "data": data.get("data", data)}

    @router.post("/qq/send_message")
    async def qq_send_message(payload: SendMessageRequest, request: Request) -> dict[str, Any]:
        _verify_skill_token(request, settings)
        _authorize(state, run_id=payload.run_id, tool=cap.QQ_SEND_MESSAGE, group_id=payload.group_id)
        data = await napcat.send_msg(message_type="group", group_id=payload.group_id, message=payload.text)
        message_id = _response_message_id(data)
        if message_id:
            state.add_bot_message_id(payload.group_id, message_id)
        return {"ok": True, "message_id": message_id}

    @router.post("/qq/reply_message")
    async def qq_reply_message(payload: ReplyMessageRequest, request: Request) -> dict[str, Any]:
        _verify_skill_token(request, settings)
        source = store.get_message(payload.message_id) or state.find_message(payload.message_id)
        if not source or not source.get("group_id"):
            raise HTTPException(status_code=404, detail="message_id not found in bridge state")
        group_id = str(source["group_id"])
        _authorize(state, run_id=payload.run_id, tool=cap.QQ_REPLY_MESSAGE, group_id=group_id)
        data = await napcat.send_msg(
            message_type="group",
            group_id=group_id,
            message=[
                {"type": "reply", "data": {"id": payload.message_id}},
                {"type": "text", "data": {"text": payload.text}},
            ],
        )
        message_id = _response_message_id(data)
        if message_id:
            state.add_bot_message_id(group_id, message_id)
        return {"ok": True, "group_id": group_id, "message_id": message_id}

    @router.post("/qq/send_face")
    async def qq_send_face(payload: SendFaceRequest, request: Request) -> dict[str, Any]:
        _verify_skill_token(request, settings)
        _authorize(state, run_id=payload.run_id, tool=cap.QQ_SEND_FACE, group_id=payload.group_id)
        data = await napcat.send_msg(
            message_type="group",
            group_id=payload.group_id,
            message=[{"type": "face", "data": {"id": payload.face_id}}],
        )
        message_id = _response_message_id(data)
        if message_id:
            state.add_bot_message_id(payload.group_id, message_id)
        return {"ok": True, "message_id": message_id}

    @router.post("/qq/set_group_card")
    async def qq_set_group_card(payload: SetGroupCardRequest, request: Request) -> dict[str, Any]:
        _verify_skill_token(request, settings)
        _authorize(state, run_id=payload.run_id, tool=cap.QQ_SET_GROUP_CARD, group_id=payload.group_id)
        data = await napcat.set_group_card(payload.group_id, payload.user_id, payload.card)
        return {"ok": True, "data": data.get("data")}

    @router.post("/qq/set_group_ban")
    async def qq_set_group_ban(payload: SetGroupBanRequest, request: Request) -> dict[str, Any]:
        _verify_skill_token(request, settings)
        _authorize(state, run_id=payload.run_id, tool=cap.QQ_SET_GROUP_BAN, group_id=payload.group_id)
        data = await napcat.set_group_ban(payload.group_id, payload.user_id, payload.duration)
        return {"ok": True, "data": data.get("data")}

    @router.post("/qq/delete_msg")
    async def qq_delete_msg(payload: DeleteMsgRequest, request: Request) -> dict[str, Any]:
        _verify_skill_token(request, settings)
        source = store.get_message(payload.message_id) or state.find_message(payload.message_id)
        if not source or not source.get("group_id"):
            raise HTTPException(status_code=404, detail="message_id not found in bridge state")
        group_id = str(source["group_id"])
        _authorize(state, run_id=payload.run_id, tool=cap.QQ_DELETE_MSG, group_id=group_id)
        data = await napcat.delete_msg(payload.message_id)
        return {"ok": True, "data": data.get("data")}

    @router.post("/qq/get_group_info")
    async def qq_get_group_info(payload: GroupInfoRequest, request: Request) -> dict[str, Any]:
        _verify_skill_token(request, settings)
        _authorize(state, run_id=payload.run_id, tool=cap.QQ_GET_GROUP_INFO, group_id=payload.group_id)
        return await napcat.get_group_info(payload.group_id)

    @router.post("/qq/get_group_member_info")
    async def qq_get_group_member_info(payload: GroupMemberInfoRequest, request: Request) -> dict[str, Any]:
        _verify_skill_token(request, settings)
        _authorize(state, run_id=payload.run_id, tool=cap.QQ_GET_GROUP_MEMBER_INFO, group_id=payload.group_id)
        return await napcat.get_group_member_info(payload.group_id, payload.user_id, payload.no_cache)

    @router.post("/qq/get_group_member_list")
    async def qq_get_group_member_list(payload: GroupMemberListRequest, request: Request) -> dict[str, Any]:
        _verify_skill_token(request, settings)
        _authorize(state, run_id=payload.run_id, tool=cap.QQ_GET_GROUP_MEMBER_LIST, group_id=payload.group_id)
        return await napcat.get_group_member_list(payload.group_id)

    @router.post("/github/list_prs")
    async def github_list_prs(payload: RepoRequest, request: Request) -> dict[str, Any]:
        _verify_skill_token(request, settings)
        repo = config.repo(payload.repo)
        _authorize(state, run_id=payload.run_id, tool=cap.GITHUB_LIST_PRS, repo=repo.alias)
        prs = await github.list_open_prs(repo)
        return {"ok": True, "repo": repo.slug, "pull_requests": [_compact_pr(pr) for pr in prs]}

    @router.post("/github/get_pr")
    async def github_get_pr(payload: PrRequest, request: Request) -> dict[str, Any]:
        _verify_skill_token(request, settings)
        repo = config.repo(payload.repo)
        _authorize(state, run_id=payload.run_id, tool=cap.GITHUB_GET_PR, repo=repo.alias)
        pr = await github.get_pr(repo, payload.number)
        return {"ok": True, "repo": repo.slug, "pull_request": _compact_pr(pr)}

    @router.post("/github/get_issue")
    async def github_get_issue(payload: PrRequest, request: Request) -> dict[str, Any]:
        _verify_skill_token(request, settings)
        repo = config.repo(payload.repo)
        _authorize(state, run_id=payload.run_id, tool=cap.GITHUB_GET_ISSUE, repo=repo.alias)
        issue = await github.get_issue(repo, payload.number)
        return {"ok": True, "repo": repo.slug, "issue": _compact_issue(issue)}

    @router.post("/github/get_workflow_status")
    async def github_get_workflow_status(payload: WorkflowStatusRequest, request: Request) -> dict[str, Any]:
        _verify_skill_token(request, settings)
        repo = config.repo(payload.repo)
        _authorize(state, run_id=payload.run_id, tool=cap.GITHUB_WORKFLOW_STATUS, repo=repo.alias)
        workflow_id = repo.workflow_id(payload.workflow) if payload.workflow else None
        runs = await github.list_workflow_runs(repo, workflow_id=workflow_id, branch=payload.branch, per_page=payload.limit)
        return {"ok": True, "repo": repo.slug, "workflow": workflow_id, "runs": [_compact_run(run) for run in runs]}

    return router


def _verify_skill_token(request: Request, settings: Settings) -> None:
    expected = settings.qqbridge_skill_token
    if not expected:
        raise HTTPException(status_code=503, detail="QQBRIDGE_SKILL_TOKEN is not configured")
    header_token = request.headers.get("x-qqbridge-skill-token")
    authorization = request.headers.get("authorization", "")
    if header_token == expected or authorization == f"Bearer {expected}":
        return
    raise HTTPException(status_code=401, detail="invalid skill token")


def _authorize(
    state: BridgeState,
    *,
    run_id: str,
    tool: str,
    group_id: str | None = None,
    repo: str | None = None,
) -> dict[str, Any]:
    try:
        return state.authorize_agent_tool(run_id=run_id, tool=tool, group_id=group_id, repo=repo)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _authorize_onebot_action(settings: Settings, action: str) -> None:
    allowed = cap.onebot_actions_for_level(settings.skill_onebot_level)
    if allowed is None:
        return
    if action not in allowed:
        raise HTTPException(status_code=403, detail=f"onebot action is not allowed at this level: {action}")


def _group_id_from_params(params: dict[str, Any]) -> str | None:
    group_id = params.get("group_id")
    return str(group_id) if group_id is not None and str(group_id).strip() else None


def _response_message_id(data: dict[str, Any]) -> str | None:
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    message_id = payload.get("message_id") if isinstance(payload, dict) else None
    return str(message_id) if message_id is not None else None


def _compact_pr(pr: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": pr.get("number"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "draft": pr.get("draft"),
        "user": (pr.get("user") or {}).get("login") if isinstance(pr.get("user"), dict) else None,
        "head": (pr.get("head") or {}).get("ref") if isinstance(pr.get("head"), dict) else None,
        "base": (pr.get("base") or {}).get("ref") if isinstance(pr.get("base"), dict) else None,
        "html_url": pr.get("html_url"),
        "body": pr.get("body"),
    }


def _compact_issue(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "user": (issue.get("user") or {}).get("login") if isinstance(issue.get("user"), dict) else None,
        "labels": [label.get("name") for label in issue.get("labels", []) if isinstance(label, dict)],
        "html_url": issue.get("html_url"),
        "body": issue.get("body"),
    }


def _compact_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": run.get("id"),
        "run_number": run.get("run_number"),
        "name": run.get("name"),
        "display_title": run.get("display_title"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "head_branch": run.get("head_branch"),
        "event": run.get("event"),
        "html_url": run.get("html_url"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
    }
