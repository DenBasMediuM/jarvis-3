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

CREATE TABLE IF NOT EXISTS vyrobotka_rows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  spreadsheet_id TEXT NOT NULL,
  sheet_title TEXT NOT NULL,
  row_index INTEGER NOT NULL,
  master TEXT,
  ticket TEXT NOT NULL,
  report_amount REAL,
  salary REAL,
  parts REAL,
  total_repair REAL,
  paid REAL,
  upsell REAL,
  remainder REAL,
  arith_check TEXT,
  status TEXT,
  control TEXT,
  upsell_floor REAL,
  upsell_floor_label TEXT,
  comments TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(spreadsheet_id, sheet_title, row_index)
);

CREATE TABLE IF NOT EXISTS vyrobotka_sheet_stats (
  spreadsheet_id TEXT NOT NULL,
  sheet_title TEXT NOT NULL,
  sort_ym INTEGER NOT NULL DEFAULT 0,
  sort_a INTEGER NOT NULL DEFAULT 0,
  sort_b INTEGER NOT NULL DEFAULT 0,
  tickets_count INTEGER NOT NULL DEFAULT 0,
  report_sum REAL NOT NULL DEFAULT 0,
  upsell_sum REAL NOT NULL DEFAULT 0,
  upsell_count INTEGER NOT NULL DEFAULT 0,
  avg_upsell REAL,
  upsell_ratio REAL,
  spreadsheet_title TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (spreadsheet_id, sheet_title)
);

CREATE TABLE IF NOT EXISTS vyrobotka_sync_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  status TEXT NOT NULL DEFAULT 'idle',
  total INTEGER NOT NULL DEFAULT 0,
  done INTEGER NOT NULL DEFAULT 0,
  message TEXT,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS vyrobotka_debt_verify_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  status TEXT NOT NULL DEFAULT 'idle',
  total INTEGER NOT NULL DEFAULT 0,
  done INTEGER NOT NULL DEFAULT 0,
  message TEXT,
  report_json TEXT,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS vyrobotka_debt_verify_rows (
  sheet_title TEXT NOT NULL,
  ticket TEXT NOT NULL,
  verdict TEXT NOT NULL,
  summary TEXT,
  issues_json TEXT,
  sheet_total REAL,
  sheet_paid REAL,
  sheet_debt REAL,
  sheet_status TEXT,
  crm_total REAL,
  crm_paid REAL,
  crm_debt REAL,
  crm_status TEXT,
  crm_url TEXT,
  master TEXT,
  checked_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (sheet_title, ticket)
);

CREATE TABLE IF NOT EXISTS vyrobotka_debt_daily (
  day TEXT PRIMARY KEY,
  crm_debt_sum REAL,
  sheets_debt_sum REAL,
  crm_orders INTEGER,
  sheets_tickets INTEGER,
  source TEXT,
  updated_at TEXT NOT NULL
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

    async def vyrobotka_get_sync_state(self) -> dict[str, Any]:
        cur = await self.conn.execute(
            "SELECT * FROM vyrobotka_sync_state WHERE id = 1"
        )
        row = await cur.fetchone()
        if not row:
            await self.conn.execute(
                "INSERT INTO vyrobotka_sync_state(id, status) VALUES (1, 'idle')"
            )
            await self.conn.commit()
            return {
                "status": "idle",
                "total": 0,
                "done": 0,
                "message": None,
                "started_at": None,
                "finished_at": None,
            }
        return dict(row)

    async def vyrobotka_set_sync_state(self, **fields: Any) -> dict[str, Any]:
        current = await self.vyrobotka_get_sync_state()
        current.update(fields)
        await self.conn.execute(
            """
            INSERT INTO vyrobotka_sync_state(
              id, status, total, done, message, started_at, finished_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              status = excluded.status,
              total = excluded.total,
              done = excluded.done,
              message = excluded.message,
              started_at = excluded.started_at,
              finished_at = excluded.finished_at
            """,
            (
                current.get("status") or "idle",
                int(current.get("total") or 0),
                int(current.get("done") or 0),
                current.get("message"),
                current.get("started_at"),
                current.get("finished_at"),
            ),
        )
        await self.conn.commit()
        return await self.vyrobotka_get_sync_state()

    async def vyrobotka_replace_all(
        self,
        rows: list[dict[str, Any]],
        sheet_stats: list[dict[str, Any]],
    ) -> None:
        await self.conn.execute("DELETE FROM vyrobotka_rows")
        await self.conn.execute("DELETE FROM vyrobotka_sheet_stats")
        for r in rows:
            await self.conn.execute(
                """
                INSERT INTO vyrobotka_rows(
                  spreadsheet_id, sheet_title, row_index, master, ticket,
                  report_amount, salary, parts, total_repair, paid, upsell,
                  remainder, arith_check, status, control, upsell_floor,
                  upsell_floor_label, comments, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    r.get("spreadsheet_id"),
                    r.get("sheet_title"),
                    int(r.get("row_index") or 0),
                    r.get("master"),
                    r.get("ticket"),
                    r.get("report_amount"),
                    r.get("salary"),
                    r.get("parts"),
                    r.get("total_repair"),
                    r.get("paid"),
                    r.get("upsell"),
                    r.get("remainder"),
                    r.get("arith_check"),
                    r.get("status"),
                    r.get("control"),
                    r.get("upsell_floor"),
                    r.get("upsell_floor_label"),
                    r.get("comments"),
                ),
            )
        for s in sheet_stats:
            await self.conn.execute(
                """
                INSERT INTO vyrobotka_sheet_stats(
                  spreadsheet_id, sheet_title, sort_ym, sort_a, sort_b,
                  tickets_count, report_sum, upsell_sum, upsell_count,
                  avg_upsell, upsell_ratio, spreadsheet_title, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    s.get("spreadsheet_id"),
                    s.get("sheet_title"),
                    int(s.get("sort_ym") or 0),
                    int(s.get("sort_a") or 0),
                    int(s.get("sort_b") or 0),
                    int(s.get("tickets_count") or 0),
                    float(s.get("report_sum") or 0),
                    float(s.get("upsell_sum") or 0),
                    int(s.get("upsell_count") or 0),
                    s.get("avg_upsell"),
                    s.get("upsell_ratio"),
                    s.get("spreadsheet_title"),
                ),
            )
        await self.conn.commit()

    async def vyrobotka_list_sheet_stats(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT * FROM vyrobotka_sheet_stats
            ORDER BY sort_ym ASC, sort_a ASC, sort_b ASC, sheet_title ASC
            """
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def vyrobotka_list_rows(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT r.*
            FROM vyrobotka_rows r
            LEFT JOIN vyrobotka_sheet_stats s
              ON s.spreadsheet_id = r.spreadsheet_id
             AND s.sheet_title = r.sheet_title
            ORDER BY
              COALESCE(s.sort_ym, 0) ASC,
              COALESCE(s.sort_a, 0) ASC,
              COALESCE(s.sort_b, 0) ASC,
              r.sheet_title ASC,
              r.row_index ASC
            """
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def vyrobotka_get_debt_verify_state(self) -> dict[str, Any]:
        cur = await self.conn.execute(
            "SELECT * FROM vyrobotka_debt_verify_state WHERE id = 1"
        )
        row = await cur.fetchone()
        if not row:
            await self.conn.execute(
                "INSERT INTO vyrobotka_debt_verify_state(id, status) VALUES (1, 'idle')"
            )
            await self.conn.commit()
            return {
                "id": 1,
                "status": "idle",
                "total": 0,
                "done": 0,
                "message": None,
                "report_json": None,
                "cancel_requested": 0,
                "started_at": None,
                "finished_at": None,
                "report": None,
            }
        data = dict(row)
        report = None
        raw = data.get("report_json")
        if raw:
            try:
                report = json.loads(raw)
            except json.JSONDecodeError:
                report = None
        data["report"] = report
        return data

    async def vyrobotka_set_debt_verify_state(self, **fields: Any) -> dict[str, Any]:
        current = await self.vyrobotka_get_debt_verify_state()
        merged = {**current, **fields}
        report_json = merged.get("report_json")
        if "report" in fields:
            if fields["report"] is None:
                report_json = None
            else:
                report_json = json.dumps(fields["report"], ensure_ascii=False)
        await self.conn.execute(
            """
            INSERT INTO vyrobotka_debt_verify_state(
              id, status, total, done, message, report_json,
              cancel_requested, started_at, finished_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              status = excluded.status,
              total = excluded.total,
              done = excluded.done,
              message = excluded.message,
              report_json = excluded.report_json,
              cancel_requested = excluded.cancel_requested,
              started_at = excluded.started_at,
              finished_at = excluded.finished_at
            """,
            (
                merged.get("status") or "idle",
                int(merged.get("total") or 0),
                int(merged.get("done") or 0),
                merged.get("message"),
                report_json,
                int(merged.get("cancel_requested") or 0),
                merged.get("started_at"),
                merged.get("finished_at"),
            ),
        )
        await self.conn.commit()
        return await self.vyrobotka_get_debt_verify_state()

    async def vyrobotka_clear_debt_verify_rows(self) -> None:
        await self.conn.execute("DELETE FROM vyrobotka_debt_verify_rows")
        await self.conn.commit()

    async def vyrobotka_upsert_debt_verify_row(self, row: dict[str, Any]) -> None:
        from modules.vyrobotka.verify import pack_issues_payload

        if isinstance(row.get("issues"), str):
            issues = row["issues"]
        else:
            issues = json.dumps(pack_issues_payload(row), ensure_ascii=False)
        await self.conn.execute(
            """
            INSERT INTO vyrobotka_debt_verify_rows(
              sheet_title, ticket, verdict, summary, issues_json,
              sheet_total, sheet_paid, sheet_debt, sheet_status,
              crm_total, crm_paid, crm_debt, crm_status, crm_url,
              master, checked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(sheet_title, ticket) DO UPDATE SET
              verdict = excluded.verdict,
              summary = excluded.summary,
              issues_json = excluded.issues_json,
              sheet_total = excluded.sheet_total,
              sheet_paid = excluded.sheet_paid,
              sheet_debt = excluded.sheet_debt,
              sheet_status = excluded.sheet_status,
              crm_total = excluded.crm_total,
              crm_paid = excluded.crm_paid,
              crm_debt = excluded.crm_debt,
              crm_status = excluded.crm_status,
              crm_url = excluded.crm_url,
              master = excluded.master,
              checked_at = excluded.checked_at
            """,
            (
                row.get("sheet_title"),
                str(row.get("ticket") or ""),
                row.get("verdict") or "error",
                row.get("summary"),
                issues,
                row.get("sheet_total"),
                row.get("sheet_paid"),
                row.get("sheet_debt"),
                row.get("sheet_status"),
                row.get("crm_total"),
                row.get("crm_paid"),
                row.get("crm_debt"),
                row.get("crm_status"),
                row.get("crm_url"),
                row.get("master"),
            ),
        )
        await self.conn.commit()

    async def vyrobotka_list_debt_verify_rows(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT * FROM vyrobotka_debt_verify_rows
            ORDER BY
              CASE verdict
                WHEN 'mismatch' THEN 0
                WHEN 'missing' THEN 1
                WHEN 'error' THEN 2
                ELSE 3
              END,
              COALESCE(sheet_debt, 0) DESC,
              ticket ASC
            """
        )
        rows = await cur.fetchall()
        from modules.vyrobotka.verify import hydrate_field_diffs, unpack_issues_payload

        out: list[dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            try:
                raw = json.loads(item.get("issues_json") or "[]")
            except json.JSONDecodeError:
                raw = []
            messages, fields = unpack_issues_payload(raw)
            item["issues"] = messages
            item["field_diffs"] = fields
            item["field_diffs"] = hydrate_field_diffs(item)
            out.append(item)
        return out

    async def vyrobotka_upsert_debt_daily(self, row: dict[str, Any]) -> None:
        await self.conn.execute(
            """
            INSERT INTO vyrobotka_debt_daily(
              day, crm_debt_sum, sheets_debt_sum, crm_orders, sheets_tickets,
              source, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(day) DO UPDATE SET
              crm_debt_sum = excluded.crm_debt_sum,
              sheets_debt_sum = excluded.sheets_debt_sum,
              crm_orders = excluded.crm_orders,
              sheets_tickets = excluded.sheets_tickets,
              source = excluded.source,
              updated_at = excluded.updated_at
            """,
            (
                row["day"],
                row.get("crm_debt_sum"),
                row.get("sheets_debt_sum"),
                int(row.get("crm_orders") or 0),
                int(row.get("sheets_tickets") or 0),
                row.get("source"),
                row.get("updated_at"),
            ),
        )
        await self.conn.commit()

    async def vyrobotka_list_debt_daily(self, *, limit: int = 730) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT * FROM (
              SELECT * FROM vyrobotka_debt_daily
              ORDER BY day DESC
              LIMIT ?
            ) AS recent
            ORDER BY day ASC
            """,
            (max(1, int(limit)),),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
