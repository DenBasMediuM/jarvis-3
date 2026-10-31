"""Экспорт снимка «Качество обработки буфера» для GitHub Pages."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import ROOT


def default_pages_json_path() -> Path:
    return ROOT / "docs" / "buffer-quality" / "data.json"


def build_buffer_quality_pages_payload(stats: dict[str, Any]) -> dict[str, Any]:
    """Снимок для витрины из ответа get_stats()."""
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "title": stats.get("title") or "Качество обработки буфера",
        "latest": stats.get("latest"),
        "live": stats.get("live"),
        "masters": stats.get("masters") or [],
        "masters_snapshot": stats.get("masters_snapshot") or [],
        "daily": stats.get("daily") or [],
        "assign_history": stats.get("assign_history") or [],
        "series": stats.get("series") or {},
        "sync": stats.get("sync"),
        "counts": {
            "masters": len(stats.get("masters") or []),
            "days": len(stats.get("daily") or []),
        },
    }


def write_buffer_quality_pages_json(
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
