from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any


@dataclass(slots=True)
class OutboundAction:
    type: str
    text: str = ""
    reply_to: str | None = None
    face_id: str | None = None
    private: bool = False


@dataclass(slots=True)
class AgentPlan:
    actions: list[OutboundAction] = field(default_factory=list)
    memory_note: str | None = None

    @property
    def should_skip(self) -> bool:
        return not self.actions


def parse_agent_plan(raw: str) -> AgentPlan:
    text = raw.strip()
    if not text:
        return AgentPlan()
    data = _decode_jsonish(text)
    if data is None:
        return AgentPlan(actions=[OutboundAction(type="send", text=text)])

    if isinstance(data, list):
        raw_actions = data
        memory_note = None
    elif isinstance(data, dict):
        if _truthy(data.get("skip")) or str(data.get("action", "")).upper() == "SKIP":
            return AgentPlan(memory_note=_str_or_none(data.get("memory_note")))
        raw_actions = data.get("actions")
        if raw_actions is None and (data.get("text") or data.get("message")):
            raw_actions = [data]
        memory_note = _str_or_none(data.get("memory_note"))
    else:
        return AgentPlan(actions=[OutboundAction(type="send", text=text)])

    if not isinstance(raw_actions, list):
        return AgentPlan(memory_note=memory_note)

    actions: list[OutboundAction] = []
    for item in raw_actions:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or item.get("action") or "send").lower()
        if action_type in {"skip", "none"}:
            continue
        if action_type in {"react", "face", "emoji"}:
            face_id = _str_or_none(item.get("face_id") or item.get("id") or item.get("qq_face_id"))
            if face_id:
                actions.append(OutboundAction(type="face", face_id=face_id, reply_to=_str_or_none(item.get("reply_to"))))
            continue
        if action_type not in {"send", "message", "reply"}:
            continue
        content = _str_or_none(item.get("text") or item.get("message") or item.get("content"))
        if content:
            actions.append(
                OutboundAction(
                    type="send",
                    text=content,
                    reply_to=_str_or_none(item.get("reply_to") or item.get("reply_to_message_id")),
                    private=_truthy(item.get("private")),
                )
            )

    return AgentPlan(actions=actions, memory_note=memory_note)


def _decode_jsonish(text: str) -> Any:
    candidates = [text]
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            stripped = part.strip()
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
            if stripped.startswith("{") or stripped.startswith("["):
                candidates.append(stripped)
    for candidate in candidates:
        candidate = candidate.strip()
        if not (candidate.startswith("{") or candidate.startswith("[")):
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

