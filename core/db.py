from __future__ import annotations

import json
from datetime import datetime, timezone
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

CREATE TABLE IF NOT EXISTS quality_orders (
  order_id TEXT PRIMARY KEY,
  status TEXT,
  engineer TEXT,
  accepter TEXT,
  manager TEXT,
  device TEXT,
  client TEXT,
  location TEXT,
  accepted_at TEXT,
  repair_cost REAL,
  list_fingerprint TEXT,
  feed_json TEXT,
  metrics_json TEXT,
  list_synced_at TEXT,
  feed_synced_at TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS quality_sync_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  status TEXT NOT NULL DEFAULT 'idle',
  total INTEGER NOT NULL DEFAULT 0,
  done INTEGER NOT NULL DEFAULT 0,
  queued INTEGER NOT NULL DEFAULT 0,
  message TEXT,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS quality_daily_stats (
  day TEXT PRIMARY KEY,
  orders_count INTEGER NOT NULL DEFAULT 0,
  avg_total_days REAL,
  avg_wait_master_days REAL,
  avg_diag_days REAL,
  avg_rework_kpi REAL,
  avg_calls_kpi REAL,
  avg_order_kpi REAL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS quality_analysis (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  analysis_json TEXT NOT NULL,
  generated_at TEXT NOT NULL
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

    async def quality_upsert_order(self, row: dict[str, Any]) -> None:
        await self.conn.execute(
            """
            INSERT INTO quality_orders(
              order_id, status, engineer, accepter, manager, device, client,
              location, accepted_at, repair_cost, list_fingerprint, feed_json,
              metrics_json, list_synced_at, feed_synced_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(order_id) DO UPDATE SET
              status = excluded.status,
              engineer = excluded.engineer,
              accepter = excluded.accepter,
              manager = excluded.manager,
              device = excluded.device,
              client = excluded.client,
              location = excluded.location,
              accepted_at = COALESCE(excluded.accepted_at, quality_orders.accepted_at),
              repair_cost = COALESCE(excluded.repair_cost, quality_orders.repair_cost),
              list_fingerprint = excluded.list_fingerprint,
              feed_json = COALESCE(excluded.feed_json, quality_orders.feed_json),
              metrics_json = COALESCE(excluded.metrics_json, quality_orders.metrics_json),
              list_synced_at = COALESCE(excluded.list_synced_at, quality_orders.list_synced_at),
              feed_synced_at = COALESCE(excluded.feed_synced_at, quality_orders.feed_synced_at),
              updated_at = datetime('now')
            """,
            (
                row["order_id"],
                row.get("status"),
                row.get("engineer"),
                row.get("accepter"),
                row.get("manager"),
                row.get("device"),
                row.get("client"),
                row.get("location"),
                row.get("accepted_at"),
                row.get("repair_cost"),
                row.get("list_fingerprint"),
                row.get("feed_json"),
                row.get("metrics_json"),
                row.get("list_synced_at"),
                row.get("feed_synced_at"),
            ),
        )
        await self.conn.commit()

    async def quality_get_order(self, order_id: str) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            "SELECT * FROM quality_orders WHERE order_id = ?", (str(order_id),)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def quality_list_orders(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT * FROM quality_orders ORDER BY accepted_at DESC, order_id DESC"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def quality_delete_missing(self, keep_ids: set[str]) -> int:
        cur = await self.conn.execute("SELECT order_id FROM quality_orders")
        existing = {str(r["order_id"]) for r in await cur.fetchall()}
        drop = existing - keep_ids
        for oid in drop:
            await self.conn.execute(
                "DELETE FROM quality_orders WHERE order_id = ?", (oid,)
            )
        if drop:
            await self.conn.commit()
        return len(drop)

    async def quality_get_sync_state(self) -> dict[str, Any]:
        cur = await self.conn.execute(
            "SELECT * FROM quality_sync_state WHERE id = 1"
        )
        row = await cur.fetchone()
        if not row:
            await self.conn.execute(
                "INSERT INTO quality_sync_state(id, status) VALUES (1, 'idle')"
            )
            await self.conn.commit()
            return {
                "status": "idle",
                "total": 0,
                "done": 0,
                "queued": 0,
                "message": None,
                "started_at": None,
                "finished_at": None,
            }
        return dict(row)

    async def quality_set_sync_state(self, **fields: Any) -> dict[str, Any]:
        current = await self.quality_get_sync_state()
        current.update({k: v for k, v in fields.items() if v is not None or k in fields})
        await self.conn.execute(
            """
            INSERT INTO quality_sync_state(
              id, status, total, done, queued, message, started_at, finished_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              status = excluded.status,
              total = excluded.total,
              done = excluded.done,
              queued = excluded.queued,
              message = excluded.message,
              started_at = excluded.started_at,
              finished_at = excluded.finished_at
            """,
            (
                current.get("status") or "idle",
                int(current.get("total") or 0),
                int(current.get("done") or 0),
                int(current.get("queued") or 0),
                current.get("message"),
                current.get("started_at"),
                current.get("finished_at"),
            ),
        )
        await self.conn.commit()
        return await self.quality_get_sync_state()

    async def quality_upsert_daily_stats(self, row: dict[str, Any]) -> None:
        await self.conn.execute(
            """
            INSERT INTO quality_daily_stats(
              day, orders_count, avg_total_days, avg_wait_master_days, avg_diag_days,
              avg_rework_kpi, avg_calls_kpi, avg_order_kpi, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(day) DO UPDATE SET
              orders_count = excluded.orders_count,
              avg_total_days = excluded.avg_total_days,
              avg_wait_master_days = excluded.avg_wait_master_days,
              avg_diag_days = excluded.avg_diag_days,
              avg_rework_kpi = excluded.avg_rework_kpi,
              avg_calls_kpi = excluded.avg_calls_kpi,
              avg_order_kpi = excluded.avg_order_kpi,
              updated_at = excluded.updated_at
            """,
            (
                row["day"],
                int(row.get("orders_count") or 0),
                row.get("avg_total_days"),
                row.get("avg_wait_master_days"),
                row.get("avg_diag_days"),
                row.get("avg_rework_kpi"),
                row.get("avg_calls_kpi"),
                row.get("avg_order_kpi"),
                row.get("updated_at"),
            ),
        )
        await self.conn.commit()

    async def quality_list_daily_stats(self, *, limit: int = 365) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT * FROM (
              SELECT * FROM quality_daily_stats
              ORDER BY day DESC
              LIMIT ?
            ) AS recent
            ORDER BY day ASC
            """,
            (max(1, int(limit)),),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def quality_save_analysis(self, analysis: dict[str, Any]) -> None:
        generated_at = analysis.get("generated_at") or datetime.now(timezone.utc).isoformat()
        await self.conn.execute(
            """
            INSERT INTO quality_analysis(id, analysis_json, generated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              analysis_json = excluded.analysis_json,
              generated_at = excluded.generated_at
            """,
            (json.dumps(analysis, ensure_ascii=False), generated_at),
        )
        await self.conn.commit()

    async def quality_get_analysis(self) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            "SELECT analysis_json, generated_at FROM quality_analysis WHERE id = 1"
        )
        row = await cur.fetchone()
        if not row:
            return None
        try:
            data = json.loads(row["analysis_json"] or "{}")
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            data.setdefault("generated_at", row["generated_at"])
            return data
        return None
