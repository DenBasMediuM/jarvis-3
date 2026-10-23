"""Сервис сбора отзывов: батч кандидатов, ingest CF, экспорт витрины."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from core.config import settings as app_settings
from modules.reviews.branches import (
    CALL_OUTCOMES,
    DEFAULT_CALL_SCRIPT,
    branch_by_id,
    branches_public,
    guess_branch_id,
    outcome_label,
)
from modules.reviews.export import build_reviews_pages_payload, write_reviews_pages
from modules.reviews.inbox import (
    ReviewsInboxClient,
    normalize_phone,
    validate_call_payload,
    validate_google_stats_payload,
)

log = logging.getLogger(__name__)

GincoreFactory = Callable[[], Awaitable[Any]]

MAX_REPAIR_DAYS = 10
LOOKBACK_DAYS = 21
# Пул кандидатов в снимке; витрина сама держит «окно» из QUEUE_SIZE и доливает при обработке.
POOL_SIZE = 50
QUEUE_SIZE = 10


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return date.today().isoformat()


def _parse_day(raw: str | None) -> date | None:
    if not raw:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(raw))
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"(\d{2})[./](\d{2})[./](\d{4})", str(raw))
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


class ReviewsService:
    def __init__(
        self,
        db: Any,
        gincore_client_factory: GincoreFactory | None = None,
    ) -> None:
        self.db = db
        self._gincore_factory = gincore_client_factory

    def inbox_client(self) -> ReviewsInboxClient:
        return ReviewsInboxClient(
            app_settings.reviews_inbox_url or "",
            write_key=app_settings.reviews_inbox_write_key or "",
            read_key=app_settings.reviews_inbox_read_key or "",
        )

    async def get_stats(self) -> dict[str, Any]:
        calls = await self.db.reviews_list_calls(limit=1000)
        by_outcome: dict[str, int] = {k: 0 for k in CALL_OUTCOMES}
        by_manager: dict[str, dict[str, Any]] = {}
        for c in calls:
            oc = str(c.get("outcome") or "")
            if oc in by_outcome:
                by_outcome[oc] += 1
            mgr = str(c.get("manager") or "—")
            bucket = by_manager.setdefault(
                mgr,
                {"manager": mgr, "total": 0, "will_review": 0, "no_answer": 0, "wont_review": 0, "unhappy": 0},
            )
            bucket["total"] += 1
            if oc in bucket:
                bucket[oc] += 1
        for b in by_manager.values():
            t = b["total"] or 1
            b["will_review_rate"] = round(b["will_review"] / t, 3)
        batch = await self.db.reviews_get_batch()
        batch_out = None
        if batch:
            try:
                tickets = json.loads(batch.get("tickets_json") or "[]")
            except json.JSONDecodeError:
                tickets = []
            batch_out = {
                "day": batch.get("day"),
                "built_at": batch.get("built_at"),
                "message": batch.get("message"),
                "count": len(tickets) if isinstance(tickets, list) else 0,
            }
        google = await self.db.reviews_list_google_stats(limit=200)
        latest = await self.db.reviews_latest_google_stats()
        return {
            "ok": True,
            "outcomes": CALL_OUTCOMES,
            "outcome_counts": by_outcome,
            "managers": sorted(by_manager.values(), key=lambda x: (-x["total"], x["manager"])),
            "calls_total": len(calls),
            "calls": calls[:200],
            "batch": batch_out,
            "google_stats": google,
            "google_latest": latest,
            "branches": branches_public(),
            "inbox_configured": self.inbox_client().configured,
        }

    async def ingest_inbox(self) -> dict[str, Any]:
        client = self.inbox_client()
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
            kind = str(item.get("type") or item.get("kind") or "call")
            try:
                if kind in {"google_stats", "google"}:
                    payload = validate_google_stats_payload(item)
                    noted_at = str(item.get("at") or _now())
                    rows = [
                        {
                            "day": payload["day"],
                            "branch_id": b["id"],
                            "rating": b["rating"],
                            "review_count": b["review_count"],
                            "noted_by": payload.get("manager"),
                            "noted_at": noted_at,
                        }
                        for b in payload["branches"]
                    ]
                    await self.db.reviews_upsert_google_stats(rows)
                else:
                    payload = validate_call_payload(item)
                    phone_norm = payload.get("phone") or normalize_phone(payload.get("phone"))
                    await self.db.reviews_insert_call(
                        {
                            **payload,
                            "phone_norm": phone_norm,
                            "called_at": str(item.get("at") or _now()),
                            "source": "cf",
                        }
                    )
                applied += 1
                if iid:
                    ack_ids.append(iid)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{iid or kind}: {exc}")
                if iid and ("bad_" in str(exc) or "need_" in str(exc)):
                    ack_ids.append(iid)
        if ack_ids:
            await client.ack(ack_ids)
        if applied:
            await self._safe_export()
        return {
            "ok": True,
            "fetched": len(items),
            "applied": applied,
            "acked": len(ack_ids),
            "errors": errors[:20],
        }

    async def build_batch(self, *, force: bool = False) -> dict[str, Any]:
        today = _today()
        existing = await self.db.reviews_get_batch()
        if existing and not force and existing.get("day") == today:
            try:
                cards = json.loads(existing.get("cards_json") or "[]")
            except json.JSONDecodeError:
                cards = []
            if isinstance(cards, list) and cards:
                return {
                    "ok": True,
                    "skipped": True,
                    "day": today,
                    "count": len(cards),
                    "message": existing.get("message"),
                }

        if not self._gincore_factory:
            raise RuntimeError("Gincore не настроен")
        client = await self._gincore_factory()
        date_to = date.today()
        date_from = date_to - timedelta(days=LOOKBACK_DAYS)
        result = await client.repair_orders(
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
            filters={"date_type": "issued"},
            group_by="list",
            max_sample=400,
        )
        orders = list(result.get("orders") or result.get("sample") or [])
        if not orders and isinstance(result.get("groups"), list):
            for g in result["groups"]:
                if isinstance(g, dict):
                    orders.extend(g.get("orders") or [])

        called_phones = await self.db.reviews_called_phones()
        called_tickets = await self.db.reviews_called_tickets()
        candidates: list[dict[str, Any]] = []
        seen_phones: set[str] = set()

        for o in orders:
            ticket = str(o.get("id") or o.get("ticket") or "").strip()
            if not ticket.isdigit() or ticket in called_tickets:
                continue
            # accepted_at в списке CRM — это имя приёмщика, не дата; срок ремонта считаем после enrich
            phone_raw = str(o.get("phone") or o.get("client_phone") or "")
            phone_norm = normalize_phone(phone_raw) if phone_raw else ""
            if phone_norm and (phone_norm in called_phones or phone_norm in seen_phones):
                continue
            if phone_norm:
                seen_phones.add(phone_norm)
            branch_id = guess_branch_id(str(o.get("location") or ""))
            candidates.append(
                {
                    "ticket": ticket,
                    "client_name": str(o.get("client") or "")[:120] or None,
                    "device": str(o.get("device") or "")[:120] or None,
                    "status": str(o.get("status") or "")[:80] or None,
                    "location": str(o.get("location") or "")[:80] or None,
                    "branch_id": branch_id,
                    "phone": phone_raw or None,
                    "phone_norm": phone_norm or None,
                }
            )
            if len(candidates) >= POOL_SIZE * 2:
                break

        # Обогатить пул (телефон, лента, срок ремонта ≤ MAX_REPAIR_DAYS).
        # Уже прозвоненные ticket/phone из reviews_calls не попадают в пул.
        cards: list[dict[str, Any]] = []
        for cand in candidates:
            if len(cards) >= POOL_SIZE:
                break
            try:
                card = await self._enrich_card(client, cand)
            except Exception as exc:  # noqa: BLE001
                log.warning("reviews enrich %s: %s", cand.get("ticket"), exc)
                continue
            if card is None:
                continue
            pn = card.get("phone_norm") or normalize_phone(card.get("phone"))
            if pn and (pn in called_phones or any(c.get("phone_norm") == pn for c in cards)):
                continue
            if not pn and not card.get("phone"):
                continue
            if pn:
                card["phone_norm"] = pn
            cards.append(card)

        tickets = [str(c["ticket"]) for c in cards]
        msg = (
            f"Пул {today}: {len(cards)} кандидатов "
            f"(витрина держит {QUEUE_SIZE} в очереди; окно {LOOKBACK_DAYS}д, ремонт ≤{MAX_REPAIR_DAYS}д)"
        )
        await self.db.reviews_set_batch(day=today, tickets=tickets, cards=cards, message=msg)
        await self._safe_export()
        return {
            "ok": True,
            "day": today,
            "count": len(cards),
            "queue_size": QUEUE_SIZE,
            "message": msg,
            "tickets": tickets,
        }

    async def _enrich_card(self, client: Any, cand: dict[str, Any]) -> dict[str, Any] | None:
        from modules.gincore.quality import parse_order_page_meta

        ticket = str(cand["ticket"])
        html = await client.fetch_order_html(ticket)
        feed: list[dict[str, Any]] = []
        try:
            feed = client.parse_order_live_feed(html) or []
        except Exception:  # noqa: BLE001
            feed = []
        pay: dict[str, Any] = {}
        try:
            pay = client.parse_order_payment(html) or {}
        except Exception:  # noqa: BLE001
            pay = {}
        meta = parse_order_page_meta(html)
        accepted = _parse_day(meta.get("accepted_at"))
        issued = None
        for ev in feed if isinstance(feed, list) else []:
            blob = f"{ev.get('text') or ''} {ev.get('status') or ''}".casefold()
            if "выдач" in blob or "выдан" in blob:
                issued = _parse_day(ev.get("date"))
                if issued:
                    break
        if not issued:
            issued = date.today()
        repair_days = None
        if accepted:
            repair_days = (issued - accepted).days
            if repair_days < 0:
                repair_days = None
            elif repair_days > MAX_REPAIR_DAYS:
                return None
        phone = cand.get("phone")
        client_name = cand.get("client_name")
        if not phone:
            m = re.search(r"(?:\+?38)?0\d{9}", html)
            if m:
                phone = m.group(0)
        if not client_name:
            m = re.search(
                r"(?:Клиент|Заказчик)\s*[:：]\s*([^\n<]{2,80})",
                html,
                re.I,
            )
            if m:
                client_name = m.group(1).strip()[:120]
        base = getattr(client, "base_url", "") or app_settings.default_gincore_base_url
        crm_url = f"{base.rstrip('/')}/orders#edit_order_form?id={ticket}&kind=repair"
        branch_id = cand.get("branch_id") or guess_branch_id(cand.get("location"))
        return {
            **cand,
            "phone": phone,
            "phone_norm": normalize_phone(phone),
            "client_name": client_name,
            "accepted_at": accepted.isoformat() if accepted else None,
            "issued_at": issued.isoformat() if issued else None,
            "repair_days": repair_days,
            "live_feed": feed[:40] if isinstance(feed, list) else [],
            "crm_total": pay.get("repair_cost") or pay.get("total_with_discount"),
            "crm_paid": pay.get("paid"),
            "crm_debt": pay.get("due"),
            "crm_url": crm_url,
            "branch_id": branch_id,
            "branch_name": (branch_by_id(branch_id) or {}).get("name") if branch_id else None,
            "review_url": (branch_by_id(branch_id) or {}).get("review_url") if branch_id else None,
        }

    async def get_card(self, ticket: str) -> dict[str, Any]:
        batch = await self.db.reviews_get_batch()
        if batch:
            try:
                cards = json.loads(batch.get("cards_json") or "[]")
            except json.JSONDecodeError:
                cards = []
            for c in cards if isinstance(cards, list) else []:
                if str(c.get("ticket")) == str(ticket):
                    return {"ok": True, "card": c}
        if not self._gincore_factory:
            raise ValueError("Нет карточки и Gincore недоступен")
        client = await self._gincore_factory()
        card = await self._enrich_card(client, {"ticket": str(ticket)})
        return {"ok": True, "card": card}

    async def export_pages_snapshot(self, path: str | None = None) -> dict[str, Any]:
        batch_row = await self.db.reviews_get_batch()
        day = None
        tickets: list[str] = []
        cards: list[dict[str, Any]] = []
        if batch_row:
            day = batch_row.get("day")
            try:
                tickets = json.loads(batch_row.get("tickets_json") or "[]")
                cards = json.loads(batch_row.get("cards_json") or "[]")
            except json.JSONDecodeError:
                tickets, cards = [], []
        inbox = self.inbox_client()
        payload = build_reviews_pages_payload(
            batch={"day": day, "tickets": tickets, "built_at": (batch_row or {}).get("built_at")},
            cards=cards if isinstance(cards, list) else [],
            inbox={
                "url": inbox.base_url or None,
                "write_key": app_settings.reviews_inbox_write_key or None,
            },
            google_latest=await self.db.reviews_latest_google_stats(),
            queue_size=QUEUE_SIZE,
        )
        # call_script уже в builder
        out = write_reviews_pages(payload, path=path)  # type: ignore[arg-type]
        return {
            "ok": True,
            "path": str(out),
            "batch": len(cards) if isinstance(cards, list) else 0,
            "exported_at": payload["exported_at"],
        }

    async def publish_pages_snapshot(self) -> dict[str, Any]:
        import asyncio

        from core.pages_publish import publish_docs_files

        exported = await self.export_pages_snapshot()
        published = await asyncio.to_thread(
            publish_docs_files,
            [
                "docs/reviews/data.json",
                "docs/reviews/index.html",
                "docs/reviews/app.js",
                "docs/reviews/styles.css",
            ],
            message="chore(reviews): обновить снимок витрины сбора отзывов",
        )
        return {"ok": True, "export": exported, "publish": published}

    async def _safe_export(self) -> None:
        try:
            await self.export_pages_snapshot()
        except Exception:  # noqa: BLE001
            log.exception("reviews export failed")
