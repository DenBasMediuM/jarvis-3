"""Сервис «Постоянные клиенты»: CRM-снимок клиентов и кандидатов → облако (не в публичный репозиторий).

Живые данные менеджера (клиенты, договоры, касания, справочники) — в Worker jarvis-feedback (D1).
Jarvis раз в пересборку: забирает клиентов (телефоны) и решения по кандидатам, качает историю
ремонтов за 12 месяцев (кэш по месяцам), считает метрики клиентов и кандидатов из базы и
отправляет снимок в облако — витрина получает его только по токену входа.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable

from modules.clients.compute import (
    HISTORY_MONTHS,
    client_metrics,
    find_candidates,
    index_by_phone,
    parse_history_rows,
    staff_name_sets,
)
from modules.gincore.client import to_gincore_date
from modules.outsource.compute import classify_status
from modules.outsource.service import _deps_param, history_months, month_needs_refetch

log = logging.getLogger(__name__)

SYNC_KEY = "clients_sync"
SUMMARY_KEY = "clients_summary"
HISTORY_KEY = "clients_history_v2"  # v2: телефон из полного текста ячейки «Клиент»
MAX_PAGES_PER_MONTH = 80


class ClientsService:
    def __init__(
        self,
        db: Any,
        *,
        gincore_client_factory: Callable[[], Awaitable[Any]],
        feedback_client_factory: Callable[[], Any],
    ) -> None:
        self.db = db
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
        """Сводка последней синхронизации + живое состояние облака (для админки, без контактов)."""
        summary = await self.db.get_setting(SUMMARY_KEY, None) or {}
        live: dict[str, Any] = {"ok": False}
        fb = self._feedback_factory()
        if getattr(fb, "configured", False):
            try:
                st = await fb.get_clients_state()
                keep = ("id", "name", "kind", "stage", "stage_at", "next_step", "next_step_at", "last_touch_at", "source")
                live = {
                    "ok": True,
                    "clients": [{k: c.get(k) for k in keep} for c in st.get("clients") or []],
                    "contracts": [
                        {k: c.get(k) for k in ("id", "client_id", "number", "status", "valid_to")}
                        for c in st.get("contracts") or []
                    ],
                    "plan": st.get("plan"),
                    "log_total": len(st.get("log") or []),
                }
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

    async def _run_sync(self) -> None:
        client = None
        warnings: list[str] = []
        try:
            today = date.today()
            await self._set_sync(message="Клиенты из облака…")
            fb = self._feedback_factory()
            if not getattr(fb, "configured", False):
                raise RuntimeError("облако «Улучшения» не настроено (JARVIS_FEEDBACK_URL / ADMIN_KEY)")
            state = await fb.get_clients_state()
            clients = list(state.get("clients") or [])
            decisions = list(state.get("decisions") or [])
            settings = state.get("settings") or {}

            client = await self._client_factory()
            base_url = str(getattr(client, "base_url", "") or "").rstrip("/")

            def order_url(oid: str) -> str | None:
                return f"{base_url}/orders/{oid}" if base_url else None

            history = await self._sync_history(client, today)
            by_phone = index_by_phone(history)

            await self._set_sync(message="Метрики клиентов…")
            metrics: dict[str, Any] = {}
            known: set[str] = set()
            unmatched = 0
            for c in clients:
                phones = [str(p) for p in c.get("phones") or [] if p]
                known.update(phones)
                m = client_metrics(phones, by_phone, today=today, order_url=order_url)
                if phones and not m["phones_matched"] and c.get("stage") == "active":
                    unmatched += 1
                metrics[str(c.get("id"))] = m
            if unmatched:
                warnings.append(f"у {unmatched} постоянных клиентов нет заказов в CRM по указанным телефонам")

            skip = set(known)
            skip.update(str(p) for p in settings.get("excluded_phones") or [])
            today_s = today.isoformat()
            for d in decisions:
                if d.get("decision") in ("dismissed", "taken"):
                    skip.add(str(d.get("phone")))
                elif d.get("decision") == "snoozed" and str(d.get("until") or "") > today_s:
                    skip.add(str(d.get("phone")))
            staff_names: list[str] = []
            try:
                for o in await self.db.quality_list_orders():
                    staff_names += [str(o.get(k) or "") for k in ("engineer", "manager", "accepter")]
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"список сотрудников из Качества: {exc}")
            skipped: dict[str, int] = {}
            candidates = find_candidates(
                by_phone,
                today=today,
                thresholds=settings.get("thresholds") or {},
                skip_phones=skip,
                order_url=order_url,
                staff=staff_name_sets(staff_names),
                skipped=skipped,
            )
            if skipped.get("staff"):
                warnings.append(f"не предложено как сотрудники/мастера: {skipped['staff']}")

            totals = {"gross_90": 0.0, "orders_90": 0}
            for r in history:
                try:
                    age = (today - date.fromisoformat(str(r.get("accepted_at"))[:10])).days
                except ValueError:
                    continue
                if age <= 90:
                    totals["orders_90"] += 1
                    if classify_status(r.get("status")) in ("issued", "refusal"):
                        totals["gross_90"] += float(r.get("paid") or 0)
            totals["gross_90"] = round(totals["gross_90"], 2)

            months = history_months(today, HISTORY_MONTHS)
            snapshot = {
                "totals": totals,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "today": today_s,
                "window": {"from": months[0][1], "to": today_s, "months": len(months)},
                "history_orders": len(history),
                "phones": len(by_phone),
                "clients": metrics,
                "candidates": candidates,
                "warnings": warnings,
            }
            await self._set_sync(message="Отправка снимка в облако…")
            await fb.put_clients_snapshot(snapshot)

            active = [c for c in clients if c.get("stage") == "active"]
            summary = {
                "generated_at": snapshot["generated_at"],
                "window": snapshot["window"],
                "history_orders": len(history),
                "phones": len(by_phone),
                "candidates_total": len(candidates),
                "candidates_top": [
                    {k: c.get(k) for k in ("name", "orders", "recent", "gross", "last_at", "b2b", "score")}
                    for c in candidates[:15]
                ],
                "metrics": {
                    str(cid): {k: m.get(k) for k in ("orders_90", "gross_90", "trend", "days_since_last", "asleep", "debt")}
                    | {"in_work": len(m.get("in_work") or [])}
                    for cid, m in metrics.items()
                },
                "warnings": warnings,
            }
            await self.db.set_setting(SUMMARY_KEY, summary)
            asleep = sum(1 for c in active if metrics.get(str(c.get("id")), {}).get("asleep"))
            msg = (
                f"Готово: клиентов {len(clients)} (постоянных {len(active)}, «заснули» {asleep}), "
                f"кандидатов из базы {len(candidates)}, история {len(history)} квит."
            )
            if warnings:
                msg += " · " + "; ".join(warnings[:3])
            await self._set_sync(status="idle", message=msg, finished_at=datetime.now(timezone.utc).isoformat())
        except Exception as exc:  # noqa: BLE001
            log.exception("Постоянные клиенты: синхронизация упала")
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

    async def _sync_history(self, client: Any, today: date) -> list[dict[str, Any]]:
        cache = await self.db.get_setting(HISTORY_KEY, None) or {}
        cached: dict[str, Any] = dict(cache.get("months") or {})
        months = history_months(today, HISTORY_MONTHS)
        keep = {m[0] for m in months}
        todo = [m for m in months if month_needs_refetch(cached.get(m[0]), m[2], today)]
        await self._set_sync(total=len(todo), done=0)
        deps = _deps_param()
        for i, (key, dfrom, dto) in enumerate(todo, 1):
            rows: list[dict[str, Any]] = []
            seen: set[str] = set()
            complete = False
            total_count = None
            for page in range(1, MAX_PAGES_PER_MONTH + 1):
                await self._set_sync(message=f"История {key}: стр. {page} ({i}/{len(todo)})", done=i - 1)
                params = {"df": to_gincore_date(dfrom), "dt": to_gincore_date(dto)}
                if deps:
                    params["dep"] = deps  # все филиалы, кроме Сахарова (как в Качестве)
                meta = await client._repair_orders_page(page=page, crm_params=params)
                if total_count is None:
                    total_count = int(meta.get("count") or 0)
                chunk = parse_history_rows(meta.get("html") or "")
                new = [r for r in chunk if r["order_id"] not in seen]
                for r in new:
                    seen.add(r["order_id"])
                rows.extend(new)
                if not chunk or not new or (total_count and len(rows) >= total_count):
                    complete = True
                    break
                await asyncio.sleep(0.2)
            cached[key] = {
                "complete": complete,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "count": len(rows),
                "rows": rows,
            }
            # сохраняем по месяцу — если прогон прервётся, скачанное не пропадёт
            await self.db.set_setting(HISTORY_KEY, {"months": {k: v for k, v in cached.items() if k in keep}})
            await self._set_sync(done=i)
        cached = {k: v for k, v in cached.items() if k in keep}
        await self.db.set_setting(HISTORY_KEY, {"months": cached})
        out: list[dict[str, Any]] = []
        for key in sorted(cached):
            out.extend(cached[key].get("rows") or [])
        return out
