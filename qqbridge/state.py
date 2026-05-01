from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
import json
import time
from typing import Any
from uuid import uuid4

from .settings import GroupConfig


class BridgeState:
    def __init__(self, path: Path, max_history_messages: int) -> None:
        self.path = path
        self.max_history_messages = max_history_messages
        self._dedup: dict[str, float] = {}
        self._rate: dict[str, deque[float]] = defaultdict(deque)
        self.data = self._load()

    def seen_event(self, key: str, ttl_seconds: int = 600) -> bool:
        now = time.time()
        expired = [item for item, ts in self._dedup.items() if now - ts > ttl_seconds]
        for item in expired:
            self._dedup.pop(item, None)
        if key in self._dedup:
            return True
        self._dedup[key] = now
        return False

    def allow_user_llm(self, user_id: str, limit_per_minute: int) -> bool:
        if limit_per_minute <= 0:
            return True
        now = time.time()
        window = self._rate[user_id]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= limit_per_minute:
            return False
        window.append(now)
        return True

    def history(self, key: str) -> list[dict[str, str]]:
        raw = self.data["conversations"].get(key, [])
        return [item for item in raw if item.get("role") in {"user", "assistant"} and isinstance(item.get("content"), str)]

    def append_conversation(self, key: str, user_content: str, assistant_content: str) -> None:
        history = self.history(key)
        history.extend(
            [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": assistant_content},
            ]
        )
        self.data["conversations"][key] = history[-self.max_history_messages :]
        self.save()

    def clear_conversation(self, key: str) -> None:
        self.data["conversations"].pop(key, None)
        self.save()

    def append_group_message(
        self,
        group_id: str,
        sender: str,
        user_id: str,
        text: str,
        message_id: str | None = None,
        max_items: int = 40,
    ) -> None:
        if not text.strip():
            return
        message = {
            "message_id": str(message_id or ""),
            "sender": sender,
            "user_id": user_id,
            "text": text.strip(),
            "ts": int(time.time()),
        }
        messages = self.data["recent_group_messages"].setdefault(group_id, [])
        messages.append(message)
        self.data["recent_group_messages"][group_id] = messages[-max_items:]
        unread = self.data["ambient_unread_group_messages"].setdefault(group_id, [])
        unread.append(message)
        self.data["ambient_unread_group_messages"][group_id] = unread[-max_items:]
        self.save()

    def recent_group_context(self, group_id: str, limit: int) -> list[dict[str, Any]]:
        messages = self.data["recent_group_messages"].get(group_id, [])
        return list(messages[-limit:])

    def find_message(self, message_id: str) -> dict[str, Any] | None:
        target = str(message_id)
        for group_id, messages in self.data["recent_group_messages"].items():
            for message in reversed(messages):
                if str(message.get("message_id", "")) == target:
                    found = dict(message)
                    found.setdefault("group_id", str(group_id))
                    return found
        for group_id, messages in self.data["ambient_unread_group_messages"].items():
            for message in reversed(messages):
                if str(message.get("message_id", "")) == target:
                    found = dict(message)
                    found.setdefault("group_id", str(group_id))
                    return found
        return None

    def ambient_groups_with_unread(self, min_messages: int) -> list[str]:
        groups: list[str] = []
        for group_id, messages in self.data["ambient_unread_group_messages"].items():
            if len(messages) >= min_messages:
                groups.append(str(group_id))
        return groups

    def unread_group_messages(self, group_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        messages = list(self.data["ambient_unread_group_messages"].get(group_id, []))
        if limit is not None:
            return messages[-limit:]
        return messages

    def clear_unread_group_messages(self, group_id: str) -> None:
        self.data["ambient_unread_group_messages"][group_id] = []
        self.save()

    def add_bot_message_id(self, group_id: str | None, message_id: str) -> None:
        if not group_id or not message_id:
            return
        ids = self.data["last_bot_message_ids"].setdefault(group_id, [])
        ids.append(str(message_id))
        self.data["last_bot_message_ids"][group_id] = ids[-80:]
        self.save()

    def is_reply_to_bot(self, group_id: str | None, reply_id: str) -> bool:
        if not group_id or not reply_id:
            return False
        return str(reply_id) in set(self.data["last_bot_message_ids"].get(group_id, []))

    def group_override(self, group_id: str) -> dict[str, Any]:
        return dict(self.data["group_overrides"].get(group_id, {}))

    def set_group_override(self, group_id: str, updates: dict[str, Any]) -> None:
        current = self.group_override(group_id)
        current.update(updates)
        self.data["group_overrides"][group_id] = current
        self.save()

    def effective_group_config(self, group_id: str | None, base: GroupConfig) -> GroupConfig:
        if not group_id:
            return base
        override = self.group_override(group_id)
        return GroupConfig(
            autonomous_enabled=bool(override.get("autonomous_enabled", base.autonomous_enabled)),
            min_seconds_between_replies=int(
                override.get("min_seconds_between_replies", base.min_seconds_between_replies)
            ),
            keywords=list(override.get("keywords", base.keywords)),
        )

    def can_group_autoreply_now(self, group_id: str, cooldown_seconds: int) -> bool:
        if cooldown_seconds <= 0:
            return True
        last = float(self.data["group_reply_times"].get(group_id, 0))
        return time.time() - last >= cooldown_seconds

    def mark_group_replied(self, group_id: str) -> None:
        self.data["group_reply_times"][group_id] = time.time()
        self.save()

    def create_agent_run(
        self,
        *,
        mode: str,
        allowed_tools: list[str],
        ttl_seconds: int,
        group_id: str | None = None,
        user_id: str | None = None,
        trigger_message_id: str | None = None,
        allowed_repos: list[str] | None = None,
        max_tool_calls: int = 20,
    ) -> dict[str, Any]:
        self.prune_agent_runs()
        run_id = uuid4().hex
        now = int(time.time())
        run = {
            "run_id": run_id,
            "mode": mode,
            "group_id": str(group_id) if group_id else None,
            "user_id": str(user_id) if user_id else None,
            "trigger_message_id": str(trigger_message_id) if trigger_message_id else None,
            "allowed_tools": list(dict.fromkeys(allowed_tools)),
            "allowed_repos": list(dict.fromkeys(allowed_repos or [])),
            "expires_at": now + max(30, ttl_seconds),
            "created_at": now,
            "max_tool_calls": max_tool_calls,
            "tool_calls": 0,
        }
        self.data["agent_runs"][run_id] = run
        self.save()
        return dict(run)

    def get_agent_run(self, run_id: str) -> dict[str, Any] | None:
        self.prune_agent_runs()
        run = self.data["agent_runs"].get(str(run_id))
        return dict(run) if isinstance(run, dict) else None

    def authorize_agent_tool(
        self,
        *,
        run_id: str,
        tool: str,
        group_id: str | None = None,
        repo: str | None = None,
    ) -> dict[str, Any]:
        run = self.get_agent_run(run_id)
        if not run:
            raise PermissionError("agent run is missing or expired")
        if tool not in set(run.get("allowed_tools", [])):
            raise PermissionError(f"tool is not allowed for this run: {tool}")
        if group_id and run.get("group_id") and str(group_id) != str(run["group_id"]):
            raise PermissionError("group target is not allowed for this run")
        allowed_repos = set(run.get("allowed_repos") or [])
        if repo and allowed_repos and repo not in allowed_repos:
            raise PermissionError("repo target is not allowed for this run")
        if int(run.get("tool_calls", 0)) >= int(run.get("max_tool_calls", 20)):
            raise PermissionError("agent run tool call limit exceeded")
        self.data["agent_runs"][run_id]["tool_calls"] = int(run.get("tool_calls", 0)) + 1
        self.save()
        return run

    def prune_agent_runs(self) -> None:
        now = int(time.time())
        runs = self.data.get("agent_runs", {})
        if not isinstance(runs, dict):
            self.data["agent_runs"] = {}
            self.save()
            return
        expired = [run_id for run_id, run in runs.items() if not isinstance(run, dict) or int(run.get("expires_at", 0)) < now]
        if not expired:
            return
        for run_id in expired:
            runs.pop(run_id, None)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=False, indent=2)

    def _load(self) -> dict[str, Any]:
        default = {
            "conversations": {},
            "recent_group_messages": {},
            "ambient_unread_group_messages": {},
            "last_bot_message_ids": {},
            "group_overrides": {},
            "group_reply_times": {},
            "agent_runs": {},
        }
        if not self.path.exists():
            return default
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return default
        if not isinstance(loaded, dict):
            return default
        return {**default, **loaded}
