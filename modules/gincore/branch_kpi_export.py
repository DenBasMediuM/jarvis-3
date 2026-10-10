"""Экспорт снимка «КПД филиалов» для GitHub Pages."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import ROOT
from modules.gincore.branch_kpi import BRANCHES, build_branch_kpi_charts


def default_pages_json_path() -> Path:
    return ROOT / "docs" / "branch-kpi" / "data.json"


def build_branch_kpi_pages_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    months = [
        {
            "year": int(r["year"]),
            "month": int(r["month"]),
            "branch_id": r["branch_id"],
            "acceptances": r.get("acceptances"),
            "gross_profit": r.get("gross_profit"),
            "net_profit": r.get("net_profit"),
            "expense": r.get("expense"),
            "refusals": r.get("refusals"),
            "return_rate": r.get("return_rate"),
        }
        for r in rows
    ]
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "title": "КПД филиалов",
        "branches": [
            {
                "id": b["id"],
                "title": b["title"],
                "color": b["color"],
                "crm_branch_id": b["crm_branch_id"],
            }
            for b in BRANCHES
        ],
        "months": months,
        "charts": build_branch_kpi_charts(months),
        "counts": {
            "months": len({(m["year"], m["month"]) for m in months}),
            "rows": len(months),
        },
    }


def write_branch_kpi_pages_json(
    payload: dict[str, Any],
    path: Path | None = None,
) -> Path:
    out = path or default_pages_json_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return out
