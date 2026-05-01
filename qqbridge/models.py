from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


CQ_RE = re.compile(r"\[CQ:(?P<type>[a-zA-Z0-9_]+)(?P<params>(?:,[^\]]*)?)\]")


@dataclass(slots=True)
class MessageSegment:
    type: str
    data: dict[str, str]


@dataclass(slots=True)
class InboundMessage:
    event: dict[str, Any]
    self_id: str
    message_type: str
    user_id: str
    group_id: str | None
    message_id: str
    plain_text: str
    raw_message: str
    segments: list[MessageSegment]
    sender_name: str

    @property
    def is_group(self) -> bool:
        return self.message_type == "group"

    @property
    def is_private(self) -> bool:
        return self.message_type == "private"

    @property
    def conversation_key(self) -> str:
        if self.group_id:
            return f"group:{self.group_id}:user:{self.user_id}"
        return f"private:{self.user_id}"

    @property
    def dedup_key(self) -> str:
        return f"{self.self_id}:{self.message_type}:{self.group_id or '-'}:{self.message_id}"


def parse_inbound_message(event: dict[str, Any]) -> InboundMessage | None:
    if event.get("post_type") != "message":
        return None
    message_type = str(event.get("message_type") or "")
    if message_type not in {"private", "group"}:
        return None

    self_id = normalize_id(event.get("self_id"))
    user_id = normalize_id(event.get("user_id"))
    group_id = normalize_id(event.get("group_id")) if message_type == "group" else None
    message_id = normalize_id(event.get("message_id"))
    raw_message = str(event.get("raw_message") or "")
    segments = coerce_segments(event.get("message", raw_message))
    plain_text = extract_plain_text(segments, raw_message)
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    sender_name = str(sender.get("card") or sender.get("nickname") or user_id)

    if not self_id or not user_id or not message_id:
        return None

    return InboundMessage(
        event=event,
        self_id=self_id,
        message_type=message_type,
        user_id=user_id,
        group_id=group_id,
        message_id=message_id,
        plain_text=plain_text.strip(),
        raw_message=raw_message,
        segments=segments,
        sender_name=sender_name,
    )


def normalize_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def coerce_segments(message: Any) -> list[MessageSegment]:
    if isinstance(message, list):
        segments: list[MessageSegment] = []
        for item in message:
            if not isinstance(item, dict):
                continue
            segment_type = str(item.get("type") or "")
            data = item.get("data") if isinstance(item.get("data"), dict) else {}
            segments.append(MessageSegment(type=segment_type, data={str(k): str(v) for k, v in data.items()}))
        return segments
    return parse_cq_string(str(message or ""))


def parse_cq_string(message: str) -> list[MessageSegment]:
    segments: list[MessageSegment] = []
    index = 0
    for match in CQ_RE.finditer(message):
        if match.start() > index:
            segments.append(MessageSegment(type="text", data={"text": message[index : match.start()]}))
        params = _parse_cq_params(match.group("params"))
        segments.append(MessageSegment(type=match.group("type"), data=params))
        index = match.end()
    if index < len(message):
        segments.append(MessageSegment(type="text", data={"text": message[index:]}))
    return segments


def extract_plain_text(segments: list[MessageSegment], fallback: str = "") -> str:
    texts: list[str] = []
    for segment in segments:
        if segment.type == "text":
            texts.append(segment.data.get("text", ""))
        elif segment.type == "image":
            texts.append("[图片]")
        elif segment.type == "record":
            texts.append("[语音]")
        elif segment.type == "video":
            texts.append("[视频]")
    text = "".join(texts).strip()
    if text:
        return text
    return CQ_RE.sub("", fallback).strip()


def at_targets(segments: list[MessageSegment]) -> list[str]:
    return [segment.data.get("qq", "") for segment in segments if segment.type == "at" and segment.data.get("qq")]


def reply_ids(segments: list[MessageSegment]) -> list[str]:
    return [segment.data.get("id", "") for segment in segments if segment.type == "reply" and segment.data.get("id")]


def mentions_bot(message: InboundMessage, configured_bot_id: str | None, bot_names: list[str]) -> bool:
    bot_id = configured_bot_id or message.self_id
    targets = {target.strip() for target in at_targets(message.segments)}
    if bot_id and bot_id in targets:
        return True
    lowered = message.plain_text.lower()
    return any(name.lower() in lowered for name in bot_names if name)


def keyword_hit(text: str, keywords: list[str]) -> str | None:
    lowered = text.lower()
    for keyword in keywords:
        if keyword and keyword.lower() in lowered:
            return keyword
    return None


def _parse_cq_params(raw_params: str) -> dict[str, str]:
    params: dict[str, str] = {}
    if not raw_params:
        return params
    for part in raw_params.lstrip(",").split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        params[key] = value
    return params

