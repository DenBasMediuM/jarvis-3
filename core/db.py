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
  sheet_id INTEGER,
  row_count INTEGER,
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

CREATE TABLE IF NOT EXISTS vyrobotka_debt_baseline (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  day TEXT,
  sheets_debt_sum REAL,
  sheets_tickets INTEGER,
  locked_at TEXT
);

CREATE TABLE IF NOT EXISTS vyrobotka_debt_baseline_tickets (
  sheet_title TEXT NOT NULL,
  ticket TEXT NOT NULL,
  PRIMARY KEY (sheet_title, ticket)
);

CREATE TABLE IF NOT EXISTS vyrobotka_debt_ledger (
  ticket TEXT PRIMARY KEY,
  active INTEGER NOT NULL DEFAULT 1,
  flag TEXT,
  flag_reason TEXT,
  first_sheet_total REAL,
  first_sheet_paid REAL,
  first_sheet_debt REAL,
  first_crm_total REAL,
  first_crm_paid REAL,
  first_crm_debt REAL,
  first_crm_status TEXT,
  first_on_pay_list INTEGER,
  first_seen_at TEXT,
  sheet_title TEXT,
  master TEXT,
  sheet_total REAL,
  sheet_paid REAL,
  sheet_debt REAL,
  report_amount REAL,
  crm_total REAL,
  crm_paid REAL,
  crm_debt REAL,
  crm_status TEXT,
  on_pay_list INTEGER NOT NULL DEFAULT 0,
  crm_url TEXT,
  crm_checked_at TEXT,
  crm_feed_json TEXT,
  crm_feed_at TEXT,
  decision_status TEXT,
  decision_code TEXT,
  decision_by TEXT,
  decision_at TEXT,
  moderated_by TEXT,
  moderated_at TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vyrobotka_debt_closed (
  ticket TEXT PRIMARY KEY,
  closed_at TEXT NOT NULL,
  decision_code TEXT,
  decision_by TEXT,
  decision_at TEXT,
  moderated_by TEXT,
  snapshot_json TEXT NOT NULL,
  flag TEXT,
  flag_reason TEXT,
  crm_debt REAL,
  sheet_debt REAL,
  crm_status TEXT,
  master TEXT,
  sheet_title TEXT,
  ui_hidden INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS vitrine_users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  login TEXT NOT NULL UNIQUE COLLATE NOCASE,
  salt TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  access_json TEXT NOT NULL DEFAULT '[]',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS branch_kpi_months (
  year INTEGER NOT NULL,
  month INTEGER NOT NULL,
  branch_id TEXT NOT NULL,
  acceptances INTEGER,
  gross_profit REAL,
  net_profit REAL,
  expense REAL,
  refusals INTEGER,
  return_rate REAL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (year, month, branch_id)
);

CREATE TABLE IF NOT EXISTS branch_kpi_sync_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  status TEXT NOT NULL DEFAULT 'idle',
  total INTEGER NOT NULL DEFAULT 0,
  done INTEGER NOT NULL DEFAULT 0,
  message TEXT,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS buffer_quality_daily (
  day TEXT PRIMARY KEY,
  buffer_count INTEGER NOT NULL DEFAULT 0,
  buffer_over_3d INTEGER NOT NULL DEFAULT 0,
  assigned_from_buffer INTEGER,
  masters_high INTEGER NOT NULL DEFAULT 0,
  masters_ok INTEGER NOT NULL DEFAULT 0,
  masters_low INTEGER NOT NULL DEFAULT 0,
  assign_to_high INTEGER NOT NULL DEFAULT 0,
  assign_to_ok INTEGER NOT NULL DEFAULT 0,
  assign_to_low INTEGER NOT NULL DEFAULT 0,
  assign_unknown INTEGER NOT NULL DEFAULT 0,
  avg_load_index REAL,
  dispatch_score REAL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS buffer_quality_buffer_ids (
  day TEXT NOT NULL,
  order_id TEXT NOT NULL,
  PRIMARY KEY (day, order_id)
);

CREATE TABLE IF NOT EXISTS buffer_quality_master_daily (
  day TEXT NOT NULL,
  master_key TEXT NOT NULL,
  display_name TEXT NOT NULL,
  open_count INTEGER NOT NULL DEFAULT 0,
  age_sum_days REAL NOT NULL DEFAULT 0,
  rework_orders INTEGER NOT NULL DEFAULT 0,
  no_diag_count INTEGER NOT NULL DEFAULT 0,
  load_index REAL NOT NULL DEFAULT 0,
  zone TEXT NOT NULL DEFAULT 'low',
  assigned_from_buffer INTEGER NOT NULL DEFAULT 0,
  assign_quality TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (day, master_key)
);

CREATE TABLE IF NOT EXISTS buffer_quality_sync_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  status TEXT NOT NULL DEFAULT 'idle',
  total INTEGER NOT NULL DEFAULT 0,
  done INTEGER NOT NULL DEFAULT 0,
  message TEXT,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS masters_kpi_masters (
  master_key TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  folder_name TEXT,
  folder_id TEXT,
  color TEXT,
  files INTEGER NOT NULL DEFAULT 0,
  lines INTEGER NOT NULL DEFAULT 0,
  tickets INTEGER NOT NULL DEFAULT 0,
  work_sum REAL,
  hours REAL,
  avg_ticket REAL,
  efficiency REAL,
  crm_orders INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS masters_kpi_weeks (
  master_key TEXT NOT NULL,
  iso_year INTEGER NOT NULL,
  iso_week INTEGER NOT NULL,
  week_start TEXT,
  tickets INTEGER,
  lines INTEGER,
  work_sum REAL,
  hours REAL,
  avg_ticket REAL,
  efficiency REAL,
  PRIMARY KEY (master_key, iso_year, iso_week)
);

CREATE TABLE IF NOT EXISTS masters_kpi_sync_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  status TEXT NOT NULL DEFAULT 'idle',
  total INTEGER NOT NULL DEFAULT 0,
  done INTEGER NOT NULL DEFAULT 0,
  message TEXT,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS reviews_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket TEXT NOT NULL,
  phone TEXT,
  phone_norm TEXT,
  client_name TEXT,
  manager TEXT,
  outcome TEXT NOT NULL,
  comment TEXT,
  device TEXT,
  branch_id TEXT,
  issued_at TEXT,
  repair_days REAL,
  called_at TEXT NOT NULL,
  source TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reviews_google_stats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT NOT NULL,
  branch_id TEXT NOT NULL,
  rating REAL NOT NULL,
  review_count INTEGER NOT NULL,
  noted_by TEXT,
  noted_at TEXT NOT NULL,
  UNIQUE (day, branch_id)
);

CREATE TABLE IF NOT EXISTS reviews_batch (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  day TEXT,
  tickets_json TEXT NOT NULL DEFAULT '[]',
  cards_json TEXT NOT NULL DEFAULT '[]',
  built_at TEXT,
  message TEXT
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
        await self._migrate_vyrobotka_schema()
        await self._migrate_reviews_schema()
        await self._conn.commit()

    async def _migrate_vyrobotka_schema(self) -> None:
        """Лёгкие ALTER для уже существующих БД."""
        cur = await self.conn.execute("PRAGMA table_info(vyrobotka_sheet_stats)")
        cols = {str(r[1]) for r in await cur.fetchall()}
        if "sheet_id" not in cols:
            await self.conn.execute(
                "ALTER TABLE vyrobotka_sheet_stats ADD COLUMN sheet_id INTEGER"
            )
        if "row_count" not in cols:
            await self.conn.execute(
                "ALTER TABLE vyrobotka_sheet_stats ADD COLUMN row_count INTEGER"
            )
        cur = await self.conn.execute("PRAGMA table_info(vyrobotka_debt_ledger)")
        ledger_cols = {str(r[1]) for r in await cur.fetchall()}
        if "crm_feed_json" not in ledger_cols:
            await self.conn.execute(
                "ALTER TABLE vyrobotka_debt_ledger ADD COLUMN crm_feed_json TEXT"
            )
        if "crm_feed_at" not in ledger_cols:
            await self.conn.execute(
                "ALTER TABLE vyrobotka_debt_ledger ADD COLUMN crm_feed_at TEXT"
            )
        for col, typ in (
            ("decision_status", "TEXT"),
            ("decision_code", "TEXT"),
            ("decision_by", "TEXT"),
            ("decision_at", "TEXT"),
            ("moderated_by", "TEXT"),
            ("moderated_at", "TEXT"),
        ):
            if col not in ledger_cols:
                await self.conn.execute(
                    f"ALTER TABLE vyrobotka_debt_ledger ADD COLUMN {col} {typ}"
                )
        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vyrobotka_debt_closed (
              ticket TEXT PRIMARY KEY,
              closed_at TEXT NOT NULL,
              decision_code TEXT,
              decision_by TEXT,
              decision_at TEXT,
              moderated_by TEXT,
              snapshot_json TEXT NOT NULL,
              flag TEXT,
              flag_reason TEXT,
              crm_debt REAL,
              sheet_debt REAL,
              crm_status TEXT,
              master TEXT,
              sheet_title TEXT,
              ui_hidden INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        closed_cols = {
            r[1]
            for r in await (
                await self.conn.execute("PRAGMA table_info(vyrobotka_debt_closed)")
            ).fetchall()
        }
        if "ui_hidden" not in closed_cols:
            await self.conn.execute(
                "ALTER TABLE vyrobotka_debt_closed ADD COLUMN ui_hidden INTEGER NOT NULL DEFAULT 0"
            )

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
            await self._vyrobotka_insert_row(r)
        for s in sheet_stats:
            await self._vyrobotka_upsert_sheet_stats(s)
        await self.conn.commit()

    async def _vyrobotka_insert_row(self, r: dict[str, Any]) -> None:
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

    async def _vyrobotka_upsert_sheet_stats(self, s: dict[str, Any]) -> None:
        await self.conn.execute(
            """
            INSERT INTO vyrobotka_sheet_stats(
              spreadsheet_id, sheet_title, sort_ym, sort_a, sort_b,
              tickets_count, report_sum, upsell_sum, upsell_count,
              avg_upsell, upsell_ratio, spreadsheet_title, sheet_id, row_count,
              updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(spreadsheet_id, sheet_title) DO UPDATE SET
              sort_ym = excluded.sort_ym,
              sort_a = excluded.sort_a,
              sort_b = excluded.sort_b,
              tickets_count = excluded.tickets_count,
              report_sum = excluded.report_sum,
              upsell_sum = excluded.upsell_sum,
              upsell_count = excluded.upsell_count,
              avg_upsell = excluded.avg_upsell,
              upsell_ratio = excluded.upsell_ratio,
              spreadsheet_title = excluded.spreadsheet_title,
              sheet_id = COALESCE(excluded.sheet_id, vyrobotka_sheet_stats.sheet_id),
              row_count = excluded.row_count,
              updated_at = datetime('now')
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
                s.get("sheet_id"),
                s.get("row_count"),
            ),
        )

    async def vyrobotka_replace_sheet_rows(
        self,
        *,
        spreadsheet_id: str,
        sheet_title: str,
        rows: list[dict[str, Any]],
        sheet_stats: dict[str, Any],
    ) -> None:
        """Заменить строки одного листа, остальные листы не трогать."""
        await self.conn.execute(
            """
            DELETE FROM vyrobotka_rows
            WHERE spreadsheet_id = ? AND sheet_title = ?
            """,
            (spreadsheet_id, sheet_title),
        )
        for r in rows:
            await self._vyrobotka_insert_row(r)
        await self._vyrobotka_upsert_sheet_stats(sheet_stats)
        await self.conn.commit()

    async def vyrobotka_touch_sheet_meta(self, sheet_stats: dict[str, Any]) -> None:
        """Обновить метаданные листа (sheet_id и т.п.) без перезаписи строк."""
        await self._vyrobotka_upsert_sheet_stats(sheet_stats)
        await self.conn.commit()

    async def vyrobotka_known_sheet_meta(self) -> dict[str, dict[str, Any]]:
        """sheet_title → {tickets_count, row_count, sheet_id, ...}."""
        cur = await self.conn.execute("SELECT * FROM vyrobotka_sheet_stats")
        rows = await cur.fetchall()
        return {str(r["sheet_title"]): dict(r) for r in rows}

    async def vyrobotka_get_debt_baseline(self) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            "SELECT * FROM vyrobotka_debt_baseline WHERE id = 1"
        )
        row = await cur.fetchone()
        if not row or not row["day"]:
            return None
        return dict(row)

    async def vyrobotka_list_debt_baseline_tickets(self) -> list[dict[str, str]]:
        cur = await self.conn.execute(
            "SELECT sheet_title, ticket FROM vyrobotka_debt_baseline_tickets"
        )
        return [dict(r) for r in await cur.fetchall()]

    async def vyrobotka_set_debt_baseline(
        self,
        *,
        day: str,
        sheets_debt_sum: float,
        sheets_tickets: int,
        tickets: list[dict[str, Any]],
        locked_at: str | None = None,
    ) -> dict[str, Any]:
        await self.conn.execute(
            """
            INSERT INTO vyrobotka_debt_baseline(
              id, day, sheets_debt_sum, sheets_tickets, locked_at
            ) VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              day = excluded.day,
              sheets_debt_sum = excluded.sheets_debt_sum,
              sheets_tickets = excluded.sheets_tickets,
              locked_at = excluded.locked_at
            """,
            (
                day,
                float(sheets_debt_sum),
                int(sheets_tickets),
                locked_at or datetime.now(timezone.utc).isoformat(),
            ),
        )
        await self.conn.execute("DELETE FROM vyrobotka_debt_baseline_tickets")
        for t in tickets:
            await self.conn.execute(
                """
                INSERT OR IGNORE INTO vyrobotka_debt_baseline_tickets(sheet_title, ticket)
                VALUES (?, ?)
                """,
                (str(t.get("sheet_title") or ""), str(t.get("ticket") or "")),
            )
        await self.conn.commit()
        out = await self.vyrobotka_get_debt_baseline()
        return out or {}

    async def vyrobotka_list_debt_ledger(
        self, *, active_only: bool = True
    ) -> list[dict[str, Any]]:
        if active_only:
            cur = await self.conn.execute(
                """
                SELECT * FROM vyrobotka_debt_ledger
                WHERE active = 1
                ORDER BY
                  CASE flag
                    WHEN 'red' THEN 0
                    WHEN 'mismatch' THEN 1
                    WHEN 'yellow' THEN 2
                    WHEN 'open' THEN 3
                    ELSE 4
                  END,
                  COALESCE(crm_debt, sheet_debt, 0) DESC,
                  ticket ASC
                """
            )
        else:
            cur = await self.conn.execute(
                """
                SELECT * FROM vyrobotka_debt_ledger
                ORDER BY ticket ASC
                """
            )
        return [dict(r) for r in await cur.fetchall()]

    async def vyrobotka_get_debt_ledger_ticket(
        self, ticket: str
    ) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            "SELECT * FROM vyrobotka_debt_ledger WHERE ticket = ?",
            (str(ticket),),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def vyrobotka_upsert_debt_ledger(self, row: dict[str, Any]) -> None:
        """Upsert ledger row. first_* заполняются только если ещё пусты."""
        ticket = str(row.get("ticket") or "").strip()
        if not ticket:
            return
        existing = await self.vyrobotka_get_debt_ledger_ticket(ticket)
        now = datetime.now(timezone.utc).isoformat()

        def _keep_first(key: str, new_val: Any) -> Any:
            if existing and existing.get(key) is not None and existing.get(key) != "":
                return existing.get(key)
            return new_val if new_val is not None else (existing or {}).get(key)

        first_seen = (existing or {}).get("first_seen_at") or row.get("first_seen_at") or now
        merged = {
            "ticket": ticket,
            "active": int(row["active"]) if "active" in row else (
                int(existing["active"]) if existing and "active" in existing else 1
            ),
            "flag": row.get("flag", (existing or {}).get("flag")),
            "flag_reason": row.get("flag_reason", (existing or {}).get("flag_reason")),
            "first_sheet_total": _keep_first("first_sheet_total", row.get("first_sheet_total")),
            "first_sheet_paid": _keep_first("first_sheet_paid", row.get("first_sheet_paid")),
            "first_sheet_debt": _keep_first("first_sheet_debt", row.get("first_sheet_debt")),
            "first_crm_total": _keep_first("first_crm_total", row.get("first_crm_total")),
            "first_crm_paid": _keep_first("first_crm_paid", row.get("first_crm_paid")),
            "first_crm_debt": _keep_first("first_crm_debt", row.get("first_crm_debt")),
            "first_crm_status": _keep_first("first_crm_status", row.get("first_crm_status")),
            "first_on_pay_list": _keep_first(
                "first_on_pay_list",
                row.get("first_on_pay_list"),
            ),
            "first_seen_at": first_seen,
            "sheet_title": row.get(
                "sheet_title", (existing or {}).get("sheet_title")
            ),
            "master": row.get("master", (existing or {}).get("master")),
            "sheet_total": row.get(
                "sheet_total", (existing or {}).get("sheet_total")
            ),
            "sheet_paid": row.get("sheet_paid", (existing or {}).get("sheet_paid")),
            "sheet_debt": row.get("sheet_debt", (existing or {}).get("sheet_debt")),
            "report_amount": row.get(
                "report_amount", (existing or {}).get("report_amount")
            ),
            "crm_total": row.get("crm_total", (existing or {}).get("crm_total")),
            "crm_paid": row.get("crm_paid", (existing or {}).get("crm_paid")),
            "crm_debt": row.get("crm_debt", (existing or {}).get("crm_debt")),
            "crm_status": row.get(
                "crm_status", (existing or {}).get("crm_status")
            ),
            "on_pay_list": int(
                row["on_pay_list"]
                if "on_pay_list" in row
                else ((existing or {}).get("on_pay_list") or 0)
            ),
            "crm_url": row.get("crm_url", (existing or {}).get("crm_url")),
            "crm_checked_at": row.get(
                "crm_checked_at", (existing or {}).get("crm_checked_at")
            ),
            "crm_feed_json": row.get(
                "crm_feed_json", (existing or {}).get("crm_feed_json")
            ),
            "crm_feed_at": row.get(
                "crm_feed_at", (existing or {}).get("crm_feed_at")
            ),
            "updated_at": now,
        }
        # Explicit None overwrite for CRM fields when provided as keys
        for k in (
            "crm_total",
            "crm_paid",
            "crm_debt",
            "crm_status",
            "sheet_total",
            "sheet_paid",
            "sheet_debt",
            "flag",
            "flag_reason",
            "crm_feed_json",
            "crm_feed_at",
        ):
            if k in row:
                merged[k] = row[k]

        await self.conn.execute(
            """
            INSERT INTO vyrobotka_debt_ledger(
              ticket, active, flag, flag_reason,
              first_sheet_total, first_sheet_paid, first_sheet_debt,
              first_crm_total, first_crm_paid, first_crm_debt,
              first_crm_status, first_on_pay_list, first_seen_at,
              sheet_title, master, sheet_total, sheet_paid, sheet_debt,
              report_amount, crm_total, crm_paid, crm_debt, crm_status,
              on_pay_list, crm_url, crm_checked_at, crm_feed_json, crm_feed_at,
              updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(ticket) DO UPDATE SET
              active = excluded.active,
              flag = excluded.flag,
              flag_reason = excluded.flag_reason,
              first_sheet_total = COALESCE(vyrobotka_debt_ledger.first_sheet_total, excluded.first_sheet_total),
              first_sheet_paid = COALESCE(vyrobotka_debt_ledger.first_sheet_paid, excluded.first_sheet_paid),
              first_sheet_debt = COALESCE(vyrobotka_debt_ledger.first_sheet_debt, excluded.first_sheet_debt),
              first_crm_total = COALESCE(vyrobotka_debt_ledger.first_crm_total, excluded.first_crm_total),
              first_crm_paid = COALESCE(vyrobotka_debt_ledger.first_crm_paid, excluded.first_crm_paid),
              first_crm_debt = COALESCE(vyrobotka_debt_ledger.first_crm_debt, excluded.first_crm_debt),
              first_crm_status = COALESCE(vyrobotka_debt_ledger.first_crm_status, excluded.first_crm_status),
              first_on_pay_list = COALESCE(vyrobotka_debt_ledger.first_on_pay_list, excluded.first_on_pay_list),
              first_seen_at = COALESCE(vyrobotka_debt_ledger.first_seen_at, excluded.first_seen_at),
              sheet_title = excluded.sheet_title,
              master = excluded.master,
              sheet_total = excluded.sheet_total,
              sheet_paid = excluded.sheet_paid,
              sheet_debt = excluded.sheet_debt,
              report_amount = excluded.report_amount,
              crm_total = excluded.crm_total,
              crm_paid = excluded.crm_paid,
              crm_debt = excluded.crm_debt,
              crm_status = excluded.crm_status,
              on_pay_list = excluded.on_pay_list,
              crm_url = excluded.crm_url,
              crm_checked_at = excluded.crm_checked_at,
              crm_feed_json = COALESCE(excluded.crm_feed_json, vyrobotka_debt_ledger.crm_feed_json),
              crm_feed_at = COALESCE(excluded.crm_feed_at, vyrobotka_debt_ledger.crm_feed_at),
              updated_at = excluded.updated_at
            """,
            (
                merged["ticket"],
                merged["active"],
                merged["flag"],
                merged["flag_reason"],
                merged["first_sheet_total"],
                merged["first_sheet_paid"],
                merged["first_sheet_debt"],
                merged["first_crm_total"],
                merged["first_crm_paid"],
                merged["first_crm_debt"],
                merged["first_crm_status"],
                merged["first_on_pay_list"],
                merged["first_seen_at"],
                merged["sheet_title"],
                merged["master"],
                merged["sheet_total"],
                merged["sheet_paid"],
                merged["sheet_debt"],
                merged["report_amount"],
                merged["crm_total"],
                merged["crm_paid"],
                merged["crm_debt"],
                merged["crm_status"],
                merged["on_pay_list"],
                merged["crm_url"],
                merged["crm_checked_at"],
                merged["crm_feed_json"],
                merged["crm_feed_at"],
                merged["updated_at"],
            ),
        )
        await self.conn.commit()

    async def vyrobotka_set_debt_decision(
        self,
        ticket: str,
        *,
        decision_status: str | None,
        decision_code: str | None = None,
        decision_by: str | None = None,
        decision_at: str | None = None,
        moderated_by: str | None = None,
        moderated_at: str | None = None,
        clear_moderation: bool = False,
    ) -> dict[str, Any] | None:
        oid = str(ticket or "").strip()
        if not oid:
            return None
        now = datetime.now(timezone.utc).isoformat()
        row = await self.vyrobotka_get_debt_ledger_ticket(oid)
        if not row:
            return None
        fields = {
            "decision_status": decision_status,
            "decision_code": decision_code,
            "decision_by": decision_by,
            "decision_at": decision_at,
            "updated_at": now,
        }
        if clear_moderation:
            fields["moderated_by"] = None
            fields["moderated_at"] = None
        else:
            if moderated_by is not None:
                fields["moderated_by"] = moderated_by
            if moderated_at is not None:
                fields["moderated_at"] = moderated_at
        sets = ", ".join(f"{k} = ?" for k in fields)
        await self.conn.execute(
            f"UPDATE vyrobotka_debt_ledger SET {sets} WHERE ticket = ?",
            (*fields.values(), oid),
        )
        await self.conn.commit()
        return await self.vyrobotka_get_debt_ledger_ticket(oid)

    async def vyrobotka_list_debt_pending(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT * FROM vyrobotka_debt_ledger
            WHERE active = 1 AND decision_status = 'pending'
            ORDER BY decision_at ASC, ticket ASC
            """
        )
        return [dict(r) for r in await cur.fetchall()]

    async def vyrobotka_close_debt_ticket(
        self,
        ticket: str,
        *,
        moderated_by: str | None,
    ) -> dict[str, Any] | None:
        import json as _json

        oid = str(ticket or "").strip()
        row = await self.vyrobotka_get_debt_ledger_ticket(oid)
        if not row:
            return None
        now = datetime.now(timezone.utc).isoformat()
        snap = dict(row)
        await self.conn.execute(
            """
            INSERT INTO vyrobotka_debt_closed(
              ticket, closed_at, decision_code, decision_by, decision_at,
              moderated_by, snapshot_json, flag, flag_reason,
              crm_debt, sheet_debt, crm_status, master, sheet_title
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticket) DO UPDATE SET
              closed_at = excluded.closed_at,
              decision_code = excluded.decision_code,
              decision_by = excluded.decision_by,
              decision_at = excluded.decision_at,
              moderated_by = excluded.moderated_by,
              snapshot_json = excluded.snapshot_json,
              flag = excluded.flag,
              flag_reason = excluded.flag_reason,
              crm_debt = excluded.crm_debt,
              sheet_debt = excluded.sheet_debt,
              crm_status = excluded.crm_status,
              master = excluded.master,
              sheet_title = excluded.sheet_title
            """,
            (
                oid,
                now,
                row.get("decision_code"),
                row.get("decision_by"),
                row.get("decision_at"),
                moderated_by,
                _json.dumps(snap, ensure_ascii=False),
                row.get("flag"),
                row.get("flag_reason"),
                row.get("crm_debt"),
                row.get("sheet_debt"),
                row.get("crm_status"),
                row.get("master"),
                row.get("sheet_title"),
            ),
        )
        await self.conn.execute(
            """
            UPDATE vyrobotka_debt_ledger
            SET active = 0, decision_status = 'closed',
                moderated_by = ?, moderated_at = ?, updated_at = ?
            WHERE ticket = ?
            """,
            (moderated_by, now, now, oid),
        )
        await self.conn.commit()
        return {
            "ticket": oid,
            "closed_at": now,
            "decision_code": row.get("decision_code"),
            "moderated_by": moderated_by,
        }

    async def vyrobotka_list_debt_closed(
        self, *, limit: int = 500, include_hidden: bool = False
    ) -> list[dict[str, Any]]:
        if include_hidden:
            cur = await self.conn.execute(
                """
                SELECT ticket, closed_at, decision_code, decision_by, decision_at,
                       moderated_by, flag, flag_reason, crm_debt, sheet_debt,
                       crm_status, master, sheet_title, ui_hidden
                FROM vyrobotka_debt_closed
                ORDER BY closed_at DESC
                LIMIT ?
                """,
                (int(limit),),
            )
        else:
            cur = await self.conn.execute(
                """
                SELECT ticket, closed_at, decision_code, decision_by, decision_at,
                       moderated_by, flag, flag_reason, crm_debt, sheet_debt,
                       crm_status, master, sheet_title, ui_hidden
                FROM vyrobotka_debt_closed
                WHERE COALESCE(ui_hidden, 0) = 0
                ORDER BY closed_at DESC
                LIMIT ?
                """,
                (int(limit),),
            )
        return [dict(r) for r in await cur.fetchall()]

    async def vyrobotka_set_debt_closed_hidden(self, ticket: str, *, hidden: bool) -> bool:
        oid = str(ticket or "").strip()
        if not oid:
            return False
        cur = await self.conn.execute(
            "UPDATE vyrobotka_debt_closed SET ui_hidden = ? WHERE ticket = ?",
            (1 if hidden else 0, oid),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def vyrobotka_get_debt_closed(self, ticket: str) -> dict[str, Any] | None:
        oid = str(ticket or "").strip()
        if not oid:
            return None
        cur = await self.conn.execute(
            "SELECT * FROM vyrobotka_debt_closed WHERE ticket = ?", (oid,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def vyrobotka_reopen_debt_closed(self, ticket: str) -> dict[str, Any] | None:
        """Вернуть закрытую квитанцию в активный ledger; запись в closed остаётся для статистики."""
        import json as _json

        oid = str(ticket or "").strip()
        closed = await self.vyrobotka_get_debt_closed(oid)
        if not closed:
            return None
        now = datetime.now(timezone.utc).isoformat()
        snap: dict[str, Any] = {}
        try:
            snap = _json.loads(closed.get("snapshot_json") or "{}")
        except Exception:  # noqa: BLE001
            snap = {}
        existing = await self.vyrobotka_get_debt_ledger_ticket(oid)
        if existing:
            await self.conn.execute(
                """
                UPDATE vyrobotka_debt_ledger
                SET active = 1,
                    decision_status = NULL,
                    decision_code = NULL,
                    decision_by = NULL,
                    decision_at = NULL,
                    moderated_by = NULL,
                    moderated_at = NULL,
                    updated_at = ?
                WHERE ticket = ?
                """,
                (now, oid),
            )
        else:
            await self.conn.execute(
                """
                INSERT INTO vyrobotka_debt_ledger(
                  ticket, active, flag, flag_reason,
                  sheet_title, master, sheet_total, sheet_paid, sheet_debt,
                  report_amount, crm_total, crm_paid, crm_debt, crm_status,
                  on_pay_list, crm_url, crm_checked_at, crm_feed_json, crm_feed_at,
                  updated_at
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    oid,
                    snap.get("flag") or closed.get("flag"),
                    snap.get("flag_reason") or closed.get("flag_reason"),
                    snap.get("sheet_title") or closed.get("sheet_title"),
                    snap.get("master") or closed.get("master"),
                    snap.get("sheet_total"),
                    snap.get("sheet_paid"),
                    snap.get("sheet_debt") if snap.get("sheet_debt") is not None else closed.get("sheet_debt"),
                    snap.get("report_amount"),
                    snap.get("crm_total"),
                    snap.get("crm_paid"),
                    snap.get("crm_debt") if snap.get("crm_debt") is not None else closed.get("crm_debt"),
                    snap.get("crm_status") or closed.get("crm_status"),
                    int(snap.get("on_pay_list") or 0),
                    snap.get("crm_url"),
                    snap.get("crm_checked_at"),
                    snap.get("crm_feed_json"),
                    snap.get("crm_feed_at"),
                    now,
                ),
            )
        await self.conn.execute(
            "UPDATE vyrobotka_debt_closed SET ui_hidden = 1 WHERE ticket = ?",
            (oid,),
        )
        await self.conn.commit()
        return await self.vyrobotka_get_debt_ledger_ticket(oid)

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
                # CRM-only квитанции без листа отчёта — пустая строка вместо NULL
                str(row.get("sheet_title") or ""),
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

    async def vitrine_list_users(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT * FROM vitrine_users ORDER BY login COLLATE NOCASE ASC"
        )
        return [dict(r) for r in await cur.fetchall()]

    async def vitrine_get_user(self, user_id: int) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            "SELECT * FROM vitrine_users WHERE id = ?", (int(user_id),)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def vitrine_get_user_by_login(self, login: str) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            "SELECT * FROM vitrine_users WHERE login = ? COLLATE NOCASE",
            (str(login or "").strip(),),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def vitrine_create_user(self, row: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        cur = await self.conn.execute(
            """
            INSERT INTO vitrine_users(login, salt, password_hash, access_json, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["login"],
                row["salt"],
                row["password_hash"],
                row.get("access_json") or "[]",
                int(row.get("enabled", 1)),
                now,
                now,
            ),
        )
        await self.conn.commit()
        created = await self.vitrine_get_user(int(cur.lastrowid))
        assert created is not None
        return created

    async def vitrine_update_user(self, user_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
        current = await self.vitrine_get_user(user_id)
        if not current:
            return None
        data = {**current, **fields, "updated_at": datetime.now(timezone.utc).isoformat()}
        await self.conn.execute(
            """
            UPDATE vitrine_users SET
              login = ?, salt = ?, password_hash = ?, access_json = ?,
              enabled = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                data["login"],
                data["salt"],
                data["password_hash"],
                data.get("access_json") or "[]",
                int(data.get("enabled", 1)),
                data["updated_at"],
                int(user_id),
            ),
        )
        await self.conn.commit()
        return await self.vitrine_get_user(user_id)

    async def vitrine_delete_user(self, user_id: int) -> bool:
        cur = await self.conn.execute(
            "DELETE FROM vitrine_users WHERE id = ?", (int(user_id),)
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def branch_kpi_get_sync_state(self) -> dict[str, Any]:
        cur = await self.conn.execute(
            "SELECT * FROM branch_kpi_sync_state WHERE id = 1"
        )
        row = await cur.fetchone()
        if not row:
            await self.conn.execute(
                "INSERT INTO branch_kpi_sync_state(id, status) VALUES (1, 'idle')"
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

    async def branch_kpi_set_sync_state(self, **fields: Any) -> dict[str, Any]:
        current = await self.branch_kpi_get_sync_state()
        current.update(fields)
        await self.conn.execute(
            """
            INSERT INTO branch_kpi_sync_state(
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
        return await self.branch_kpi_get_sync_state()

    async def branch_kpi_replace_months(self, rows: list[dict[str, Any]]) -> None:
        await self.conn.execute("DELETE FROM branch_kpi_months")
        for r in rows:
            await self.conn.execute(
                """
                INSERT INTO branch_kpi_months(
                  year, month, branch_id, acceptances, gross_profit, net_profit,
                  expense, refusals, return_rate, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    int(r["year"]),
                    int(r["month"]),
                    str(r["branch_id"]),
                    r.get("acceptances"),
                    r.get("gross_profit"),
                    r.get("net_profit"),
                    r.get("expense"),
                    r.get("refusals"),
                    r.get("return_rate"),
                ),
            )
        await self.conn.commit()

    async def branch_kpi_list_months(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT * FROM branch_kpi_months
            ORDER BY year ASC, month ASC, branch_id ASC
            """
        )
        return [dict(r) for r in await cur.fetchall()]

    async def buffer_quality_get_sync_state(self) -> dict[str, Any]:
        cur = await self.conn.execute(
            "SELECT * FROM buffer_quality_sync_state WHERE id = 1"
        )
        row = await cur.fetchone()
        if not row:
            await self.conn.execute(
                "INSERT INTO buffer_quality_sync_state(id, status) VALUES (1, 'idle')"
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

    async def buffer_quality_set_sync_state(self, **fields: Any) -> dict[str, Any]:
        current = await self.buffer_quality_get_sync_state()
        current.update(fields)
        await self.conn.execute(
            """
            INSERT INTO buffer_quality_sync_state(
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
        return await self.buffer_quality_get_sync_state()

    async def buffer_quality_upsert_daily(self, row: dict[str, Any]) -> None:
        await self.conn.execute(
            """
            INSERT INTO buffer_quality_daily(
              day, buffer_count, buffer_over_3d, assigned_from_buffer,
              masters_high, masters_ok, masters_low,
              assign_to_high, assign_to_ok, assign_to_low, assign_unknown,
              avg_load_index, dispatch_score, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(day) DO UPDATE SET
              buffer_count = excluded.buffer_count,
              buffer_over_3d = excluded.buffer_over_3d,
              assigned_from_buffer = excluded.assigned_from_buffer,
              masters_high = excluded.masters_high,
              masters_ok = excluded.masters_ok,
              masters_low = excluded.masters_low,
              assign_to_high = excluded.assign_to_high,
              assign_to_ok = excluded.assign_to_ok,
              assign_to_low = excluded.assign_to_low,
              assign_unknown = excluded.assign_unknown,
              avg_load_index = excluded.avg_load_index,
              dispatch_score = excluded.dispatch_score,
              updated_at = excluded.updated_at
            """,
            (
                row["day"],
                int(row.get("buffer_count") or 0),
                int(row.get("buffer_over_3d") or 0),
                row.get("assigned_from_buffer"),
                int(row.get("masters_high") or 0),
                int(row.get("masters_ok") or 0),
                int(row.get("masters_low") or 0),
                int(row.get("assign_to_high") or 0),
                int(row.get("assign_to_ok") or 0),
                int(row.get("assign_to_low") or 0),
                int(row.get("assign_unknown") or 0),
                row.get("avg_load_index"),
                row.get("dispatch_score"),
            ),
        )
        await self.conn.commit()

    async def buffer_quality_list_daily(self, *, limit: int = 365) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT * FROM (
              SELECT * FROM buffer_quality_daily
              ORDER BY day DESC
              LIMIT ?
            ) AS recent
            ORDER BY day ASC
            """,
            (max(1, int(limit)),),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def buffer_quality_get_daily(self, day: str) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            "SELECT * FROM buffer_quality_daily WHERE day = ?", (day,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def buffer_quality_replace_buffer_ids(self, day: str, order_ids: list[str]) -> None:
        await self.conn.execute(
            "DELETE FROM buffer_quality_buffer_ids WHERE day = ?", (day,)
        )
        for oid in order_ids:
            await self.conn.execute(
                "INSERT INTO buffer_quality_buffer_ids(day, order_id) VALUES (?, ?)",
                (day, str(oid)),
            )
        await self.conn.commit()

    async def buffer_quality_list_buffer_ids(self, day: str) -> list[str]:
        cur = await self.conn.execute(
            "SELECT order_id FROM buffer_quality_buffer_ids WHERE day = ? ORDER BY order_id",
            (day,),
        )
        return [str(r["order_id"]) for r in await cur.fetchall()]

    async def buffer_quality_replace_masters_daily(
        self, day: str, rows: list[dict[str, Any]]
    ) -> None:
        await self.conn.execute(
            "DELETE FROM buffer_quality_master_daily WHERE day = ?", (day,)
        )
        for r in rows:
            await self.conn.execute(
                """
                INSERT INTO buffer_quality_master_daily(
                  day, master_key, display_name, open_count, age_sum_days,
                  rework_orders, no_diag_count, load_index, zone,
                  assigned_from_buffer, assign_quality, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    day,
                    str(r["master_key"]),
                    str(r.get("display_name") or r["master_key"]),
                    int(r.get("open_count") or 0),
                    float(r.get("age_sum_days") or 0),
                    int(r.get("rework_orders") or 0),
                    int(r.get("no_diag_count") or 0),
                    float(r.get("load_index") or 0),
                    str(r.get("zone") or "low"),
                    int(r.get("assigned_from_buffer") or 0),
                    r.get("assign_quality"),
                ),
            )
        await self.conn.commit()

    async def buffer_quality_list_masters_daily(
        self, day: str
    ) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT * FROM buffer_quality_master_daily
            WHERE day = ?
            ORDER BY load_index DESC, display_name COLLATE NOCASE ASC
            """,
            (day,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def buffer_quality_list_masters_range(
        self, *, limit_days: int = 90
    ) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT m.* FROM buffer_quality_master_daily m
            WHERE m.day IN (
              SELECT day FROM (
                SELECT DISTINCT day FROM buffer_quality_master_daily
                ORDER BY day DESC
                LIMIT ?
              )
            )
            ORDER BY m.day ASC, m.load_index DESC
            """,
            (max(1, int(limit_days)),),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def masters_kpi_get_sync_state(self) -> dict[str, Any]:
        cur = await self.conn.execute(
            "SELECT * FROM masters_kpi_sync_state WHERE id = 1"
        )
        row = await cur.fetchone()
        if not row:
            await self.conn.execute(
                "INSERT INTO masters_kpi_sync_state(id, status) VALUES (1, 'idle')"
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

    async def masters_kpi_set_sync_state(self, **fields: Any) -> dict[str, Any]:
        current = await self.masters_kpi_get_sync_state()
        current.update(fields)
        await self.conn.execute(
            """
            INSERT INTO masters_kpi_sync_state(
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
        return await self.masters_kpi_get_sync_state()

    async def masters_kpi_replace_all(
        self,
        masters: list[dict[str, Any]],
        weeks: list[dict[str, Any]],
    ) -> None:
        await self.conn.execute("DELETE FROM masters_kpi_weeks")
        await self.conn.execute("DELETE FROM masters_kpi_masters")
        for m in masters:
            await self.conn.execute(
                """
                INSERT INTO masters_kpi_masters(
                  master_key, display_name, folder_name, folder_id, color,
                  files, lines, tickets, work_sum, hours, avg_ticket,
                  efficiency, crm_orders, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    str(m["master_key"]),
                    str(m.get("display_name") or m["master_key"]),
                    m.get("folder_name"),
                    m.get("folder_id"),
                    m.get("color"),
                    int(m.get("files") or 0),
                    int(m.get("lines") or 0),
                    int(m.get("tickets") or 0),
                    m.get("work_sum"),
                    m.get("hours"),
                    m.get("avg_ticket"),
                    m.get("efficiency"),
                    int(m.get("crm_orders") or 0),
                ),
            )
        for w in weeks:
            await self.conn.execute(
                """
                INSERT INTO masters_kpi_weeks(
                  master_key, iso_year, iso_week, week_start, tickets, lines,
                  work_sum, hours, avg_ticket, efficiency
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(w["master_key"]),
                    int(w["iso_year"]),
                    int(w["iso_week"]),
                    w.get("week_start"),
                    w.get("tickets"),
                    w.get("lines"),
                    w.get("work_sum"),
                    w.get("hours"),
                    w.get("avg_ticket"),
                    w.get("efficiency"),
                ),
            )
        await self.conn.commit()

    async def masters_kpi_list_masters(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT * FROM masters_kpi_masters
            ORDER BY (work_sum IS NULL), work_sum DESC, display_name ASC
            """
        )
        return [dict(r) for r in await cur.fetchall()]

    async def masters_kpi_list_weeks(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT * FROM masters_kpi_weeks
            ORDER BY iso_year ASC, iso_week ASC, master_key ASC
            """
        )
        return [dict(r) for r in await cur.fetchall()]

    async def _migrate_reviews_schema(self) -> None:
        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews_calls (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ticket TEXT NOT NULL,
              phone TEXT,
              phone_norm TEXT,
              client_name TEXT,
              manager TEXT,
              outcome TEXT NOT NULL,
              comment TEXT,
              device TEXT,
              branch_id TEXT,
              issued_at TEXT,
              repair_days REAL,
              called_at TEXT NOT NULL,
              source TEXT,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews_google_stats (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              day TEXT NOT NULL,
              branch_id TEXT NOT NULL,
              rating REAL NOT NULL,
              review_count INTEGER NOT NULL,
              noted_by TEXT,
              noted_at TEXT NOT NULL,
              UNIQUE (day, branch_id)
            )
            """
        )
        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews_batch (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              day TEXT,
              tickets_json TEXT NOT NULL DEFAULT '[]',
              cards_json TEXT NOT NULL DEFAULT '[]',
              built_at TEXT,
              message TEXT
            )
            """
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reviews_calls_phone ON reviews_calls(phone_norm)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reviews_calls_ticket ON reviews_calls(ticket)"
        )

    async def reviews_insert_call(self, row: dict[str, Any]) -> int:
        cur = await self.conn.execute(
            """
            INSERT INTO reviews_calls(
              ticket, phone, phone_norm, client_name, manager, outcome, comment,
              device, branch_id, issued_at, repair_days, called_at, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(row["ticket"]),
                row.get("phone"),
                row.get("phone_norm"),
                row.get("client_name"),
                row.get("manager"),
                str(row["outcome"]),
                row.get("comment"),
                row.get("device"),
                row.get("branch_id"),
                row.get("issued_at"),
                row.get("repair_days"),
                str(row["called_at"]),
                row.get("source") or "cf",
            ),
        )
        await self.conn.commit()
        return int(cur.lastrowid or 0)

    async def reviews_list_calls(self, *, limit: int = 500) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT * FROM reviews_calls
            ORDER BY called_at DESC, id DESC
            LIMIT ?
            """,
            (int(limit),),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def reviews_delete_call(self, call_id: int) -> bool:
        cur = await self.conn.execute(
            "DELETE FROM reviews_calls WHERE id = ?",
            (int(call_id),),
        )
        await self.conn.commit()
        return int(cur.rowcount or 0) > 0

    async def reviews_get_call(self, call_id: int) -> dict[str, Any] | None:
        cur = await self.conn.execute(
            "SELECT * FROM reviews_calls WHERE id = ?",
            (int(call_id),),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def reviews_called_phones(self) -> set[str]:
        cur = await self.conn.execute(
            "SELECT DISTINCT phone_norm FROM reviews_calls WHERE phone_norm IS NOT NULL AND phone_norm != ''"
        )
        return {str(r[0]) for r in await cur.fetchall() if r[0]}

    async def reviews_called_tickets(self) -> set[str]:
        cur = await self.conn.execute("SELECT DISTINCT ticket FROM reviews_calls")
        return {str(r[0]) for r in await cur.fetchall() if r[0]}

    async def reviews_upsert_google_stats(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            await self.conn.execute(
                """
                INSERT INTO reviews_google_stats(
                  day, branch_id, rating, review_count, noted_by, noted_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(day, branch_id) DO UPDATE SET
                  rating = excluded.rating,
                  review_count = excluded.review_count,
                  noted_by = excluded.noted_by,
                  noted_at = excluded.noted_at
                """,
                (
                    str(row["day"]),
                    str(row["branch_id"]),
                    float(row["rating"]),
                    int(row["review_count"]),
                    row.get("noted_by"),
                    str(row["noted_at"]),
                ),
            )
        await self.conn.commit()

    async def reviews_list_google_stats(self, *, limit: int = 500) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT * FROM reviews_google_stats
            ORDER BY day DESC, branch_id ASC
            LIMIT ?
            """,
            (int(limit),),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def reviews_latest_google_stats(self) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            """
            SELECT g.* FROM reviews_google_stats g
            INNER JOIN (
              SELECT branch_id, MAX(day) AS day
              FROM reviews_google_stats
              GROUP BY branch_id
            ) t ON g.branch_id = t.branch_id AND g.day = t.day
            ORDER BY g.branch_id ASC
            """
        )
        return [dict(r) for r in await cur.fetchall()]

    async def reviews_get_batch(self) -> dict[str, Any] | None:
        cur = await self.conn.execute("SELECT * FROM reviews_batch WHERE id = 1")
        row = await cur.fetchone()
        return dict(row) if row else None

    async def reviews_set_batch(
        self,
        *,
        day: str,
        tickets: list[str],
        cards: list[dict[str, Any]],
        message: str | None = None,
        built_at: str | None = None,
    ) -> None:
        import json as _json
        from datetime import datetime, timezone

        at = built_at or datetime.now(timezone.utc).isoformat()
        await self.conn.execute(
            """
            INSERT INTO reviews_batch(id, day, tickets_json, cards_json, built_at, message)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              day = excluded.day,
              tickets_json = excluded.tickets_json,
              cards_json = excluded.cards_json,
              built_at = excluded.built_at,
              message = excluded.message
            """,
            (
                day,
                _json.dumps(tickets, ensure_ascii=False),
                _json.dumps(cards, ensure_ascii=False),
                at,
                message,
            ),
        )
        await self.conn.commit()
