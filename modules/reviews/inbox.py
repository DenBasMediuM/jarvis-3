"""Cloudflare inbox: результаты звонков и снимки рейтинга Google с витрины."""

from __future__ import annotations

from typing import Any

import httpx

from modules.reviews.branches import BRANCH_IDS, CALL_OUTCOMES


class ReviewsInboxClient:
    def __init__(self, base_url: str, *, write_key: str = "", read_key: str = "") -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.write_key = write_key or ""
        self.read_key = read_key or ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.read_key)

    async def fetch_inbox(self) -> list[dict[str, Any]]:
        if not self.configured:
            return []
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{self.base_url}/inbox",
                headers={"Authorization": f"Bearer {self.read_key}"},
            )
            r.raise_for_status()
            data = r.json()
            items = data.get("items") if isinstance(data, dict) else None
            return list(items) if isinstance(items, list) else []

    async def ack(self, ids: list[str]) -> None:
        if not self.configured or not ids:
            return
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{self.base_url}/inbox/ack",
                headers={
                    "Authorization": f"Bearer {self.read_key}",
                    "Content-Type": "application/json",
                },
                json={"ids": ids},
            )
            r.raise_for_status()


def normalize_phone(raw: str | None) -> str:
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(digits) >= 10:
        return digits[-10:]
    return digits


def validate_call_payload(body: dict[str, Any]) -> dict[str, Any]:
    ticket = str(body.get("ticket") or "").strip()
    outcome = str(body.get("outcome") or "").strip()
    if not ticket.isdigit() or len(ticket) < 4:
        raise ValueError("bad_ticket")
    if outcome not in CALL_OUTCOMES:
        raise ValueError("bad_outcome")
    comment = str(body.get("comment") or "").strip()[:2000] or None
    if outcome == "unhappy" and not comment:
        raise ValueError("comment_required")
    return {
        "ticket": ticket,
        "outcome": outcome,
        "comment": comment,
        "manager": str(body.get("manager") or "").strip()[:80] or None,
        "phone": normalize_phone(body.get("phone")),
        "client_name": str(body.get("client_name") or "").strip()[:120] or None,
        "device": str(body.get("device") or "").strip()[:120] or None,
        "branch_id": str(body.get("branch_id") or "").strip() or None,
        "issued_at": str(body.get("issued_at") or "").strip()[:32] or None,
        "repair_days": body.get("repair_days"),
    }


def validate_google_stats_payload(body: dict[str, Any]) -> dict[str, Any]:
    day = str(body.get("day") or "").strip()[:10]
    if len(day) < 8:
        raise ValueError("bad_day")
    manager = str(body.get("manager") or "").strip()[:80] or None
    raw_branches = body.get("branches")
    if not isinstance(raw_branches, list) or len(raw_branches) < 1:
        raise ValueError("bad_branches")
    branches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_branches:
        if not isinstance(item, dict):
            continue
        bid = str(item.get("id") or "").strip()
        if bid not in BRANCH_IDS or bid in seen:
            continue
        try:
            rating = float(item.get("rating"))
            count = int(item.get("review_count"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"bad_stats:{bid}") from exc
        if not (1.0 <= rating <= 5.0) or count < 0:
            raise ValueError(f"bad_stats:{bid}")
        seen.add(bid)
        branches.append({"id": bid, "rating": rating, "review_count": count})
    if len(seen) < len(BRANCH_IDS):
        raise ValueError("need_all_branches")
    return {"day": day, "manager": manager, "branches": branches}
