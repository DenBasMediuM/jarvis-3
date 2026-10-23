"""Снимок витрины docs/reviews/data.json."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import ROOT
from modules.reviews.branches import (
    CALL_OUTCOMES,
    DEFAULT_CALL_SCRIPT,
    branches_public,
)


def default_pages_path() -> Path:
    return ROOT / "docs" / "reviews" / "data.json"


def build_reviews_pages_payload(
    *,
    batch: dict[str, Any] | None,
    cards: list[dict[str, Any]],
    inbox: dict[str, Any] | None = None,
    google_latest: list[dict[str, Any]] | None = None,
    queue_size: int = 10,
) -> dict[str, Any]:
    inbox_out = dict(inbox or {})
    return {
        "schema_version": 2,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": "jarvis-reviews",
        "branches": branches_public(),
        "outcomes": dict(CALL_OUTCOMES),
        "call_script": dict(DEFAULT_CALL_SCRIPT),
        "inbox": inbox_out,
        "queue_size": int(queue_size),
        "batch": batch or {"day": None, "tickets": [], "cards": []},
        "cards": cards,
        "google_latest": google_latest or [],
        "counts": {
            "pool": len(cards),
            "batch": len(cards),
            "queue_size": int(queue_size),
            "branches": len(branches_public()),
        },
    }


def write_reviews_pages(payload: dict[str, Any], path: Path | None = None) -> Path:
    out = path or default_pages_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out
