#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Call AgentBridge skill APIs.")
    sub = parser.add_subparsers(dest="command", required=True)

    onebot = sub.add_parser("onebot-call")
    onebot.add_argument("--run-id", required=True)
    onebot.add_argument("--action", required=True)
    onebot.add_argument("--params-json", default="{}")

    send = sub.add_parser("send-message")
    send.add_argument("--run-id", required=True)
    send.add_argument("--group-id", required=True)
    send.add_argument("--text", required=True)

    reply = sub.add_parser("reply-message")
    reply.add_argument("--run-id", required=True)
    reply.add_argument("--message-id", required=True)
    reply.add_argument("--text", required=True)

    face = sub.add_parser("send-face")
    face.add_argument("--run-id", required=True)
    face.add_argument("--group-id", required=True)
    face.add_argument("--face-id", required=True)

    card = sub.add_parser("set-group-card")
    card.add_argument("--run-id", required=True)
    card.add_argument("--group-id", required=True)
    card.add_argument("--user-id", required=True)
    card.add_argument("--card", required=True)

    ban = sub.add_parser("set-group-ban")
    ban.add_argument("--run-id", required=True)
    ban.add_argument("--group-id", required=True)
    ban.add_argument("--user-id", required=True)
    ban.add_argument("--duration", type=int, required=True)

    delete = sub.add_parser("delete-msg")
    delete.add_argument("--run-id", required=True)
    delete.add_argument("--message-id", required=True)

    group_info = sub.add_parser("group-info")
    group_info.add_argument("--run-id", required=True)
    group_info.add_argument("--group-id", required=True)

    member_info = sub.add_parser("member-info")
    member_info.add_argument("--run-id", required=True)
    member_info.add_argument("--group-id", required=True)
    member_info.add_argument("--user-id", required=True)
    member_info.add_argument("--no-cache", action="store_true")

    member_list = sub.add_parser("member-list")
    member_list.add_argument("--run-id", required=True)
    member_list.add_argument("--group-id", required=True)

    list_prs = sub.add_parser("list-prs")
    list_prs.add_argument("--run-id", required=True)
    list_prs.add_argument("--repo")

    get_pr = sub.add_parser("get-pr")
    get_pr.add_argument("--run-id", required=True)
    get_pr.add_argument("--number", type=int, required=True)
    get_pr.add_argument("--repo")

    get_issue = sub.add_parser("get-issue")
    get_issue.add_argument("--run-id", required=True)
    get_issue.add_argument("--number", type=int, required=True)
    get_issue.add_argument("--repo")

    workflow = sub.add_parser("workflow-status")
    workflow.add_argument("--run-id", required=True)
    workflow.add_argument("--repo")
    workflow.add_argument("--workflow")
    workflow.add_argument("--branch")
    workflow.add_argument("--limit", type=int, default=5)

    args = parser.parse_args()
    path, payload = build_request(args)
    try:
        result = post(path, payload)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_request(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    command = args.command
    if command == "onebot-call":
        return (
            "/skills/onebot/call",
            {"run_id": args.run_id, "action": args.action, "params": json.loads(args.params_json)},
        )
    if command == "send-message":
        return "/skills/qq/send_message", {"run_id": args.run_id, "group_id": args.group_id, "text": args.text}
    if command == "reply-message":
        return "/skills/qq/reply_message", {"run_id": args.run_id, "message_id": args.message_id, "text": args.text}
    if command == "send-face":
        return "/skills/qq/send_face", {"run_id": args.run_id, "group_id": args.group_id, "face_id": args.face_id}
    if command == "set-group-card":
        return (
            "/skills/qq/set_group_card",
            {"run_id": args.run_id, "group_id": args.group_id, "user_id": args.user_id, "card": args.card},
        )
    if command == "set-group-ban":
        return (
            "/skills/qq/set_group_ban",
            {
                "run_id": args.run_id,
                "group_id": args.group_id,
                "user_id": args.user_id,
                "duration": args.duration,
            },
        )
    if command == "delete-msg":
        return "/skills/qq/delete_msg", {"run_id": args.run_id, "message_id": args.message_id}
    if command == "group-info":
        return "/skills/qq/get_group_info", {"run_id": args.run_id, "group_id": args.group_id}
    if command == "member-info":
        return (
            "/skills/qq/get_group_member_info",
            {
                "run_id": args.run_id,
                "group_id": args.group_id,
                "user_id": args.user_id,
                "no_cache": args.no_cache,
            },
        )
    if command == "member-list":
        return "/skills/qq/get_group_member_list", {"run_id": args.run_id, "group_id": args.group_id}
    if command == "list-prs":
        return "/skills/github/list_prs", {"run_id": args.run_id, "repo": args.repo}
    if command == "get-pr":
        return "/skills/github/get_pr", {"run_id": args.run_id, "repo": args.repo, "number": args.number}
    if command == "get-issue":
        return "/skills/github/get_issue", {"run_id": args.run_id, "repo": args.repo, "number": args.number}
    if command == "workflow-status":
        return (
            "/skills/github/get_workflow_status",
            {
                "run_id": args.run_id,
                "repo": args.repo,
                "workflow": args.workflow,
                "branch": args.branch,
                "limit": args.limit,
            },
        )
    raise ValueError(f"unknown command: {command}")


def post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    base_url = os.environ.get("QQBRIDGE_SKILL_BASE_URL", "http://127.0.0.1:8787").rstrip("/")
    token = os.environ.get("QQBRIDGE_SKILL_TOKEN", "")
    if not token:
        raise RuntimeError("QQBRIDGE_SKILL_TOKEN is not configured")

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-QQBridge-Skill-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AgentBridge API error {exc.code}: {detail[:500]}") from exc
    return json.loads(text)


if __name__ == "__main__":
    sys.exit(main())
