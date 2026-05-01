from __future__ import annotations

import re


def split_qq_message(text: str, max_chars: int) -> list[str]:
    clean = text.strip()
    if not clean:
        return []
    if max_chars <= 0 or len(clean) <= max_chars:
        return [clean]

    chunks: list[str] = []
    current = ""
    for part in re.split(r"(\n+)", clean):
        if not part:
            continue
        if len(part) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(_hard_wrap(part, max_chars))
            continue
        if len(current) + len(part) > max_chars:
            chunks.append(current.strip())
            current = part
        else:
            current += part
    if current.strip():
        chunks.append(current.strip())
    return chunks


def is_skip_response(text: str) -> bool:
    normalized = re.sub(r"[\s。.!！?？~～]+", "", text).upper()
    return normalized in {"SKIP", "不回复", "跳过", "算了"}


def _hard_wrap(text: str, max_chars: int) -> list[str]:
    return [text[index : index + max_chars].strip() for index in range(0, len(text), max_chars) if text[index : index + max_chars].strip()]

