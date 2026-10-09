"""Синхронизация Google Sheets → локальный кэш и статистика «Выработка»."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from core.db import Database
from modules.vyrobotka.parse import (
    aggregate_sheet_debt,
    aggregate_sheet_upsell,
    collect_underpaid_tickets,
    normalize_sheet_title,
    parse_week_rows,
    select_week_sheets,
)
from modules.vyrobotka.sheets import GoogleSheetsClient, SheetsError
from modules.vyrobotka.verify import (
    apply_display_verdicts,
    build_verify_report,
    compare_ticket_with_crm,
    crm_totals_from_payment,
)

SettingsProvider = Callable[[], Awaitable[dict[str, Any]]]
GincoreClientFactory = Callable[[], Awaitable[Any]]

_sync_lock = asyncio.Lock()
_sync_task: asyncio.Task | None = None
_verify_lock = asyncio.Lock()
_verify_task: asyncio.Task | None = None

# Аккуратно к Gincore: строго по одной квитанции, паузы между запросами.
VERIFY_PAUSE_S = 0.75
VERIFY_BATCH_EVERY = 20
VERIFY_BATCH_PAUSE_S = 4.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VyrobotkaService:
    def __init__(
        self,
        db: Database,
        settings_provider: SettingsProvider,
        gincore_client_factory: GincoreClientFactory | None = None,
    ) -> None:
        self.db = db
        self._settings_provider = settings_provider
        self._gincore_client_factory = gincore_client_factory

    async def _client(self) -> tuple[GoogleSheetsClient, str]:
        cfg = await self._settings_provider()
        if cfg.get("enabled") is False:
            raise SheetsError("Модуль «Выработка» выключен")
        raw = cfg.get("service_account_json") or ""
        if not raw or raw == "********":
            raise SheetsError("Нет JSON ключа service account — сохраните в настройках модуля")
        sid = (cfg.get("spreadsheet_id") or "").strip()
        if not sid:
            raise SheetsError("Не указан ID таблицы")
        return GoogleSheetsClient(raw), sid

    async def get_stats(self) -> dict[str, Any]:
        sheets = await self.db.vyrobotka_list_sheet_stats()
        sync = await self.db.vyrobotka_get_sync_state()
        all_rows = await self.db.vyrobotka_list_rows()
        by_sheet: dict[str, list[dict[str, Any]]] = {}
        for r in all_rows:
            title = str(r.get("sheet_title") or "")
            by_sheet.setdefault(title, []).append(r)
        debt_sheets: list[dict[str, Any]] = []
        for s in sheets:
            title = str(s.get("sheet_title") or "")
            debt_sheets.append(aggregate_sheet_debt(title, by_sheet.get(title) or []))
        underpaid = collect_underpaid_tickets(all_rows)
        verify = await self.get_debt_verify()
        by_key = {
            f"{r.get('sheet_title')}::{r.get('ticket')}": r
            for r in (verify.get("rows") or [])
        }
        for t in underpaid:
            key = f"{t.get('sheet_title')}::{t.get('ticket')}"
            vr = by_key.get(key)
            if vr:
                t["verify"] = {
                    "verdict": vr.get("verdict"),
                    "summary": vr.get("summary"),
                    "issues": vr.get("issues") or [],
                    "field_diffs": vr.get("field_diffs") or {},
                    "crm_total": vr.get("crm_total"),
                    "crm_paid": vr.get("crm_paid"),
                    "crm_debt": vr.get("crm_debt"),
                    "crm_status": vr.get("crm_status"),
                    "crm_url": vr.get("crm_url"),
                }
        return {
            "ok": True,
            "sheets": sheets,
            "sync": sync,
            "sheets_count": len(sheets),
            "debt": {
                "sheets": debt_sheets,
                "tickets": underpaid,
                "tickets_count": len(underpaid),
                "debt_sum": round(sum(float(t.get("debt") or 0) for t in underpaid), 2),
                "verify": verify,
            },
        }

    async def start_sync(self) -> dict[str, Any]:
        global _sync_task
        state = await self.db.vyrobotka_get_sync_state()
        if state.get("status") == "running":
            return {"ok": True, "started": False, "sync": state}

        async def _runner() -> None:
            async with _sync_lock:
                try:
                    await self._run_sync()
                except Exception as exc:  # noqa: BLE001
                    await self.db.vyrobotka_set_sync_state(
                        status="error",
                        message=str(exc),
                        finished_at=_now(),
                    )

        _sync_task = asyncio.create_task(_runner())
        state = await self.db.vyrobotka_get_sync_state()
        return {"ok": True, "started": True, "sync": state}

    async def _run_sync(self) -> None:
        await self.db.vyrobotka_set_sync_state(
            status="running",
            total=0,
            done=0,
            message="Читаю список листов…",
            started_at=_now(),
            finished_at=None,
        )
        client, sid = await self._client()
        probe = await client.probe(sid)
        weeks = select_week_sheets(probe.get("sheets") or [])
        await self.db.vyrobotka_set_sync_state(
            status="running",
            total=len(weeks),
            done=0,
            message=f"Загрузка {len(weeks)} недельных листов…",
        )
        if not weeks:
            await self.db.vyrobotka_replace_all([], [])
            await self.db.vyrobotka_set_sync_state(
                status="idle",
                done=0,
                total=0,
                message="Нет недельных листов в таблице",
                finished_at=_now(),
            )
            return

        ranges = [client.a1_range(str(s.get("title") or "")) for s in weeks]
        values_map = await client.batch_get_values(sid, ranges)

        all_rows: list[dict[str, Any]] = []
        sheet_stats: list[dict[str, Any]] = []
        for idx, sh in enumerate(weeks):
            title = normalize_sheet_title(str(sh.get("title") or ""))
            rng = client.a1_range(title)
            values = values_map.get(rng) or []
            # fallback: искать по title в ключах
            if not values:
                for k, v in values_map.items():
                    if k.split("!", 1)[0].strip("'") == title:
                        values = v
                        break
            rows = parse_week_rows(title, values)
            for r in rows:
                r["spreadsheet_id"] = sid
            all_rows.extend(rows)
            stats = aggregate_sheet_upsell(title, rows)
            stats["spreadsheet_id"] = sid
            stats["spreadsheet_title"] = probe.get("title")
            sheet_stats.append(stats)
            await self.db.vyrobotka_set_sync_state(
                status="running",
                total=len(weeks),
                done=idx + 1,
                message=f"Лист {idx + 1}/{len(weeks)}: {title}",
            )

        await self.db.vyrobotka_replace_all(all_rows, sheet_stats)
        await self.db.vyrobotka_set_sync_state(
            status="idle",
            total=len(weeks),
            done=len(weeks),
            message=(
                f"Готово: {len(weeks)} листов, {len(all_rows)} квитанций. "
                f"Таблица: {probe.get('title') or sid}"
            ),
            finished_at=_now(),
        )

    async def get_debt_verify(self) -> dict[str, Any]:
        state = await self.db.vyrobotka_get_debt_verify_state()
        # Только для ответа API: mismatch→norm при «Выдан»+без долга. БД не трогаем.
        rows = apply_display_verdicts(await self.db.vyrobotka_list_debt_verify_rows())
        report = build_verify_report(rows) if rows else state.get("report")
        return {
            "status": state.get("status") or "idle",
            "total": int(state.get("total") or 0),
            "done": int(state.get("done") or 0),
            "message": state.get("message"),
            "started_at": state.get("started_at"),
            "finished_at": state.get("finished_at"),
            "report": report,
            "rows": rows,
        }

    async def cancel_debt_verify(self) -> dict[str, Any]:
        state = await self.db.vyrobotka_get_debt_verify_state()
        if state.get("status") == "running":
            await self.db.vyrobotka_set_debt_verify_state(
                cancel_requested=1,
                message="Остановка после текущей квитанции…",
            )
        return await self.get_debt_verify()

    async def start_debt_verify(self, mode: str = "all") -> dict[str, Any]:
        global _verify_task
        if not self._gincore_client_factory:
            raise SheetsError("Gincore не подключён — настройте модуль Gincore")
        mode_norm = "new" if str(mode or "").strip().casefold() in {"new", "only_new", "unchecked"} else "all"
        state = await self.db.vyrobotka_get_debt_verify_state()
        if state.get("status") == "running":
            return {"ok": True, "started": False, "verify": await self.get_debt_verify()}

        async def _runner() -> None:
            async with _verify_lock:
                try:
                    await self._run_debt_verify(mode_norm)
                except Exception as exc:  # noqa: BLE001
                    await self.db.vyrobotka_set_debt_verify_state(
                        status="error",
                        message=str(exc),
                        finished_at=_now(),
                        cancel_requested=0,
                    )

        _verify_task = asyncio.create_task(_runner())
        # дать таску стартовать и записать running
        await asyncio.sleep(0.05)
        return {"ok": True, "started": True, "verify": await self.get_debt_verify()}

    async def _run_debt_verify(self, mode: str = "all") -> None:
        all_rows = await self.db.vyrobotka_list_rows()
        underpaid = collect_underpaid_tickets(all_rows)
        existing = await self.db.vyrobotka_list_debt_verify_rows()
        existing_keys = {
            f"{r.get('sheet_title')}::{r.get('ticket')}" for r in existing
        }

        if mode == "new":
            tickets = [
                t
                for t in underpaid
                if f"{t.get('sheet_title')}::{t.get('ticket')}" not in existing_keys
            ]
            label = "новых"
        else:
            await self.db.vyrobotka_clear_debt_verify_rows()
            tickets = underpaid
            label = "квитанций"

        await self.db.vyrobotka_set_debt_verify_state(
            status="running",
            total=len(tickets),
            done=0,
            message=f"Старт сверки {len(tickets)} {label} с Gincore…",
            report=None,
            report_json=None,
            cancel_requested=0,
            started_at=_now(),
            finished_at=None,
        )
        if not tickets:
            # для mode=new сохраняем прошлый отчёт по всем уже проверенным
            all_checked = await self.db.vyrobotka_list_debt_verify_rows() if mode == "new" else []
            report = build_verify_report(all_checked)
            msg = (
                "Нет новых недоплаченных квитанций — всё уже сверено"
                if mode == "new"
                else "Нет недоплаченных квитанций для сверки"
            )
            await self.db.vyrobotka_set_debt_verify_state(
                status="idle",
                done=0,
                total=0 if mode != "new" else len(all_checked),
                message=msg,
                report=report,
                finished_at=_now(),
            )
            return

        assert self._gincore_client_factory is not None
        client = await self._gincore_client_factory()
        await client.ensure_login()

        batch_results: list[dict[str, Any]] = []
        for i, ticket in enumerate(tickets):
            state = await self.db.vyrobotka_get_debt_verify_state()
            if int(state.get("cancel_requested") or 0):
                all_checked = await self.db.vyrobotka_list_debt_verify_rows()
                report = build_verify_report(all_checked)
                await self.db.vyrobotka_set_debt_verify_state(
                    status="idle",
                    done=i,
                    message=f"Остановлено: проверено {i}/{len(tickets)} в этом запуске",
                    report=report,
                    cancel_requested=0,
                    finished_at=_now(),
                )
                return

            oid = str(ticket.get("ticket") or "").strip()
            await self.db.vyrobotka_set_debt_verify_state(
                status="running",
                total=len(tickets),
                done=i,
                message=f"Gincore {i + 1}/{len(tickets)} · №{oid}",
            )
            compared = await self._verify_one(client, ticket)
            await self.db.vyrobotka_upsert_debt_verify_row(compared)
            batch_results.append(compared)

            await self.db.vyrobotka_set_debt_verify_state(
                status="running",
                total=len(tickets),
                done=i + 1,
                message=f"Gincore {i + 1}/{len(tickets)} · №{oid} · {compared.get('verdict')}",
            )

            # пауза между запросами; каждые N — длиннее
            if i + 1 < len(tickets):
                pause = VERIFY_PAUSE_S
                if (i + 1) % VERIFY_BATCH_EVERY == 0:
                    pause = VERIFY_BATCH_PAUSE_S
                    await self.db.vyrobotka_set_debt_verify_state(
                        message=(
                            f"Пауза {int(pause)}с после {i + 1} квитанций "
                            f"(щадим Gincore)…"
                        ),
                    )
                await asyncio.sleep(pause)

        all_checked = await self.db.vyrobotka_list_debt_verify_rows()
        report = build_verify_report(all_checked)
        prefix = "Новые сверены" if mode == "new" else "Сверка готова"
        await self.db.vyrobotka_set_debt_verify_state(
            status="idle",
            total=len(all_checked),
            done=len(all_checked),
            message=(
                f"{prefix}: в этом запуске {len(batch_results)}; "
                f"всего ок {report['ok']}, "
                f"расхождений {report['mismatch']}, "
                f"нет в CRM {report['missing']}, "
                f"ошибок {report['error']}"
            ),
            report=report,
            cancel_requested=0,
            finished_at=_now(),
        )

    async def _verify_one(self, client: Any, ticket: dict[str, Any]) -> dict[str, Any]:
        from modules.gincore.client import GincoreError

        oid = str(ticket.get("ticket") or "").strip()
        try:
            html = await client.fetch_order_html(oid)
            payment = client.parse_order_payment(html)
            status = client.parse_order_status(html)
            crm_total, crm_paid, crm_debt = crm_totals_from_payment(payment)
            # пустая карточка без сумм и статуса — считаем missing
            if (
                crm_total is None
                and crm_paid is None
                and not status.get("status_name")
                and not status.get("status_id")
            ):
                return compare_ticket_with_crm(ticket, missing=True, crm_url=f"{client.base_url}/orders/{oid}")
            return compare_ticket_with_crm(
                ticket,
                crm_total=crm_total,
                crm_paid=crm_paid,
                crm_debt=crm_debt,
                crm_status=status.get("status_name"),
                crm_url=f"{client.base_url}/orders/{oid}",
            )
        except GincoreError as exc:
            msg = str(exc)
            if "истекла" in msg.casefold() or "login" in msg.casefold():
                try:
                    await client.ensure_login()
                    html = await client.fetch_order_html(oid)
                    payment = client.parse_order_payment(html)
                    status = client.parse_order_status(html)
                    crm_total, crm_paid, crm_debt = crm_totals_from_payment(payment)
                    return compare_ticket_with_crm(
                        ticket,
                        crm_total=crm_total,
                        crm_paid=crm_paid,
                        crm_debt=crm_debt,
                        crm_status=status.get("status_name"),
                        crm_url=f"{client.base_url}/orders/{oid}",
                    )
                except Exception as exc2:  # noqa: BLE001
                    return compare_ticket_with_crm(
                        ticket, error=str(exc2), crm_url=f"{getattr(client, 'base_url', '')}/orders/{oid}"
                    )
            if "404" in msg or "не найден" in msg.casefold():
                return compare_ticket_with_crm(
                    ticket, missing=True, crm_url=f"{client.base_url}/orders/{oid}"
                )
            return compare_ticket_with_crm(
                ticket, error=msg, crm_url=f"{getattr(client, 'base_url', '')}/orders/{oid}"
            )
        except Exception as exc:  # noqa: BLE001
            return compare_ticket_with_crm(
                ticket,
                error=str(exc),
                crm_url=f"{getattr(client, 'base_url', '')}/orders/{oid}",
            )
