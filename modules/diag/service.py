"""Сервис «Платная диагностика»: кандидаты и статусы квитанций → облако.

Записи менеджера (что взял, с каким мастером консультировался, что предложил клиенту, итог) —
в Worker jarvis-feedback (D1). Jarvis раз в пересборку: берёт рабочие заказы из кэша «Качества»
(буфер и ещё не продиагностированные), историю ремонтов из «Постоянных клиентов» (доля «без ремонта»
по категориям) и отправляет в облако кандидатов и статусы квитанций из записей (оплачено ли).
Gincore запрашивается только для квитанций записей, которых нет ни в одном кэше.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable

from modules.diag.compute import CATEGORY_LABELS, category_stats, find_candidates, ticket_info

log = logging.getLogger(__name__)

SYNC_KEY = "diag_sync"
SUMMARY_KEY = "diag_summary"
HISTORY_KEYS = ("clients_history_v2", "outsource_history")
MAX_FETCH = 40


class DiagService:
    def __init__(
        self,
        db: Any,
        *,
        quality_service: Any,
        gincore_client_factory: Callable[[], Awaitable[Any]],
        feedback_client_factory: Callable[[], Any],
    ) -> None:
        self.db = db
        self.quality_service = quality_service
        self._client_factory = gincore_client_factory
        self._feedback_factory = feedback_client_factory
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def get_sync_state(self) -> dict[str, Any]:
        st = await self.db.get_setting(SYNC_KEY, None) or {}
        return {
            "status": st.get("status") or "idle",
            "message": st.get("message"),
            "started_at": st.get("started_at"),
            "finished_at": st.get("finished_at"),
            "done": int(st.get("done") or 0),
            "total": int(st.get("total") or 0),
        }

    async def _set_sync(self, **fields: Any) -> None:
        st = await self.db.get_setting(SYNC_KEY, None) or {}
        st.update(fields)
        await self.db.set_setting(SYNC_KEY, st)

    async def get_stats(self) -> dict[str, Any]:
        """Сводка для админки: живые записи из облака + последняя синхронизация."""
        summary = await self.db.get_setting(SUMMARY_KEY, None) or {}
        live: dict[str, Any] = {"ok": False}
        fb = self._feedback_factory()
        if getattr(fb, "configured", False):
            try:
                st = await fb.get_diag_state()
                live = {"ok": True, "cases": st.get("cases") or [], "plan": st.get("plan")}
            except Exception as exc:  # noqa: BLE001
                live = {"ok": False, "error": str(exc)}
        else:
            live = {"ok": False, "error": "облако «Улучшения» не настроено"}
        return {"ok": True, **summary, "live": live, "sync": await self.get_sync_state()}

    async def sync(self) -> dict[str, Any]:
        async with self._lock:
            if self._task and not self._task.done():
                return {"ok": True, "started": False, "sync": await self.get_sync_state()}
            await self._set_sync(
                status="running",
                message="Старт…",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at=None,
                done=0,
                total=0,
            )
            self._task = asyncio.create_task(self._run_sync())
            return {"ok": True, "started": True, "sync": await self.get_sync_state()}

    async def _history_rows(self) -> list[dict[str, Any]]:
        for key in HISTORY_KEYS:
            cache = await self.db.get_setting(key, None) or {}
            months = cache.get("months") or {}
            rows = [r for m in months.values() for r in (m.get("rows") or [])]
            if rows:
                return rows
        return []

    async def _run_sync(self) -> None:
        client = None
        warnings: list[str] = []
        try:
            today = date.today()
            fb = self._feedback_factory()
            if not getattr(fb, "configured", False):
                raise RuntimeError("облако «Улучшения» не настроено (JARVIS_FEEDBACK_URL / ADMIN_KEY)")
            await self._set_sync(message="Записи менеджера из облака…")
            state = await fb.get_diag_state()
            cases = list(state.get("cases") or [])
            taken = {str(c.get("ticket")) for c in cases if c.get("ticket")}

            await self._set_sync(message="Рабочие заказы из Качества…")
            working: list[dict[str, Any]] = []
            if self.quality_service is not None:
                working = list((await self.quality_service.list_rows()).get("orders") or [])
            feeds: dict[str, list[dict[str, Any]]] = {}
            try:
                for r in await self.db.quality_list_orders():
                    try:
                        feeds[str(r.get("order_id"))] = json.loads(r.get("feed_json") or "[]")
                    except (TypeError, ValueError):
                        pass
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"ленты заказов: {exc}")
            for o in working:
                o["feed"] = feeds.get(str(o.get("order_id")), [])
            if not working:
                warnings.append("кэш Качества пуст — сначала «Качество из CRM»")

            history = await self._history_rows()
            if not history:
                warnings.append("нет истории ремонтов — доля «без ремонта» по категориям не посчитана")
            stats = category_stats(history)

            base_url = ""
            try:
                client = await self._client_factory()
                base_url = str(getattr(client, "base_url", "") or "").rstrip("/")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Gincore: {exc}")

            def order_url(oid: str) -> str | None:
                return f"{base_url}/orders/{oid}" if base_url else None

            candidates = find_candidates(working, today=today, stats=stats, taken=taken, order_url=order_url)

            # статусы квитанций из записей: Качество → история → карточка заказа (не больше MAX_FETCH)
            by_working = {str(o.get("order_id")): o for o in working}
            by_hist = {str(r.get("order_id")): r for r in history}
            tickets: dict[str, Any] = {}
            missing: list[str] = []
            for t in sorted(taken):
                row = by_working.get(t)
                if row is not None:
                    info = ticket_info(row)
                    hist = by_hist.get(t)
                    if info and hist and hist.get("paid") is not None:
                        info["paid"] = float(hist.get("paid") or 0)
                    tickets[t] = info
                elif t in by_hist:
                    tickets[t] = ticket_info(by_hist[t])
                else:
                    missing.append(t)
            # закрытые записи старше 45 дней без данных — не дёргаем CRM каждый день
            recent = {str(c.get("ticket")) for c in cases if str(c.get("updated_at") or "")[:10] >= (date.fromordinal(today.toordinal() - 45)).isoformat()}
            missing = [t for t in missing if t in recent][:MAX_FETCH]
            if missing and client is not None:
                await self._set_sync(message=f"Карточки квитанций 0/{len(missing)}", total=len(missing), done=0)
                for i, t in enumerate(missing, 1):
                    try:
                        html = await client.fetch_order_html(t)
                        st = client.parse_order_status(html)
                        pay = client.parse_order_payment(html)
                        tickets[t] = ticket_info(
                            {"status": st.get("status_name"), "paid": pay.get("paid"), "cost": pay.get("repair_cost")}
                        )
                    except Exception as exc:  # noqa: BLE001
                        warnings.append(f"№{t}: {exc}")
                    await self._set_sync(message=f"Карточки квитанций {i}/{len(missing)}", done=i)
                    await asyncio.sleep(0.4)

            engineers = sorted({str(o.get("engineer") or "").strip() for o in working if o.get("engineer")})
            snapshot = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "today": today.isoformat(),
                "candidates": candidates,
                "pool": {
                    "working": len(working),
                    "buffer": sum(1 for c in candidates if c["source"] == "buffer"),
                    "undiagnosed": sum(1 for c in candidates if c["source"] == "undiagnosed"),
                },
                "categories": stats,
                "category_labels": CATEGORY_LABELS,
                "engineers": engineers,
                "tickets": tickets,
                "warnings": warnings,
            }
            await self._set_sync(message="Отправка снимка в облако…")
            await fb.put_diag_snapshot(snapshot)
            await self.db.set_setting(
                SUMMARY_KEY,
                {
                    "generated_at": snapshot["generated_at"],
                    "pool": snapshot["pool"],
                    "candidates_top": [
                        {k: c.get(k) for k in ("ticket", "device", "category", "source", "engineer", "days", "score")}
                        for c in candidates[:15]
                    ],
                    "tickets": tickets,
                    "category_labels": CATEGORY_LABELS,
                    "warnings": warnings,
                },
            )
            msg = (
                f"Готово: кандидатов {len(candidates)} (в буфере {snapshot['pool']['buffer']}, "
                f"не продиагностировано {snapshot['pool']['undiagnosed']}), записей {len(cases)}"
            )
            if warnings:
                msg += " · " + "; ".join(warnings[:3])
            await self._set_sync(status="idle", message=msg, finished_at=datetime.now(timezone.utc).isoformat())
        except Exception as exc:  # noqa: BLE001
            log.exception("Платная диагностика: синхронизация упала")
            await self._set_sync(
                status="error",
                message=f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001
                    pass
