"""Экспорт снимка «КПД мастеров» для GitHub Pages."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import ROOT


def build_masters_kpi_pages_payload(stats: dict[str, Any]) -> dict[str, Any]:
    masters = stats.get("masters") or []
    weeks = stats.get("weeks") or []
    charts = stats.get("charts") or {}
    return {
        "title": "КПД мастеров",
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "masters": masters,
        "weeks": weeks,
        "charts": charts,
        "sync": {
            "finished_at": (stats.get("sync") or {}).get("finished_at"),
            "message": (stats.get("sync") or {}).get("message"),
        },
        "counts": {
            "masters": len(masters),
            "weeks": len(weeks),
        },
    }


def write_masters_kpi_pages_json(
    payload: dict[str, Any],
    path: Path | None = None,
) -> Path:
    out = path or (ROOT / "docs" / "masters-kpi" / "data.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
