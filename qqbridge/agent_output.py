from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .text import is_skip_response


@dataclass(slots=True)
class AgentPlan:
    memory_note: str | None = None
    skip: bool = False

    @property
    def should_skip(self) -> bool:
        return self.skip


def parse_agent_plan(raw: str) -> AgentPlan:
    text = raw.strip()
    if not text or is_skip_response(text):
        return AgentPlan(skip=True)
    data = _decode_jsonish(text)
    if data is None:
        return AgentPlan()

    if isinstance(data, dict):
        if _truthy(data.get("skip")) or str(data.get("action", "")).upper() == "SKIP":
            return AgentPlan(memory_note=_str_or_none(data.get("memory_note")), skip=True)

    # Agent sends messages by calling tools, not by returning JSON actions.
    # Bridge only reads skip/memory_note from the response.
    return AgentPlan(memory_note=_str_or_none(data.get("memory_note")) if isinstance(data, dict) else None)


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
