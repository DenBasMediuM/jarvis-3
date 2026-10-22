"""Синхронизация Google Sheets → локальный кэш и статистика «Выработка»."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable

from core.db import Database
from modules.vyrobotka.parse import (
    aggregate_sheet_debt,
    aggregate_sheet_upsell,
    collect_underpaid_tickets,
    normalize_sheet_title,
    parse_week_rows,
    select_week_sheets,
    sheet_sort_key,
    underpayment_amount,
)
from modules.vyrobotka.sheets import GoogleSheetsClient, SheetsError
from modules.vyrobotka.verify import (
    apply_display_verdicts,
    build_verify_report,
    classify_debt_row,
    compare_ticket_with_crm,
    crm_totals_from_payment,
    is_atypical_debt_case,
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
CRM_LIST_PAGE_PAUSE_S = 0.4

# Фильтр списка ремонтов = «Ожидаемая сумма оплаты» в колонке «Оплачено».
# https://itserviceoutsourcing.gincore.net/orders?other=pay&dep=…#show_repair_orders
CRM_DEBT_LIST_PARAMS: dict[str, str] = {
    "other": "pay",
    "dep": (
        "1-a,1-l,9-a,9-l,13-a,13-l,19-a,19-l,20-a,20-l,"
        "23-a,23-l,26-a,26-l,31-a,31-l,34-a,34-l,37-a,37-l,l-l"
    ),
}


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

        underpaid_all = collect_underpaid_tickets(all_rows)
        baseline = await self.ensure_debt_baseline(underpaid_all)
        underpaid = self._filter_underpaid_by_baseline(underpaid_all, baseline)

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

        debt_sum = (
            float(baseline["sheets_debt_sum"])
            if baseline and baseline.get("sheets_debt_sum") is not None
            else round(sum(float(t.get("debt") or 0) for t in underpaid), 2)
        )
        debt_n = (
            int(baseline["sheets_tickets"])
            if baseline and baseline.get("sheets_tickets") is not None
            else len(underpaid)
        )

        debt_daily = await self.db.vyrobotka_list_debt_daily(limit=730)
        # На графике линия отчётов мастеров — только первый слепок
        if baseline and baseline.get("sheets_debt_sum") is not None:
            frozen = float(baseline["sheets_debt_sum"])
            frozen_n = int(baseline.get("sheets_tickets") or 0)
            debt_daily = [
                {
                    **d,
                    "sheets_debt_sum": frozen,
                    "sheets_tickets": frozen_n or d.get("sheets_tickets"),
                }
                for d in debt_daily
            ]

        # gid вкладок нужны для ссылок «открыть лист квитанции»
        if sheets and any(s.get("sheet_id") is None for s in sheets):
            try:
                await self.refresh_sheet_ids()
                sheets = await self.db.vyrobotka_list_sheet_stats()
            except Exception:  # noqa: BLE001
                pass

        atypical = self._build_atypical_cases(
            verify_rows=verify.get("rows") or [],
            all_rows=all_rows,
            sheet_stats=sheets,
        )
        ledger = await self.db.vyrobotka_list_debt_ledger(active_only=True)
        table = self._enrich_debt_table(ledger, sheets, all_rows)

        return {
            "ok": True,
            "sheets": sheets,
            "sync": sync,
            "sheets_count": len(sheets),
            "debt": {
                "sheets": debt_sheets,
                "tickets": underpaid,
                "tickets_count": debt_n,
                "debt_sum": debt_sum,
                "verify": verify,
                "daily": debt_daily,
                "baseline": baseline,
                "atypical": atypical,
                "table": table,
                "table_counts": self._debt_table_counts(table),
            },
        }

    @staticmethod
    def _debt_table_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts = {"total": len(rows), "red": 0, "yellow": 0, "open": 0, "mismatch": 0}
        for r in rows:
            f = str(r.get("flag") or "")
            if f in counts:
                counts[f] += 1
        return counts

    def _enrich_debt_table(
        self,
        ledger: list[dict[str, Any]],
        sheet_stats: list[dict[str, Any]],
        all_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        stats_by_title = {
            str(s.get("sheet_title") or ""): s for s in sheet_stats
        }
        row_by_key = {
            f"{r.get('sheet_title')}::{r.get('ticket')}": r for r in all_rows
        }
        row_by_ticket: dict[str, dict[str, Any]] = {}
        for r in all_rows:
            tid = str(r.get("ticket") or "")
            if tid and tid not in row_by_ticket:
                row_by_ticket[tid] = r
        out: list[dict[str, Any]] = []
        for item in ledger:
            row = dict(item)
            title = str(row.get("sheet_title") or "")
            ticket = str(row.get("ticket") or "")
            st = stats_by_title.get(title) or {}
            src = row_by_key.get(f"{title}::{ticket}") or row_by_ticket.get(ticket) or {}
            if not title and src.get("sheet_title"):
                title = str(src.get("sheet_title") or "")
                st = stats_by_title.get(title) or st
            sid = src.get("spreadsheet_id") or st.get("spreadsheet_id")
            row["sheet_url"] = GoogleSheetsClient.sheet_tab_url(
                sid,
                st.get("sheet_id"),
                row_index=src.get("row_index"),
            )
            if row.get("salary") is None and src.get("salary") is not None:
                row["salary"] = src.get("salary")
            if row.get("report_amount") is None and src.get("report_amount") is not None:
                row["report_amount"] = src.get("report_amount")
            if not row.get("master") and src.get("master"):
                row["master"] = src.get("master")
            if not row.get("sheet_title") and src.get("sheet_title"):
                row["sheet_title"] = src.get("sheet_title")
            out.append(row)
        return out

    async def get_debt_order_preview(self, ticket: str) -> dict[str, Any]:
        """Карточка квитанции из локального кэша (без запросов в Gincore)."""
        oid = str(ticket or "").strip()
        if not oid:
            raise SheetsError("Не указан номер квитанции")
        ledger = await self.db.vyrobotka_get_debt_ledger_ticket(oid) or {}
        if not ledger:
            raise SheetsError(f"Квитанция №{oid} не найдена в таблице дебиторки")
        salary = ledger.get("salary")
        report_amount = ledger.get("report_amount")
        master = ledger.get("master")
        sheet_title = ledger.get("sheet_title")
        sheet_comments = None
        cur = await self.db.conn.execute(
            """
            SELECT salary, report_amount, master, sheet_title, comments
            FROM vyrobotka_rows
            WHERE ticket = ?
            ORDER BY row_index ASC
            LIMIT 1
            """,
            (oid,),
        )
        src = await cur.fetchone()
        if src:
            if salary is None:
                salary = src["salary"]
            if report_amount is None:
                report_amount = src["report_amount"]
            if not master:
                master = src["master"]
            if not sheet_title:
                sheet_title = src["sheet_title"]
            sheet_comments = src["comments"]
        feed: list[dict[str, Any]] = []
        raw_feed = ledger.get("crm_feed_json")
        if raw_feed:
            try:
                parsed = json.loads(raw_feed)
                if isinstance(parsed, list):
                    feed = parsed
            except json.JSONDecodeError:
                feed = []
        crm_url = ledger.get("crm_url") or f"https://itserviceoutsourcing.gincore.net/orders/{oid}"
        return {
            "ok": True,
            "order_id": oid,
            "url": crm_url,
            "title": None,
            "payment": {
                "repair_cost": ledger.get("crm_total"),
                "total_with_discount": ledger.get("crm_total"),
                "paid": ledger.get("crm_paid"),
                "due": ledger.get("crm_debt"),
            },
            "live_feed": feed,
            "crm_status": ledger.get("crm_status"),
            "crm_feed_at": ledger.get("crm_feed_at"),
            "from_cache": True,
            "ledger": {
                "sheet_debt": ledger.get("sheet_debt"),
                "crm_debt": ledger.get("crm_debt"),
                "crm_total": ledger.get("crm_total"),
                "crm_paid": ledger.get("crm_paid"),
                "salary": salary,
                "report_amount": report_amount,
                "master": master,
                "flag": ledger.get("flag"),
                "flag_reason": ledger.get("flag_reason"),
                "sheet_title": sheet_title,
                "sheet_comments": sheet_comments,
            },
        }

    async def ensure_debt_baseline(
        self, underpaid: list[dict[str, Any]] | None = None
    ) -> dict[str, Any] | None:
        """Первый слепок дебиторки по отчётам: суммы + набор квитанций."""
        existing = await self.db.vyrobotka_get_debt_baseline()
        if existing and existing.get("day"):
            tickets = await self.db.vyrobotka_list_debt_baseline_tickets()
            return {**existing, "tickets": tickets}

        daily = await self.db.vyrobotka_list_debt_daily(limit=730)
        if not daily:
            return None
        first = daily[0]
        if underpaid is None:
            underpaid = collect_underpaid_tickets(await self.db.vyrobotka_list_rows())
        picked = self._pick_baseline_tickets(
            underpaid,
            target_tickets=int(first.get("sheets_tickets") or 0),
            target_sum=float(first.get("sheets_debt_sum") or 0),
        )
        locked = await self.db.vyrobotka_set_debt_baseline(
            day=str(first.get("day")),
            sheets_debt_sum=float(first.get("sheets_debt_sum") or 0),
            sheets_tickets=int(first.get("sheets_tickets") or len(picked)),
            tickets=picked,
            locked_at=_now(),
        )
        locked["tickets"] = picked
        return locked

    @staticmethod
    def _pick_baseline_tickets(
        underpaid: list[dict[str, Any]],
        *,
        target_tickets: int,
        target_sum: float,
    ) -> list[dict[str, Any]]:
        """Восстановить набор первого слепка: убираем квитанции с самых новых листов."""
        if not underpaid:
            return []
        selected = list(underpaid)
        if target_tickets <= 0 or len(selected) <= target_tickets:
            return selected
        # Снимаем с самых новых листов, пока не дойдём до числа квитанций первого слепка
        while len(selected) > target_tickets:
            newest = max(
                selected,
                key=lambda t: (
                    sheet_sort_key(str(t.get("sheet_title") or "")),
                    str(t.get("ticket") or ""),
                ),
            )
            selected.remove(newest)
        if target_sum > 0:
            # если сумма сильно разъехалась — ничего, в KPI всё равно берём target_sum
            pass
        return selected

    @staticmethod
    def _filter_underpaid_by_baseline(
        underpaid: list[dict[str, Any]],
        baseline: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not baseline:
            return underpaid
        keys = {
            f"{t.get('sheet_title')}::{t.get('ticket')}"
            for t in (baseline.get("tickets") or [])
        }
        if not keys:
            # только суммы слепка, набор квитанций ещё не сохранён
            return underpaid
        return [
            t
            for t in underpaid
            if f"{t.get('sheet_title')}::{t.get('ticket')}" in keys
        ]

    async def refresh_sheet_ids(self) -> dict[str, int]:
        """Подтянуть gid вкладок из метаданных таблицы (без чтения значений)."""
        client, sid = await self._client()
        probe = await client.probe(sid)
        known = await self.db.vyrobotka_known_sheet_meta()
        title_to_id: dict[str, int] = {}
        for sh in probe.get("sheets") or []:
            title = normalize_sheet_title(str(sh.get("title") or ""))
            gid = sh.get("sheet_id")
            if not title or gid is None:
                continue
            title_to_id[title] = int(gid)
            prev = known.get(title)
            if not prev:
                continue
            if prev.get("sheet_id") == int(gid):
                continue
            st = dict(prev)
            st["sheet_id"] = int(gid)
            st["spreadsheet_title"] = probe.get("title")
            await self.db.vyrobotka_touch_sheet_meta(st)
        return title_to_id

    def _build_atypical_cases(
        self,
        *,
        verify_rows: list[dict[str, Any]],
        all_rows: list[dict[str, Any]],
        sheet_stats: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Отказ/без ремонта в CRM, а в отчёте — долг клиента и сумма работ мастера."""
        row_by_key = {
            f"{r.get('sheet_title')}::{r.get('ticket')}": r for r in all_rows
        }
        stats_by_title = {
            str(s.get("sheet_title") or ""): s for s in sheet_stats
        }
        out: list[dict[str, Any]] = []
        for vr in verify_rows:
            key = f"{vr.get('sheet_title')}::{vr.get('ticket')}"
            src = row_by_key.get(key) or {}
            report_amount = src.get("report_amount")
            sheet_debt = vr.get("sheet_debt")
            if sheet_debt is None:
                sheet_debt = underpayment_amount(
                    vr.get("sheet_total") if vr.get("sheet_total") is not None else src.get("total_repair"),
                    vr.get("sheet_paid") if vr.get("sheet_paid") is not None else src.get("paid"),
                )
            if not is_atypical_debt_case(
                sheet_total=vr.get("sheet_total")
                if vr.get("sheet_total") is not None
                else src.get("total_repair"),
                crm_total=vr.get("crm_total"),
                sheet_debt=sheet_debt,
                report_amount=report_amount,
                crm_status=vr.get("crm_status"),
                crm_debt=vr.get("crm_debt"),
                crm_paid=vr.get("crm_paid"),
            ):
                continue
            st = stats_by_title.get(str(vr.get("sheet_title") or "")) or {}
            sid = src.get("spreadsheet_id") or st.get("spreadsheet_id")
            sheet_url = GoogleSheetsClient.sheet_tab_url(
                sid,
                st.get("sheet_id"),
                row_index=src.get("row_index"),
            )
            out.append(
                {
                    "ticket": vr.get("ticket"),
                    "master": vr.get("master") or src.get("master"),
                    "sheet_title": vr.get("sheet_title"),
                    "sheet_total": vr.get("sheet_total")
                    if vr.get("sheet_total") is not None
                    else src.get("total_repair"),
                    "crm_total": vr.get("crm_total"),
                    "crm_status": vr.get("crm_status"),
                    "report_amount": report_amount,
                    "crm_paid": vr.get("crm_paid"),
                    "sheet_debt": sheet_debt,
                    "sheet_url": sheet_url,
                    "crm_url": vr.get("crm_url"),
                    "summary": vr.get("summary"),
                    "row_index": src.get("row_index"),
                }
            )
        out.sort(
            key=lambda x: (
                -sheet_sort_key(str(x.get("sheet_title") or ""))[0],
                str(x.get("ticket") or ""),
            )
        )
        return out

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
        """Инкрементальная синхронизация: первый прогон — все листы, далее только новые/выросшие."""
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
        known = await self.db.vyrobotka_known_sheet_meta()
        is_first = not known

        if not weeks:
            if is_first:
                await self.db.vyrobotka_replace_all([], [])
            await self.db.vyrobotka_set_sync_state(
                status="idle",
                done=0,
                total=0,
                message="Нет недельных листов в таблице",
                finished_at=_now(),
            )
            return

        title_to_meta = {
            normalize_sheet_title(str(s.get("title") or "")): s for s in weeks
        }
        # Какие листы читать: все при первом слепке; иначе — неизвестные + самый свежий
        # (на нём обычно дописывают строки).
        if is_first:
            to_fetch = [normalize_sheet_title(str(s.get("title") or "")) for s in weeks]
        else:
            unknown = [
                normalize_sheet_title(str(s.get("title") or ""))
                for s in weeks
                if normalize_sheet_title(str(s.get("title") or "")) not in known
            ]
            newest = normalize_sheet_title(str(weeks[-1].get("title") or ""))
            to_fetch = list(dict.fromkeys([*unknown, newest]))

        await self.db.vyrobotka_set_sync_state(
            status="running",
            total=len(to_fetch),
            done=0,
            message=(
                f"{'Первый слепок' if is_first else 'Инкремент'}: "
                f"{len(to_fetch)} лист(ов)…"
            ),
        )

        ranges = [client.a1_range(t) for t in to_fetch]
        values_map = await client.batch_get_values(sid, ranges)

        updated = 0
        skipped_same = 0
        for idx, title in enumerate(to_fetch):
            rng = client.a1_range(title)
            values = values_map.get(rng) or []
            if not values:
                for k, v in values_map.items():
                    if k.split("!", 1)[0].strip("'") == title:
                        values = v
                        break
            rows = parse_week_rows(title, values)
            for r in rows:
                r["spreadsheet_id"] = sid
            prev = known.get(title) or {}
            prev_n = int(prev.get("tickets_count") or prev.get("row_count") or 0)
            sheet_id = (title_to_meta.get(title) or {}).get("sheet_id")
            stats = aggregate_sheet_upsell(title, rows)
            stats["spreadsheet_id"] = sid
            stats["spreadsheet_title"] = probe.get("title")
            stats["sheet_id"] = sheet_id
            stats["row_count"] = len(rows)

            # Уже известный лист без новых квитанций — не затираем первый слепок
            if not is_first and title in known and len(rows) <= prev_n:
                prev_stats = dict(prev)
                prev_stats["sheet_id"] = sheet_id
                prev_stats["spreadsheet_title"] = probe.get("title")
                await self.db.vyrobotka_touch_sheet_meta(prev_stats)
                skipped_same += 1
            else:
                await self.db.vyrobotka_replace_sheet_rows(
                    spreadsheet_id=sid,
                    sheet_title=title,
                    rows=rows,
                    sheet_stats=stats,
                )
                updated += 1

            await self.db.vyrobotka_set_sync_state(
                status="running",
                total=len(to_fetch),
                done=idx + 1,
                message=f"Лист {idx + 1}/{len(to_fetch)}: {title}",
            )

        # Подтянуть gid вкладок для ссылок (без перечитывания значений)
        for title, meta in title_to_meta.items():
            prev = known.get(title)
            if not prev:
                continue
            sid_val = meta.get("sheet_id")
            if sid_val is None or prev.get("sheet_id") == sid_val:
                continue
            st = dict(prev)
            st["sheet_id"] = sid_val
            st["spreadsheet_title"] = probe.get("title")
            await self.db.vyrobotka_touch_sheet_meta(st)

        # После первого полного прогона — зафиксировать слепок дебиторки по отчётам
        if is_first:
            all_rows = await self.db.vyrobotka_list_rows()
            underpaid = collect_underpaid_tickets(all_rows)
            await self.db.vyrobotka_set_debt_baseline(
                day=date.today().isoformat(),
                sheets_debt_sum=round(sum(float(t.get("debt") or 0) for t in underpaid), 2),
                sheets_tickets=len(underpaid),
                tickets=underpaid,
                locked_at=_now(),
            )
        else:
            await self.ensure_debt_baseline()

        total_rows = len(await self.db.vyrobotka_list_rows())
        pages_note = ""
        try:
            exp = await self.export_pages_snapshot()
            pages_note = f", pages {exp.get('debt_table', exp.get('debt_tickets', 0))} долгов"
        except Exception:  # noqa: BLE001
            pages_note = ""
        await self.db.vyrobotka_set_sync_state(
            status="idle",
            total=len(to_fetch),
            done=len(to_fetch),
            message=(
                f"Готово: {'первый слепок' if is_first else 'инкремент'} — "
                f"обновлено {updated} лист(ов), без изменений {skipped_same}; "
                f"в кэше {len(await self.db.vyrobotka_list_sheet_stats())} листов, "
                f"{total_rows} квитанций. "
                f"Таблица: {probe.get('title') or sid}{pages_note}"
            ),
            finished_at=_now(),
        )

    async def export_pages_snapshot(self, path: str | None = None) -> dict[str, Any]:
        """Собрать JSON для GitHub Pages (docs/vyrobotka/data.json)."""
        from pathlib import Path

        from modules.vyrobotka.export import (
            build_vyrobotka_pages_payload,
            write_vyrobotka_pages_json,
        )

        stats = await self.get_stats()
        sync = stats.get("sync") or {}
        sheets = stats.get("sheets") or []
        debt = stats.get("debt") or {}
        title = None
        if sheets:
            title = sheets[-1].get("spreadsheet_title")
        verify = debt.get("verify") or {}
        payload = build_vyrobotka_pages_payload(
            upsell_sheets=sheets,
            debt_table=debt.get("table") or [],
            debt_daily=debt.get("daily") or [],
            debt_baseline=debt.get("baseline"),
            debt_verify_message=verify.get("message"),
            sync=sync,
            spreadsheet_title=title,
        )
        out = write_vyrobotka_pages_json(payload, Path(path) if path else None)
        return {
            "ok": True,
            "path": str(out),
            "upsell_sheets": payload["counts"]["upsell_sheets"],
            "debt_table": payload["counts"]["debt_table"],
            "debt_daily": payload["counts"].get("debt_daily", 0),
            "exported_at": payload["exported_at"],
        }

    async def get_debt_verify(self) -> dict[str, Any]:
        state = await self.db.vyrobotka_get_debt_verify_state()
        # Только для ответа API: mismatch→norm при «Выдан»+без долга. БД не трогаем.
        rows = apply_display_verdicts(await self.db.vyrobotka_list_debt_verify_rows())
        # Предпочитаем отчёт сверки ledger (flags); иначе legacy verify_rows
        report = state.get("report")
        if not (isinstance(report, dict) and report.get("flags") is not None):
            table = await self.db.vyrobotka_list_debt_ledger(active_only=True)
            if table:
                report = self._ledger_verify_report(table)
            elif rows:
                report = build_verify_report(rows)
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

    async def _apply_ledger_classify(self, ticket: str) -> dict[str, Any]:
        row = await self.db.vyrobotka_get_debt_ledger_ticket(ticket)
        if not row:
            return {}
        result = classify_debt_row(row)
        await self.db.vyrobotka_upsert_debt_ledger(
            {
                "ticket": ticket,
                "active": result["active"],
                "flag": result.get("flag"),
                "flag_reason": result.get("flag_reason"),
            }
        )
        return {**row, **result}

    async def _merge_sheet_into_ledger(
        self, underpaid: list[dict[str, Any]]
    ) -> int:
        """Обновить sheet-поля ledger из недоплат отчётов (новые + baseline)."""
        n = 0
        for t in underpaid:
            oid = str(t.get("ticket") or "").strip()
            if not oid:
                continue
            debt = float(t.get("debt") or 0)
            payload: dict[str, Any] = {
                "ticket": oid,
                "active": 1,
                "sheet_title": t.get("sheet_title"),
                "master": t.get("master"),
                "sheet_total": t.get("total_repair"),
                "sheet_paid": t.get("paid"),
                "sheet_debt": debt,
                "report_amount": t.get("report_amount"),
                "first_sheet_total": t.get("total_repair"),
                "first_sheet_paid": t.get("paid"),
                "first_sheet_debt": debt,
            }
            await self.db.vyrobotka_upsert_debt_ledger(payload)
            n += 1
        return n

    async def _merge_crm_pay_list_into_ledger(
        self,
        pay_rows: list[dict[str, Any]],
        *,
        base_url: str,
    ) -> set[str]:
        """Upsert все квитанции с other=pay. Возвращает set ticket на списке."""
        on_list: set[str] = set()
        checked = _now()
        for r in pay_rows:
            oid = str(r.get("ticket") or "").strip()
            if not oid:
                continue
            on_list.add(oid)
            await self.db.vyrobotka_upsert_debt_ledger(
                {
                    "ticket": oid,
                    "active": 1,
                    "crm_total": r.get("cost"),
                    "crm_paid": r.get("paid"),
                    "crm_debt": r.get("debt"),
                    "crm_status": r.get("status"),
                    "on_pay_list": 1,
                    "crm_url": f"{base_url}/orders/{oid}",
                    "crm_checked_at": checked,
                    "first_crm_total": r.get("cost"),
                    "first_crm_paid": r.get("paid"),
                    "first_crm_debt": r.get("debt"),
                    "first_crm_status": r.get("status"),
                    "first_on_pay_list": 1,
                }
            )
        return on_list

    async def _run_debt_verify(self, mode: str = "all") -> None:
        """Сводка дебиторки: CRM other=pay + отчёты → ledger → classify."""
        all_rows = await self.db.vyrobotka_list_rows()
        underpaid_all = collect_underpaid_tickets(all_rows)
        await self.ensure_debt_baseline(underpaid_all)

        await self.db.vyrobotka_set_debt_verify_state(
            status="running",
            total=0,
            done=0,
            message="Тяну список CRM other=pay…",
            report=None,
            report_json=None,
            cancel_requested=0,
            started_at=_now(),
            finished_at=None,
        )
        assert self._gincore_client_factory is not None
        client = await self._gincore_client_factory()
        await client.ensure_login()

        # 1) Актуальный список CRM
        pay = await client.fetch_orders_expected_payment_list(
            crm_params=CRM_DEBT_LIST_PARAMS,
            page_pause_s=CRM_LIST_PAGE_PAUSE_S,
        )
        pay_rows = list(pay.get("rows") or [])
        on_list = await self._merge_crm_pay_list_into_ledger(
            pay_rows, base_url=str(getattr(client, "base_url", "") or "")
        )

        # 2) Отчёты мастеров → ledger (все текущие недоплаты / baseline уже в underpaid_all)
        await self.db.vyrobotka_set_debt_verify_state(
            message=f"CRM: {len(on_list)} квитанций · обновляю отчёты мастеров…",
        )
        sheet_merged = await self._merge_sheet_into_ledger(underpaid_all)

        # Квитанции, которые были на pay-list, а сейчас нет — сбросить on_pay_list
        existing = await self.db.vyrobotka_list_debt_ledger(active_only=False)
        flipped_off: set[str] = set()
        for row in existing:
            oid = str(row.get("ticket") or "")
            if not oid or oid in on_list:
                continue
            if int(row.get("on_pay_list") or 0):
                flipped_off.add(oid)
                await self.db.vyrobotka_upsert_debt_ledger(
                    {"ticket": oid, "on_pay_list": 0}
                )

        # 3) Кандидаты на HTML:
        #    — пропали с other=pay (подозрение на скрытие);
        #    — ещё нет сохранённой ленты комментариев (для карточки без Gincore).
        ledger = await self.db.vyrobotka_list_debt_ledger(active_only=True)
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in ledger:
            oid = str(row.get("ticket") or "")
            if not oid or oid in seen:
                continue
            expected = max(
                float(row.get("first_sheet_debt") or 0),
                float(row.get("first_crm_debt") or 0),
                float(row.get("sheet_debt") or 0),
            )
            need_miss = False
            if oid not in on_list:
                if expected > 1.0 or int(row.get("first_on_pay_list") or 0):
                    if mode == "new":
                        need_miss = oid in flipped_off or not row.get("crm_checked_at")
                    else:
                        need_miss = True
            need_feed = not row.get("crm_feed_json")
            if mode == "new" and need_feed and row.get("crm_feed_at"):
                # уже пытались сохранить ленту (пустую) — не долбим снова
                need_feed = False
            if need_miss or need_feed:
                candidates.append(row)
                seen.add(oid)

        await self.db.vyrobotka_set_debt_verify_state(
            status="running",
            total=len(candidates),
            done=0,
            message=(
                f"Pay-list {len(on_list)}, отчёты +{sheet_merged}. "
                f"HTML {len(candidates)} (пропавшие + без ленты)…"
            ),
        )

        checked_n = 0
        for i, row in enumerate(candidates):
            state = await self.db.vyrobotka_get_debt_verify_state()
            if int(state.get("cancel_requested") or 0):
                table = await self.db.vyrobotka_list_debt_ledger(active_only=True)
                report = self._ledger_verify_report(table)
                await self.db.vyrobotka_set_debt_verify_state(
                    status="idle",
                    done=i,
                    message=f"Остановлено: HTML {i}/{len(candidates)}",
                    report=report,
                    cancel_requested=0,
                    finished_at=_now(),
                )
                return

            oid = str(row.get("ticket") or "")
            await self.db.vyrobotka_set_debt_verify_state(
                status="running",
                total=len(candidates),
                done=i,
                message=f"Gincore HTML {i + 1}/{len(candidates)} · №{oid}",
            )
            sheet_stub = {
                "ticket": oid,
                "sheet_title": row.get("sheet_title"),
                "master": row.get("master"),
                "total_repair": row.get("sheet_total"),
                "paid": row.get("sheet_paid"),
                "debt": row.get("sheet_debt"),
            }
            compared = await self._verify_one(client, sheet_stub)
            feed = compared.get("live_feed")
            feed_json = (
                json.dumps(feed, ensure_ascii=False)
                if isinstance(feed, list)
                else "[]"
            )
            await self.db.vyrobotka_upsert_debt_ledger(
                {
                    "ticket": oid,
                    "crm_total": compared.get("crm_total"),
                    "crm_paid": compared.get("crm_paid"),
                    "crm_debt": compared.get("crm_debt"),
                    "crm_status": compared.get("crm_status"),
                    "crm_url": compared.get("crm_url"),
                    "on_pay_list": 1 if oid in on_list else 0,
                    "crm_checked_at": _now(),
                    "crm_feed_json": feed_json,
                    "crm_feed_at": _now(),
                    "first_crm_total": compared.get("crm_total"),
                    "first_crm_paid": compared.get("crm_paid"),
                    "first_crm_debt": compared.get("crm_debt"),
                    "first_crm_status": compared.get("crm_status"),
                }
            )
            # legacy verify row (для atypical/export совместимости)
            await self.db.vyrobotka_upsert_debt_verify_row(compared)
            await self._apply_ledger_classify(oid)
            checked_n += 1

            if i + 1 < len(candidates):
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

        # 4) Классифицировать всех на pay-list / обновлённых
        await self.db.vyrobotka_set_debt_verify_state(
            message="Классифицирую таблицу дебиторки…",
        )
        for row in await self.db.vyrobotka_list_debt_ledger(active_only=False):
            oid = str(row.get("ticket") or "")
            if not oid:
                continue
            # в mode=new не трогаем inactive уже снятые, кроме тех на pay-list
            if mode == "new" and not int(row.get("active") or 0) and oid not in on_list:
                continue
            await self._apply_ledger_classify(oid)

        table = await self.db.vyrobotka_list_debt_ledger(active_only=True)
        report = self._ledger_verify_report(table)
        counts = self._debt_table_counts(table)

        await self.db.vyrobotka_set_debt_verify_state(
            status="running",
            total=max(len(candidates), 1),
            done=len(candidates),
            message="Считаю общую дебиторку CRM…",
        )
        snap = await self._snapshot_debt_daily(
            client,
            source=f"verify-{mode}",
            crm_debt_sum=float(pay.get("expected_payment_sum") or 0),
            crm_orders=int(pay.get("orders") or pay.get("listed_total") or 0),
        )
        snap_msg = (
            f" · CRM {snap['crm_debt_sum']:.0f} / отчёты {snap['sheets_debt_sum']:.0f}"
            if snap
            else ""
        )
        prefix = "Сверка (новые)" if mode == "new" else "Сверка"
        await self.db.vyrobotka_set_debt_verify_state(
            status="idle",
            total=len(table),
            done=len(table),
            message=(
                f"{prefix}: в таблице {counts['total']} "
                f"(жёлтых {counts['yellow']}, красных {counts['red']}, "
                f"open {counts['open']}, mismatch {counts['mismatch']}); "
                f"HTML {checked_n}{snap_msg}"
            ),
            report=report,
            cancel_requested=0,
            finished_at=_now(),
        )
        await self._safe_export_pages()

    @staticmethod
    def _ledger_verify_report(table: list[dict[str, Any]]) -> dict[str, Any]:
        """Отчёт сверки из флагов ledger (для UI статуса)."""
        counts = {"ok": 0, "norm": 0, "mismatch": 0, "missing": 0, "error": 0}
        # map flags → legacy-ish counts for existing UI bits
        for r in table:
            f = str(r.get("flag") or "")
            if f == "yellow":
                counts["ok"] += 1
            elif f == "red":
                counts["mismatch"] += 1
            elif f == "mismatch":
                counts["mismatch"] += 1
            elif f == "open":
                counts["ok"] += 1
        bad = [r for r in table if r.get("flag") in {"red", "mismatch"}]
        bad.sort(
            key=lambda x: (
                -float(x.get("crm_debt") or x.get("sheet_debt") or 0),
                str(x.get("ticket") or ""),
            )
        )
        return {
            "total": len(table),
            "ok": counts["ok"],
            "norm": counts["norm"],
            "mismatch": counts["mismatch"],
            "missing": counts["missing"],
            "error": counts["error"],
            "bad_count": len(bad),
            "flags": {
                "red": sum(1 for r in table if r.get("flag") == "red"),
                "yellow": sum(1 for r in table if r.get("flag") == "yellow"),
                "open": sum(1 for r in table if r.get("flag") == "open"),
                "mismatch": sum(1 for r in table if r.get("flag") == "mismatch"),
            },
            "top_issues": [
                {
                    "ticket": r.get("ticket"),
                    "sheet_title": r.get("sheet_title"),
                    "verdict": r.get("flag"),
                    "summary": r.get("flag_reason"),
                    "sheet_debt": r.get("sheet_debt"),
                    "crm_debt": r.get("crm_debt"),
                    "field_diffs": {},
                }
                for r in bad[:40]
            ],
        }

    async def _snapshot_debt_daily(
        self,
        client: Any,
        *,
        source: str = "verify",
        day: date | None = None,
        crm_debt_sum: float | None = None,
        crm_orders: int | None = None,
    ) -> dict[str, Any] | None:
        """Одна точка в день: CRM обновляется; отчёты мастеров — только первый слепок."""
        underpaid_all = collect_underpaid_tickets(await self.db.vyrobotka_list_rows())
        baseline = await self.ensure_debt_baseline(underpaid_all)
        if baseline and baseline.get("sheets_debt_sum") is not None:
            sheets_debt_sum = float(baseline["sheets_debt_sum"])
            sheets_tickets = int(baseline.get("sheets_tickets") or 0)
        else:
            underpaid = self._filter_underpaid_by_baseline(underpaid_all, baseline)
            sheets_debt_sum = round(sum(float(t.get("debt") or 0) for t in underpaid), 2)
            sheets_tickets = len(underpaid)

        if crm_debt_sum is None:
            try:
                totals = await client.fetch_orders_expected_payment_sum(
                    crm_params=CRM_DEBT_LIST_PARAMS
                )
                crm_debt_sum = float(totals.get("expected_payment_sum") or 0)
                crm_orders = int(totals.get("orders") or totals.get("listed_total") or 0)
            except Exception:  # noqa: BLE001
                crm_debt_sum = None
                crm_orders = 0

        snap = {
            "day": (day or date.today()).isoformat(),
            "crm_debt_sum": crm_debt_sum,
            "sheets_debt_sum": sheets_debt_sum,
            "crm_orders": int(crm_orders or 0),
            "sheets_tickets": sheets_tickets,
            "source": source,
            "updated_at": _now(),
        }
        await self.db.vyrobotka_upsert_debt_daily(snap)
        return snap

    async def _safe_export_pages(self) -> None:
        try:
            await self.export_pages_snapshot()
        except Exception:  # noqa: BLE001
            pass

    async def pin_debt_daily_point(
        self,
        *,
        crm_debt_sum: float,
        day: date | None = None,
        source: str = "pin",
        crm_orders: int | None = None,
    ) -> dict[str, Any]:
        """Закрепить точку динамики (без полного прогона сверки)."""
        underpaid_all = collect_underpaid_tickets(await self.db.vyrobotka_list_rows())
        baseline = await self.ensure_debt_baseline(underpaid_all)
        if baseline and baseline.get("sheets_debt_sum") is not None:
            sheets_debt_sum = float(baseline["sheets_debt_sum"])
            sheets_tickets = int(baseline.get("sheets_tickets") or 0)
        else:
            sheets_debt_sum = round(sum(float(t.get("debt") or 0) for t in underpaid_all), 2)
            sheets_tickets = len(underpaid_all)
        snap = {
            "day": (day or date.today()).isoformat(),
            "crm_debt_sum": float(crm_debt_sum),
            "sheets_debt_sum": sheets_debt_sum,
            "crm_orders": int(crm_orders or 0),
            "sheets_tickets": sheets_tickets,
            "source": source,
            "updated_at": _now(),
        }
        await self.db.vyrobotka_upsert_debt_daily(snap)
        await self._safe_export_pages()
        return snap

    async def _verify_one(self, client: Any, ticket: dict[str, Any]) -> dict[str, Any]:
        from modules.gincore.client import GincoreError

        oid = str(ticket.get("ticket") or "").strip()
        url = f"{getattr(client, 'base_url', '')}/orders/{oid}"

        def _pack(html: str | None, **kwargs: Any) -> dict[str, Any]:
            out = compare_ticket_with_crm(ticket, **kwargs)
            feed: list[dict[str, Any]] = []
            if html:
                try:
                    feed = client.parse_order_live_feed(html) or []
                except Exception:  # noqa: BLE001
                    feed = []
            out["live_feed"] = feed
            return out

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
                return _pack(html, missing=True, crm_url=url)
            return _pack(
                html,
                crm_total=crm_total,
                crm_paid=crm_paid,
                crm_debt=crm_debt,
                crm_status=status.get("status_name"),
                crm_url=url,
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
                    return _pack(
                        html,
                        crm_total=crm_total,
                        crm_paid=crm_paid,
                        crm_debt=crm_debt,
                        crm_status=status.get("status_name"),
                        crm_url=url,
                    )
                except Exception as exc2:  # noqa: BLE001
                    return _pack(None, error=str(exc2), crm_url=url)
            if "404" in msg or "не найден" in msg.casefold():
                return _pack(None, missing=True, crm_url=url)
            return _pack(None, error=msg, crm_url=url)
        except Exception as exc:  # noqa: BLE001
            return _pack(None, error=str(exc), crm_url=url)
