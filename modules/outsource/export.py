"""Экспорт снимка «Аутсорс мастера» для GitHub Pages (без контактов — они только в облаке)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import ROOT


def default_pages_json_path() -> Path:
    return ROOT / "docs" / "outsource" / "data.json"


def build_outsource_pages_payload(snap: dict[str, Any], *, sync: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": "jarvis-outsource",
        "generated_at": snap.get("generated_at"),
        "today": snap.get("today"),
        "window": snap.get("window") or {},
        "engineers": snap.get("engineers") or [],
        "outsourcers": snap.get("outsourcers") or {},
        "trials": snap.get("trials") or {},
        "history_orders": snap.get("history_orders") or 0,
        "warnings": snap.get("warnings") or [],
        "sync": sync,
    }


def write_outsource_pages_json(payload: dict[str, Any], path: Path | None = None) -> Path:
    out = path or default_pages_json_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
