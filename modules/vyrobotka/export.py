"""Экспорт снимка «Выработка» в JSON для GitHub Pages."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import ROOT
from modules.vyrobotka.verify import apply_display_verdicts, build_verify_report

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

_DEBT_SHEET_KEYS = (
    "sheet_title",
    "sort_ym",
    "sort_a",
    "sort_b",
    "tickets_count",
    "debt_sum",
    "debt_count",
    "debt_ratio",
    "avg_debt",
)

_TICKET_KEYS = (
    "sheet_title",
    "master",
    "ticket",
    "total_repair",
    "paid",
    "debt",
    "status",
    "control",
    "arith_check",
)


def default_pages_json_path() -> Path:
    return ROOT / "docs" / "vyrobotka" / "data.json"


def _pick(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: row.get(k) for k in keys if k in row or row.get(k) is not None}


def sanitize_ticket_for_pages(row: dict[str, Any]) -> dict[str, Any]:
    out = _pick(row, _TICKET_KEYS)
    verify = row.get("verify")
    if isinstance(verify, dict):
        out["verify"] = {
            "verdict": verify.get("verdict"),
            "summary": verify.get("summary"),
            "field_diffs": verify.get("field_diffs") or {},
            "crm_total": verify.get("crm_total"),
            "crm_paid": verify.get("crm_paid"),
            "crm_debt": verify.get("crm_debt"),
            "crm_status": verify.get("crm_status"),
            "crm_url": verify.get("crm_url"),
        }
    return out


_DEBT_DAILY_KEYS = (
    "day",
    "crm_debt_sum",
    "sheets_debt_sum",
    "crm_orders",
    "sheets_tickets",
    "source",
    "updated_at",
)


def build_vyrobotka_pages_payload(
    *,
    upsell_sheets: list[dict[str, Any]],
    debt_sheets: list[dict[str, Any]],
    debt_tickets: list[dict[str, Any]],
    sync: dict[str, Any] | None = None,
    spreadsheet_title: str | None = None,
    verify_rows: list[dict[str, Any]] | None = None,
    debt_daily: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    display_rows = apply_display_verdicts(verify_rows or [])
    report = build_verify_report(display_rows) if display_rows else None
    daily = [_pick(d, _DEBT_DAILY_KEYS) for d in (debt_daily or [])]
    return {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": "jarvis-vyrobotka",
        "spreadsheet_title": spreadsheet_title,
        "sync": {
            "finished_at": (sync or {}).get("finished_at"),
            "message": (sync or {}).get("message"),
            "status": (sync or {}).get("status"),
        },
        "upsell_sheets": [_pick(s, _SHEET_KEYS) for s in upsell_sheets],
        "debt_sheets": [_pick(s, _DEBT_SHEET_KEYS) for s in debt_sheets],
        "debt_tickets": [sanitize_ticket_for_pages(t) for t in debt_tickets],
        "debt_daily": daily,
        "verify_report": report,
        "counts": {
            "upsell_sheets": len(upsell_sheets),
            "debt_sheets": len(debt_sheets),
            "debt_tickets": len(debt_tickets),
            "verify_rows": len(display_rows),
            "debt_daily": len(daily),
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
