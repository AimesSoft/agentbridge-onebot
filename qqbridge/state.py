from __future__ import annotations

from collections import defaultdict, deque
import hashlib
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

    def remove_unread_group_messages(self, group_id: str, message_ids: list[str | None]) -> None:
        targets = {str(message_id) for message_id in message_ids if message_id is not None}
        if not targets:
            return
        messages = self.data["ambient_unread_group_messages"].get(group_id, [])
        if not isinstance(messages, list):
            return
        self.data["ambient_unread_group_messages"][group_id] = [
            message for message in messages if str(message.get("message_id", "")) not in targets
        ]
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

    def open_group_attention(
        self,
        *,
        group_id: str,
        ttl_seconds: int,
        batch_interval_seconds: int,
        max_batches: int,
        reason: str,
        trigger_user_id: str | None = None,
        trigger_message_id: str | None = None,
    ) -> None:
        if ttl_seconds <= 0 or max_batches <= 0:
            return
        attentions = self.data.setdefault("active_group_attentions", {})
        if not isinstance(attentions, dict):
            attentions = {}
            self.data["active_group_attentions"] = attentions
        now = int(time.time())
        current = attentions.get(str(group_id))
        buffer = current.get("buffer", []) if isinstance(current, dict) and isinstance(current.get("buffer"), list) else []
        generation = int(current.get("generation", 0) or 0) + 1 if isinstance(current, dict) else 1
        next_dispatch_at = now + max(0, batch_interval_seconds)
        attentions[str(group_id)] = {
            "group_id": str(group_id),
            "trigger_user_id": str(trigger_user_id) if trigger_user_id else None,
            "trigger_message_id": str(trigger_message_id) if trigger_message_id else None,
            "expires_at": now + ttl_seconds,
            "remaining_batches": max_batches,
            "batch_interval_seconds": max(0, batch_interval_seconds),
            "next_dispatch_at": next_dispatch_at,
            "generation": generation,
            "reason": reason,
            "buffer": buffer,
            "updated_at": now,
        }
        self.save()

    def queue_group_attention_message(
        self,
        *,
        group_id: str | None,
        user_id: str,
        sender: str,
        text: str,
        message_id: str | None,
        max_buffer_messages: int,
    ) -> bool:
        if not group_id or not text.strip():
            return False
        attention = self.active_group_attention(group_id)
        if not attention:
            return False
        message = {
            "message_id": str(message_id or ""),
            "sender": sender,
            "user_id": str(user_id),
            "text": text.strip(),
            "ts": int(time.time()),
        }
        buffer = attention.setdefault("buffer", [])
        if not isinstance(buffer, list):
            buffer = []
            attention["buffer"] = buffer
        buffer.append(message)
        attention["buffer"] = buffer[-max(1, max_buffer_messages):]
        attention["updated_at"] = int(time.time())
        self.data["active_group_attentions"][str(group_id)] = attention
        self.save()
        return True

    def active_group_attention(self, group_id: str | None) -> dict[str, Any] | None:
        if not group_id:
            return None
        attentions = self.data.setdefault("active_group_attentions", {})
        if not isinstance(attentions, dict):
            self.data["active_group_attentions"] = {}
            self.save()
            return None
        attention = attentions.get(str(group_id))
        if not isinstance(attention, dict):
            return None
        now = int(time.time())
        if int(attention.get("expires_at", 0) or 0) < now or int(attention.get("remaining_batches", 0) or 0) <= 0:
            attentions.pop(str(group_id), None)
            self.save()
            return None
        return attention

    def group_attention_generation(self, group_id: str) -> int | None:
        attention = self.active_group_attention(group_id)
        if not attention:
            return None
        return int(attention.get("generation", 0) or 0)

    def close_group_attention_if_generation(self, group_id: str, generation: int | None) -> bool:
        if generation is None:
            return False
        attentions = self.data.get("active_group_attentions", {})
        if not isinstance(attentions, dict):
            return False
        attention = attentions.get(str(group_id))
        if not isinstance(attention, dict):
            return False
        if int(attention.get("generation", 0) or 0) != int(generation):
            return False
        attentions.pop(str(group_id), None)
        self.save()
        return True

    def clear_group_attention(self, group_id: str | None) -> bool:
        if not group_id:
            return False
        attentions = self.data.get("active_group_attentions", {})
        if not isinstance(attentions, dict) or str(group_id) not in attentions:
            return False
        attentions.pop(str(group_id), None)
        self.save()
        return True

    def ready_group_attention_groups(self) -> list[str]:
        attentions = self.data.get("active_group_attentions", {})
        if not isinstance(attentions, dict):
            return []
        now = int(time.time())
        ready: list[str] = []
        changed = False
        for group_id, attention in list(attentions.items()):
            if not isinstance(attention, dict):
                attentions.pop(group_id, None)
                changed = True
                continue
            if int(attention.get("expires_at", 0) or 0) < now or int(attention.get("remaining_batches", 0) or 0) <= 0:
                attentions.pop(group_id, None)
                changed = True
                continue
            buffer = attention.get("buffer", [])
            if isinstance(buffer, list) and buffer and int(attention.get("next_dispatch_at", 0) or 0) <= now:
                ready.append(str(group_id))
        if changed:
            self.save()
        return ready

    def pop_group_attention_batch(
        self,
        group_id: str,
        *,
        max_batch_messages: int,
        batch_interval_seconds: int,
    ) -> list[dict[str, Any]]:
        attention = self.active_group_attention(group_id)
        if not attention:
            return []
        buffer = attention.get("buffer", [])
        if not isinstance(buffer, list) or not buffer:
            return []
        now = int(time.time())
        if int(attention.get("next_dispatch_at", 0) or 0) > now:
            return []
        batch_size = max(1, max_batch_messages)
        batch = list(buffer[:batch_size])
        remaining = list(buffer[batch_size:])
        attention["buffer"] = remaining
        attention["remaining_batches"] = int(attention.get("remaining_batches", 0) or 0) - 1
        attention["last_dispatch_at"] = now
        if remaining and int(attention.get("remaining_batches", 0) or 0) > 0:
            attention["next_dispatch_at"] = now + max(0, batch_interval_seconds)
        else:
            attention["next_dispatch_at"] = 0
        if int(attention.get("remaining_batches", 0) or 0) <= 0:
            self.data["active_group_attentions"].pop(str(group_id), None)
        else:
            self.data["active_group_attentions"][str(group_id)] = attention
        self.save()
        return batch

    def requeue_group_attention_batch(self, group_id: str, batch: list[dict[str, Any]]) -> None:
        if not batch:
            return
        attention = self.active_group_attention(group_id)
        if not attention:
            return
        buffer = attention.get("buffer", [])
        if not isinstance(buffer, list):
            buffer = []
        attention["buffer"] = list(batch) + buffer
        attention["next_dispatch_at"] = int(time.time()) + max(1, int(attention.get("batch_interval_seconds", 1) or 1))
        attention["remaining_batches"] = int(attention.get("remaining_batches", 0) or 0) + 1
        self.data["active_group_attentions"][str(group_id)] = attention
        self.save()


    def runtime_setting(self, key: str, default: str | None = None) -> str | None:
        settings = self.data.get("runtime_settings", {})
        if not isinstance(settings, dict):
            return default
        value = settings.get(key)
        return str(value) if value is not None else default

    def set_runtime_setting(self, key: str, value: str | None) -> None:
        settings = self.data.setdefault("runtime_settings", {})
        if not isinstance(settings, dict):
            settings = {}
            self.data["runtime_settings"] = settings
        if value is None:
            settings.pop(key, None)
        else:
            settings[key] = value
        self.save()

    def hermes_session_id(self, conversation_key: str) -> str:
        generations = self.data.setdefault("hermes_session_generations", {})
        if not isinstance(generations, dict):
            generations = {}
            self.data["hermes_session_generations"] = generations
        generation = int(generations.get(conversation_key, 0) or 0)
        digest = hashlib.sha256(f"{conversation_key}:{generation}".encode("utf-8")).hexdigest()[:24]
        return f"qqbridge-{digest}"

    def reset_hermes_session(self, conversation_key: str) -> str:
        generations = self.data.setdefault("hermes_session_generations", {})
        if not isinstance(generations, dict):
            generations = {}
            self.data["hermes_session_generations"] = generations
        generations[conversation_key] = int(generations.get(conversation_key, 0) or 0) + 1
        self.save()
        return self.hermes_session_id(conversation_key)

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
            "runtime_settings": {},
            "hermes_session_generations": {},
            "active_group_attentions": {},
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
