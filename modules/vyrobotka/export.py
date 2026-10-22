"""Экспорт снимка «Выработка» в JSON для GitHub Pages."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import ROOT
from modules.vyrobotka.decisions import DECISION_CODES

_SHEET_KEYS = (
    "sheet_title",
    "sort_ym",
    "sort_a",
    "sort_b",
    "tickets_count",
    "report_sum",
    "upsell_sum",
    "upsell_count",
    "avg_upsell",
    "upsell_ratio",
)

_DEBT_TABLE_KEYS = (
    "ticket",
    "sheet_title",
    "master",
    "sheet_debt",
    "sheet_total",
    "sheet_paid",
    "crm_debt",
    "crm_paid",
    "crm_total",
    "crm_status",
    "crm_url",
    "report_amount",
    "salary",
    "flag",
    "flag_reason",
    "sheet_url",
    "crm_feed_at",
    "on_pay_list",
    "decision_status",
    "decision_code",
    "decision_by",
    "decision_at",
)

_DEBT_DAILY_KEYS = (
    "day",
    "crm_debt_sum",
    "sheets_debt_sum",
    "crm_orders",
    "sheets_tickets",
    "source",
    "updated_at",
)


def default_pages_json_path() -> Path:
    return ROOT / "docs" / "vyrobotka" / "data.json"


def _pick(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: row.get(k) for k in keys if k in row or row.get(k) is not None}


def _parse_feed(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("live_feed")
    if isinstance(raw, list):
        return [
            {
                "date": str(x.get("date") or ""),
                "author": str(x.get("author") or ""),
                "text": str(x.get("text") or ""),
            }
            for x in raw
            if isinstance(x, dict)
        ]
    blob = row.get("crm_feed_json")
    if not blob:
        return []
    try:
        parsed = json.loads(blob) if isinstance(blob, str) else blob
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [
        {
            "date": str(x.get("date") or ""),
            "author": str(x.get("author") or ""),
            "text": str(x.get("text") or ""),
        }
        for x in parsed
        if isinstance(x, dict)
    ]


def sanitize_debt_table_row(row: dict[str, Any]) -> dict[str, Any]:
    """Строка ledger для витрины (как в админке + кэш ленты CRM)."""
    out = _pick(row, _DEBT_TABLE_KEYS)
    out["live_feed"] = _parse_feed(row)
    return out


def debt_table_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"total": len(rows), "red": 0, "yellow": 0, "open": 0, "mismatch": 0}
    for r in rows:
        f = str(r.get("flag") or "")
        if f in counts:
            counts[f] += 1
    return counts


def build_vyrobotka_pages_payload(
    *,
    upsell_sheets: list[dict[str, Any]],
    debt_table: list[dict[str, Any]] | None = None,
    debt_daily: list[dict[str, Any]] | None = None,
    debt_baseline: dict[str, Any] | None = None,
    debt_verify_message: str | None = None,
    sync: dict[str, Any] | None = None,
    spreadsheet_title: str | None = None,
    debt_inbox: dict[str, Any] | None = None,
    # legacy kwargs — игнорируем, чтобы не ломать старые вызовы
    debt_sheets: list[dict[str, Any]] | None = None,
    debt_tickets: list[dict[str, Any]] | None = None,
    verify_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    del debt_sheets, debt_tickets, verify_rows  # unused legacy
    raw_rows = list(debt_table or [])
    pending_n = sum(1 for r in raw_rows if r.get("decision_status") == "pending")
    rework_n = sum(1 for r in raw_rows if r.get("decision_status") == "rework")
    # closed уже отфильтрованы active=0; pending/rework оставляем — витрина
    # прячет pending из основной таблицы, но открывает блок через KPI
    table = [
        sanitize_debt_table_row(r)
        for r in raw_rows
        if str(r.get("decision_status") or "") != "closed"
    ]
    work_rows = [r for r in table if r.get("decision_status") != "pending"]
    counts = debt_table_counts(work_rows)
    counts["pending"] = pending_n
    counts["rework"] = rework_n
    counts["total"] = len(work_rows)
    daily = [_pick(d, _DEBT_DAILY_KEYS) for d in (debt_daily or [])]
    baseline = None
    if debt_baseline:
        baseline = {
            "day": debt_baseline.get("day"),
            "sheets_debt_sum": debt_baseline.get("sheets_debt_sum"),
            "sheets_tickets": debt_baseline.get("sheets_tickets"),
        }
    live_msg = (
        f"В таблице {counts['total']} "
        f"(жёлтых {counts['yellow']}, красных {counts['red']}, "
        f"open {counts['open']}, mismatch {counts['mismatch']})"
    )
    inbox = dict(debt_inbox or {})
    inbox.setdefault("decision_codes", dict(DECISION_CODES))
    return {
        "schema_version": 2,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": "jarvis-vyrobotka",
        "spreadsheet_title": spreadsheet_title,
        "sync": {
            "finished_at": (sync or {}).get("finished_at"),
            "message": (sync or {}).get("message"),
            "status": (sync or {}).get("status"),
        },
        "upsell_sheets": [_pick(s, _SHEET_KEYS) for s in upsell_sheets],
        "debt_table": table,
        "debt_table_counts": counts,
        "debt_daily": daily,
        "debt_baseline": baseline,
        "debt_verify_message": live_msg or debt_verify_message,
        "debt_inbox": inbox,
        "counts": {
            "upsell_sheets": len(upsell_sheets),
            "debt_table": len(table),
            "debt_daily": len(daily),
            "pending": pending_n,
            "rework": rework_n,
        },
    }


def write_vyrobotka_pages_json(payload: dict[str, Any], path: Path | None = None) -> Path:
    target = path or default_pages_json_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
