"""Сервис «Аутсорс мастера»: CRM-снимок по аутсорсерам для витрины.

Живые данные менеджера (кандидаты, передачи, журнал, план) хранятся в Worker jarvis-feedback (D1)
и видны на витрине сразу. Jarvis раз в пересборку забирает список кандидатов (ADMIN_KEY),
считает по привязанным мастерам Gincore: устройства в работе, возвраты, вал, выплаты из кассы,
и публикует снимок docs/outsource/data.json.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable

from modules.gincore.client import to_gincore_date
from modules.gincore.quality import QUALITY_LIST_QUERY
from modules.outsource.compute import (
    ACTIVE_STAGES,
    guess_surname_tokens,
    build_outsourcer_metrics,
    engineer_names,
    parse_history_rows,
    sum_payouts,
    trial_ticket_info,
)

log = logging.getLogger(__name__)

SYNC_KEY = "outsource_sync"
SNAPSHOT_KEY = "outsource_snapshot"
HISTORY_KEY = "outsource_history"

# Окно истории (календарных месяцев, включая текущий) и «свежесть», после которой месяц не перекачиваем.
HISTORY_MONTHS = 4
REFETCH_RECENT_DAYS = 45
MAX_PAGES_PER_MONTH = 80


def history_months(today: date, n: int = HISTORY_MONTHS) -> list[tuple[str, str, str]]:
    """[(YYYY-MM, date_from, date_to)] от старого к новому; текущий месяц — до сегодня."""
    out: list[tuple[str, str, str]] = []
    y, m = today.year, today.month
    for _ in range(n):
        start = date(y, m, 1)
        end = date(y + (m == 12), m % 12 + 1, 1)
        end = date.fromordinal(end.toordinal() - 1)
        if end > today:
            end = today
        out.append((f"{y:04d}-{m:02d}", start.isoformat(), end.isoformat()))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(out))


def month_needs_refetch(entry: dict[str, Any] | None, month_end: str, today: date) -> bool:
    if not entry or not entry.get("complete"):
        return True
    try:
        end = date.fromisoformat(month_end)
    except ValueError:
        return True
    return (today - end).days <= REFETCH_RECENT_DAYS


def _deps_param() -> str:
    for part in QUALITY_LIST_QUERY.split("&"):
        if part.startswith("dep="):
            return part[4:]
    return ""


class OutsourceService:
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

    # ---------- состояние ----------
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
        """Снимок CRM + живая воронка из облака (для админки; контакты не отдаём)."""
        snap = await self.db.get_setting(SNAPSHOT_KEY, None) or {}
        live: dict[str, Any] = {"ok": False}
        fb = self._feedback_factory()
        if getattr(fb, "configured", False):
            try:
                state = await fb.get_outsource_state()
                trials = list(state.get("trials") or [])
                keep = ("id", "name", "kind", "stage", "stage_at", "lost_reason", "crm_engineer", "cash_contractor", "created_by")
                cands = []
                for c in state.get("candidates") or []:
                    row = {k: c.get(k) for k in keep}
                    ct = [t for t in trials if t.get("candidate_id") == c.get("id")]
                    rated = [t for t in ct if t.get("result_quality")]
                    row["trials"] = len(ct)
                    row["trials_open"] = sum(1 for t in ct if not t.get("result_decision"))
                    row["avg_quality"] = (
                        round(sum(t["result_quality"] for t in rated) / len(rated), 1) if rated else None
                    )
                    cands.append(row)
                log = list(state.get("log") or [])
                live = {
                    "ok": True,
                    "candidates": cands,
                    "plan": state.get("plan"),
                    "log_total": len(log),
                    "last_action": log[0] if log else None,
                }
            except Exception as exc:  # noqa: BLE001
                live = {"ok": False, "error": str(exc)}
        else:
            live = {"ok": False, "error": "облако «Улучшения» не настроено"}
        return {"ok": True, **snap, "live": live, "sync": await self.get_sync_state()}

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

    # ---------- прогон ----------
    async def _run_sync(self) -> None:
        client = None
        warnings: list[str] = []
        try:
            today = date.today()
            # 1. Кандидаты и передачи из Worker
            await self._set_sync(message="Кандидаты из облака…")
            candidates: list[dict[str, Any]] = []
            trials: list[dict[str, Any]] = []
            fb = self._feedback_factory()
            if getattr(fb, "configured", False):
                try:
                    state = await fb.get_outsource_state()
                    candidates = list(state.get("candidates") or [])
                    trials = list(state.get("trials") or [])
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"облако: {exc}")
            else:
                warnings.append("Worker «Улучшения» не настроен — кандидатов нет")

            # 2. Рабочие заказы — из кэша Качества (его пересборка идёт раньше)
            working: list[dict[str, Any]] = []
            if self.quality_service is not None:
                working = list((await self.quality_service.list_rows()).get("orders") or [])

            client = await self._client_factory()
            base_url = str(getattr(client, "base_url", "") or "").rstrip("/")

            def order_url(oid: str) -> str | None:
                return f"{base_url}/orders/{oid}" if base_url else None

            # 3. История заказов за окно (кэш по месяцам)
            history = await self._sync_history(client, today)

            # 4. Выплаты аутсорсерам из кассы
            months = history_months(today)
            window_from = months[0][1]
            payouts_by_cand: dict[Any, dict[str, Any]] = {}
            bound = [
                c for c in candidates if (c.get("cash_contractor") or c.get("crm_engineer") or "").strip()
            ]
            for i, cand in enumerate(bound, 1):
                await self._set_sync(message=f"Выплаты из кассы {i}/{len(bound)}")
                explicit = str(cand.get("cash_contractor") or "").strip()
                query = explicit or str(cand.get("crm_engineer") or "").strip()
                entry: dict[str, Any] = {"contractor": explicit or None, "matched": False, "auto": not explicit}
                try:
                    if explicit:
                        found = await client.find_contractor(explicit)
                    else:
                        # получатель не указан — ищем в кассе по фамилии мастера; берём только однозначное совпадение
                        # только самое длинное слово (фамилия): по имени «Саша» легко попасть в чужого
                        found = []
                        toks = sorted(guess_surname_tokens(query), key=len, reverse=True)
                        if toks:
                            hits = await client.find_contractor(toks[0])
                            if len(hits) == 1:
                                found = hits
                    if found:
                        ct = found[0]
                        if explicit and len(found) > 1:
                            warnings.append(
                                f"«{query}» в кассе: {len(found)} совпадений, взят «{ct.get('name')}»"
                            )
                        data = await client.fetch_transactions(
                            date_from=window_from, date_to=today.isoformat(), contractor_id=ct["id"]
                        )
                        entry = {
                            "contractor": ct.get("name") or query,
                            "matched": True,
                            "auto": not explicit,
                            **sum_payouts(list(data.get("rows") or [])),
                        }
                    elif explicit:
                        warnings.append(f"в кассе нет получателя «{query}»")
                    else:
                        warnings.append(
                            f"«{cand.get('name')}»: получатель выплат в кассе не указан и не найден по фамилии"
                        )
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"выплаты «{query}»: {exc}")
                payouts_by_cand[cand.get("id")] = entry

            # 5. Статусы квитанций пробников
            working_by_id = {str(o.get("order_id")): o for o in working}
            history_by_id = {str(r.get("order_id")): r for r in history}
            fetched: dict[str, dict[str, Any]] = {}
            tickets = sorted({str(t.get("ticket")) for t in trials if t.get("ticket")})
            missing = [t for t in tickets if t not in working_by_id and t not in history_by_id]
            for i, ticket in enumerate(missing, 1):
                await self._set_sync(message=f"Карточки пробников {i}/{len(missing)}")
                try:
                    fetched[ticket] = await self._fetch_order_brief(client, ticket)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"№{ticket}: {exc}")
            trials_info = {}
            for t in tickets:
                info = trial_ticket_info(
                    t,
                    working_by_id=working_by_id,
                    history_by_id=history_by_id,
                    fetched=fetched,
                    order_url=order_url,
                )
                if info:
                    trials_info[t] = info

            # 6. Метрики по аутсорсерам
            outsourcers: dict[str, Any] = {}
            for cand in candidates:
                metrics = build_outsourcer_metrics(
                    cand,
                    working=working,
                    history=history,
                    payouts=payouts_by_cand.get(cand.get("id")),
                    today=today,
                    order_url=order_url,
                )
                if cand.get("crm_engineer") and not metrics["engineers_matched"]:
                    warnings.append(f"мастер «{cand.get('crm_engineer')}» не найден в CRM")
                outsourcers[str(cand.get("id"))] = metrics

            active = [
                outsourcers[str(c.get("id"))]
                for c in candidates
                if c.get("stage") in ACTIVE_STAGES and str(c.get("id")) in outsourcers
            ]
            idle = sum(1 for m in active if m["bound"] and m["in_work"] == 0)
            snapshot = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "today": today.isoformat(),
                "window": {"from": window_from, "to": today.isoformat(), "months": [m[0] for m in months]},
                "engineers": engineer_names(working, history),
                "outsourcers": outsourcers,
                "trials": trials_info,
                "history_orders": len(history),
                "warnings": warnings,
            }
            await self.db.set_setting(SNAPSHOT_KEY, snapshot)

            msg = (
                f"Готово: кандидатов {len(candidates)}, в работе у аутсорсеров "
                f"{sum(m['in_work'] for m in outsourcers.values())} устр., без устройств {idle}, "
                f"история {len(history)} квит."
            )
            try:
                await self.export_pages_snapshot()
                msg += ", pages ок"
            except Exception as exc:  # noqa: BLE001
                msg += f", экспорт Pages: {exc}"
            if warnings:
                msg += f" · предупреждений {len(warnings)}: " + "; ".join(warnings[:3])
            await self._set_sync(
                status="idle",
                message=msg,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("Аутсорс: синхронизация упала")
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
        cached_months: dict[str, Any] = dict(cache.get("months") or {})
        months = history_months(today)
        keep = {m[0] for m in months}
        todo = [m for m in months if month_needs_refetch(cached_months.get(m[0]), m[2], today)]
        await self._set_sync(total=len(todo), done=0)
        deps = _deps_param()
        for i, (key, dfrom, dto) in enumerate(todo, 1):
            rows: list[dict[str, Any]] = []
            seen: set[str] = set()
            complete = False
            total_count = None
            for page in range(1, MAX_PAGES_PER_MONTH + 1):
                await self._set_sync(message=f"История {key}: стр. {page}", done=i - 1)
                params = {"df": to_gincore_date(dfrom), "dt": to_gincore_date(dto)}
                if deps:
                    params["dep"] = deps
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
            cached_months[key] = {
                "complete": complete,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "count": len(rows),
                "rows": rows,
            }
            await self._set_sync(done=i)
        cached_months = {k: v for k, v in cached_months.items() if k in keep}
        await self.db.set_setting(HISTORY_KEY, {"months": cached_months})
        out: list[dict[str, Any]] = []
        for key in sorted(cached_months):
            out.extend(cached_months[key].get("rows") or [])
        return out

    async def _fetch_order_brief(self, client: Any, ticket: str) -> dict[str, Any]:
        from modules.gincore.quality import parse_order_page_meta

        html = await client.fetch_order_html(ticket)
        meta = parse_order_page_meta(html)
        pay = client.parse_order_payment(html)
        return {
            "status": meta.get("status_name"),
            "accepted_at": meta.get("accepted_at"),
            "paid": pay.get("paid"),
        }

    # ---------- витрина ----------
    async def export_pages_snapshot(self) -> dict[str, Any]:
        from modules.outsource.export import build_outsource_pages_payload, write_outsource_pages_json

        snap = await self.db.get_setting(SNAPSHOT_KEY, None) or {}
        payload = build_outsource_pages_payload(snap, sync=await self.get_sync_state())
        path = write_outsource_pages_json(payload)
        return {
            "ok": True,
            "path": str(path),
            "outsourcers": len(payload.get("outsourcers") or {}),
            "exported_at": payload["exported_at"],
        }
