from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL DEFAULT 'Чат',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  meta TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if not self._conn:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def get_setting(self, key: str, default: Any = None) -> Any:
        cur = await self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        if not row:
            return default
        return json.loads(row["value"])

    async def set_setting(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        await self.conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, payload),
        )
        await self.conn.commit()

    async def ensure_conversation(self, conversation_id: int | None = None) -> int:
        if conversation_id is not None:
            cur = await self.conn.execute(
                "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
            )
            row = await cur.fetchone()
            if row:
                return int(row["id"])
        cur = await self.conn.execute(
            "INSERT INTO conversations(title) VALUES (?)", ("Чат",)
        )
        await self.conn.commit()
        return int(cur.lastrowid)

    async def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        meta: dict[str, Any] | None = None,
    ) -> int:
        cur = await self.conn.execute(
            "INSERT INTO messages(conversation_id, role, content, meta) VALUES (?, ?, ?, ?)",
            (
                conversation_id,
                role,
                content,
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        await self.conn.execute(
            "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
            (conversation_id,),
        )
        await self.conn.commit()
        return int(cur.lastrowid)

    async def list_messages(self, conversation_id: int) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT id, role, content, meta, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        )
        rows = await cur.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "id": row["id"],
                    "role": row["role"],
                    "content": row["content"],
                    "meta": json.loads(row["meta"] or "{}"),
                    "created_at": row["created_at"],
                }
            )
        return result

    async def list_conversations(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations "
            "ORDER BY updated_at DESC"
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]
