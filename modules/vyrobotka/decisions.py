"""Решения по дебиторке: коды, CF inbox, применение в ledger."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

DECISION_CODES = {
    "mgmt_ok": "закрыть с разрешения руководства",
    "paid_fact": "оплата по факту была",
    "no_pay": "оплаты не было и не будет",
}


def decision_label(code: str | None) -> str:
    if not code:
        return "—"
    return DECISION_CODES.get(str(code), str(code))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DebtInboxClient:
    def __init__(self, base_url: str, *, write_key: str = "", read_key: str = "") -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.write_key = write_key or ""
        self.read_key = read_key or ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.read_key)

    @property
    def write_configured(self) -> bool:
        return bool(self.base_url and self.write_key)

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


async def apply_decision_to_ledger(
    db: Any,
    ticket: str,
    decision_code: str,
    *,
    decision_by: str | None = None,
    decision_at: str | None = None,
) -> dict[str, Any]:
    code = str(decision_code or "").strip()
    if code not in DECISION_CODES:
        raise ValueError(f"Неизвестный код решения: {code}")
    oid = str(ticket or "").strip()
    row = await db.vyrobotka_get_debt_ledger_ticket(oid)
    if not row or not int(row.get("active") or 0):
        raise ValueError(f"Квитанция №{oid} не в активной дебиторке")
    updated = await db.vyrobotka_set_debt_decision(
        oid,
        decision_status="pending",
        decision_code=code,
        decision_by=(decision_by or "").strip() or None,
        decision_at=decision_at or _now(),
        clear_moderation=True,
    )
    return updated or {}


async def moderate_decision(
    db: Any,
    ticket: str,
    action: str,
    *,
    moderated_by: str | None = None,
) -> dict[str, Any]:
    oid = str(ticket or "").strip()
    act = str(action or "").strip().casefold()
    row = await db.vyrobotka_get_debt_ledger_ticket(oid)
    if not row:
        raise ValueError(f"Квитанция №{oid} не найдена")
    if str(row.get("decision_status") or "") != "pending":
        raise ValueError("Нет решения, ожидающего модерации")
    who = (moderated_by or "").strip() or "admin"
    if act in {"approve", "одобрить"}:
        closed = await db.vyrobotka_close_debt_ticket(oid, moderated_by=who)
        return {"ok": True, "action": "approve", "closed": closed}
    if act in {"rework", "доработать"}:
        updated = await db.vyrobotka_set_debt_decision(
            oid,
            decision_status="rework",
            decision_code=None,
            decision_by=None,
            decision_at=None,
            moderated_by=who,
            moderated_at=_now(),
        )
        return {"ok": True, "action": "rework", "ledger": updated}
    raise ValueError("action: approve | rework")


async def ingest_cloudflare_inbox(db: Any, client: DebtInboxClient) -> dict[str, Any]:
    """Забрать решения из CF KV и пометить pending. Идемпотентно по последнему decision_at."""
    if not client.configured:
        return {"ok": True, "skipped": True, "applied": 0}
    items = await client.fetch_inbox()
    applied = 0
    errors: list[str] = []
    ack_ids: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        iid = str(item.get("id") or "")
        ticket = str(item.get("ticket") or "").strip()
        code = str(item.get("decision_code") or "").strip()
        try:
            await apply_decision_to_ledger(
                db,
                ticket,
                code,
                decision_by=item.get("decision_by"),
                decision_at=item.get("at"),
            )
            applied += 1
            if iid:
                ack_ids.append(iid)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{ticket or iid}: {exc}")
            # чужой/закрытый ticket — всё равно ack, чтобы не крутить вечно
            if iid and ("не в активной" in str(exc) or "Неизвестный" in str(exc)):
                ack_ids.append(iid)
    if ack_ids:
        await client.ack(ack_ids)
    return {
        "ok": True,
        "fetched": len(items),
        "applied": applied,
        "acked": len(ack_ids),
        "errors": errors[:20],
    }
