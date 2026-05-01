from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import sqlite3
import time
from typing import Any


class MessageStore:
    def __init__(self, path: Path, archive_dir: Path | None = None) -> None:
        self.path = path
        self.archive_dir = archive_dir
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.archive_dir:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def add_message(
        self,
        *,
        message_id: str,
        message_type: str,
        user_id: str,
        sender_name: str,
        plain_text: str,
        raw_message: str,
        segments: list[dict[str, Any]],
        group_id: str | None = None,
        self_id: str | None = None,
        reply_to: str | None = None,
        at_bot: bool = False,
        is_from_bot: bool = False,
        event: dict[str, Any] | None = None,
        timestamp: int | None = None,
    ) -> None:
        ts = int(timestamp or time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO messages (
                  message_id, message_type, group_id, user_id, self_id, sender_name,
                  plain_text, raw_message, segments_json, reply_to, at_bot, is_from_bot,
                  event_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(message_id),
                    message_type,
                    str(group_id) if group_id else None,
                    str(user_id),
                    str(self_id) if self_id else None,
                    sender_name,
                    plain_text,
                    raw_message,
                    json.dumps(segments, ensure_ascii=False),
                    str(reply_to) if reply_to else None,
                    1 if at_bot else 0,
                    1 if is_from_bot else 0,
                    json.dumps(event or {}, ensure_ascii=False),
                    ts,
                ),
            )
        self._append_archive(
            {
                "message_id": str(message_id),
                "message_type": message_type,
                "group_id": str(group_id) if group_id else None,
                "user_id": str(user_id),
                "self_id": str(self_id) if self_id else None,
                "sender_name": sender_name,
                "plain_text": plain_text,
                "raw_message": raw_message,
                "segments": segments,
                "reply_to": str(reply_to) if reply_to else None,
                "at_bot": at_bot,
                "is_from_bot": is_from_bot,
                "event": event or {},
                "timestamp": ts,
            }
        )

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM messages WHERE message_id = ?", (str(message_id),)).fetchone()
        return _row_to_message(row)

    def recent_group_messages(self, group_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE group_id = ?
                ORDER BY timestamp DESC, rowid DESC
                LIMIT ?
                """,
                (str(group_id), limit),
            ).fetchall()
        return list(reversed([message for row in rows if (message := _row_to_message(row))]))

    def recent_private_messages(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE message_type = 'private' AND user_id = ?
                ORDER BY timestamp DESC, rowid DESC
                LIMIT ?
                """,
                (str(user_id), limit),
            ).fetchall()
        return list(reversed([message for row in rows if (message := _row_to_message(row))]))

    def archive_paths(self, group_id: str | None = None, user_id: str | None = None) -> dict[str, Any]:
        if not self.archive_dir:
            return {"archive_dir": None, "paths": []}
        paths: list[str] = []
        if group_id:
            paths.extend(str(path.resolve()) for path in sorted((self.archive_dir / "groups" / str(group_id)).glob("*.jsonl")))
        elif user_id:
            paths.extend(str(path.resolve()) for path in sorted((self.archive_dir / "private" / str(user_id)).glob("*.jsonl")))
        else:
            paths.extend(str(path.resolve()) for path in sorted(self.archive_dir.glob("**/*.jsonl")))
        return {"archive_dir": str(self.archive_dir.resolve()), "paths": paths}

    def search_messages(
        self,
        *,
        query: str,
        group_id: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        conditions = ["plain_text LIKE ?"]
        params: list[Any] = [pattern]
        if group_id:
            conditions.append("group_id = ?")
            params.append(str(group_id))
        if user_id:
            conditions.append("user_id = ?")
            params.append(str(user_id))
        params.append(limit)
        sql = f"""
            SELECT * FROM messages
            WHERE {' AND '.join(conditions)}
            ORDER BY timestamp DESC, rowid DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_message(row) for row in rows if _row_to_message(row)]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  message_id TEXT UNIQUE NOT NULL,
                  message_type TEXT NOT NULL,
                  group_id TEXT,
                  user_id TEXT NOT NULL,
                  self_id TEXT,
                  sender_name TEXT,
                  plain_text TEXT,
                  raw_message TEXT,
                  segments_json TEXT,
                  reply_to TEXT,
                  at_bot INTEGER NOT NULL DEFAULT 0,
                  is_from_bot INTEGER NOT NULL DEFAULT 0,
                  event_json TEXT,
                  timestamp INTEGER NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_group_ts ON messages(group_id, timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_user_ts ON messages(user_id, timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_text ON messages(plain_text)")

    def _append_archive(self, message: dict[str, Any]) -> None:
        if not self.archive_dir:
            return
        ts = int(message["timestamp"])
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        if message.get("group_id"):
            path = self.archive_dir / "groups" / str(message["group_id"]) / f"{day}.jsonl"
        else:
            path = self.archive_dir / "private" / str(message["user_id"]) / f"{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message, ensure_ascii=False) + "\n")


def _row_to_message(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data.pop("id", None)
    data["segments"] = _json_loads(data.pop("segments_json", "[]"), [])
    data["event"] = _json_loads(data.pop("event_json", "{}"), {})
    data["at_bot"] = bool(data.get("at_bot"))
    data["is_from_bot"] = bool(data.get("is_from_bot"))
    return data


def _json_loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default
