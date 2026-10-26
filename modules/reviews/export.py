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
    google_series: dict[str, Any] | None = None,
    calls_series: dict[str, Any] | None = None,
    outcome_counts: dict[str, int] | None = None,
    managers: list[dict[str, Any]] | None = None,
    calls_total: int = 0,
    will_review_rate: float = 0,
    queue_size: int = 10,
) -> dict[str, Any]:
    inbox_out = dict(inbox or {})
    return {
        "schema_version": 3,
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
        "google_series": google_series or {"days": [], "by_branch": {}},
        "calls_series": calls_series or {"days": [], "total": [], "by_manager": {}},
        "outcome_counts": outcome_counts or {k: 0 for k in CALL_OUTCOMES},
        "managers": managers or [],
        "calls_total": int(calls_total),
        "will_review_rate": float(will_review_rate or 0),
        "counts": {
            "pool": len(cards),
            "batch": len(cards),
            "queue_size": int(queue_size),
            "branches": len(branches_public()),
            "calls": int(calls_total),
        },
    }


def write_reviews_pages(payload: dict[str, Any], path: Path | None = None) -> Path:
    out = path or default_pages_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out
