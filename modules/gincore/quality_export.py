"""Экспорт снимка качества в JSON для GitHub Pages."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import ROOT

# Поля заказа, нужные публичной витрине (без ленты и ПДн клиента).
_ORDER_KEYS = (
    "order_id",
    "status",
    "engineer",
    "master_name",
    "device",
    "url",
    "accepted_at",
    "has_feed",
    "feed_synced_at",
    "total_days",
    "wait_master_days",
    "diag_days",
    "agreement_source",
    "rework_count",
    "rework_kpi",
    "rework_diag_days",
    "rework_repair_days",
    "rework_total_days",
    "rework_last_accepted_at",
    "last_rework_at",
    "calls_kpi",
    "calls_inbound_ok",
    "calls_inbound_fail",
    "calls_inbound",
    "calls_outbound_ok",
    "calls_outbound_fail",
    "calls_missed",
    "calls_missed_total",
    "calls_missed_unrecovered",
    "calls_missed_recovered",
    "calls_pre_inbound_ok",
    "calls_pre_miss_same_day",
    "calls_pre_miss_before_visit",
    "calls_pre_miss_until_visit",
    "callback_same_day",
    "order_kpi",
    "order_kpi_parts",
    "manager_no_answer_missed",
    "is_closed",
    "is_ready",
    "closed_at",
    "ready_at",
    "as_of",
)


def default_pages_json_path() -> Path:
    return ROOT / "docs" / "quality" / "data.json"


def sanitize_order_for_pages(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _ORDER_KEYS:
        if key in row:
            out[key] = row[key]
    # Ленту на Pages не отдаём — колонка «Лента» будет read-only заглушкой.
    out["has_feed"] = False
    out.pop("feed", None)
    return out


def build_quality_pages_payload(
    *,
    orders: list[dict[str, Any]],
    daily_stats: list[dict[str, Any]],
    analysis: dict[str, Any] | None,
    sync: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": "jarvis-quality",
        "sync": {
            "finished_at": (sync or {}).get("finished_at"),
            "message": (sync or {}).get("message"),
            "status": (sync or {}).get("status"),
        },
        "orders": [sanitize_order_for_pages(o) for o in orders],
        "daily_stats": list(daily_stats or []),
        "analysis": analysis,
        "counts": {
            "orders": len(orders),
            "daily_stats": len(daily_stats or []),
        },
    }


def write_quality_pages_json(payload: dict[str, Any], path: Path | None = None) -> Path:
    target = path or default_pages_json_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
