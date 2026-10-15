"""Синхронизация Google Sheets → локальный кэш и статистика «Выработка»."""

from __future__ import annotations

import asyncio
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
            pages_note = f", pages {exp.get('debt_tickets', 0)} долгов"
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
        verify_rows = (debt.get("verify") or {}).get("rows") or []
        payload = build_vyrobotka_pages_payload(
            upsell_sheets=sheets,
            debt_sheets=debt.get("sheets") or [],
            debt_tickets=debt.get("tickets") or [],
            sync=sync,
            spreadsheet_title=title,
            verify_rows=verify_rows,
            debt_daily=debt.get("daily") or [],
        )
        out = write_vyrobotka_pages_json(payload, Path(path) if path else None)
        return {
            "ok": True,
            "path": str(out),
            "upsell_sheets": payload["counts"]["upsell_sheets"],
            "debt_tickets": payload["counts"]["debt_tickets"],
            "debt_daily": payload["counts"].get("debt_daily", 0),
            "exported_at": payload["exported_at"],
        }

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
        assert self._gincore_client_factory is not None
        client = await self._gincore_client_factory()
        await client.ensure_login()

        if not tickets:
            # для mode=new сохраняем прошлый отчёт по всем уже проверенным
            all_checked = await self.db.vyrobotka_list_debt_verify_rows() if mode == "new" else []
            report = build_verify_report(all_checked)
            snap = await self._snapshot_debt_daily(client, source=f"verify-{mode}")
            snap_msg = (
                f" · дебиторка CRM {snap['crm_debt_sum']:.0f} / отчёты {snap['sheets_debt_sum']:.0f}"
                if snap
                else ""
            )
            msg = (
                "Нет новых недоплаченных квитанций — всё уже сверено"
                if mode == "new"
                else "Нет недоплаченных квитанций для сверки"
            )
            await self.db.vyrobotka_set_debt_verify_state(
                status="idle",
                done=0,
                total=0 if mode != "new" else len(all_checked),
                message=f"{msg}{snap_msg}",
                report=report,
                finished_at=_now(),
            )
            await self._safe_export_pages()
            return

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
            status="running",
            total=len(all_checked),
            done=len(all_checked),
            message="Считаю общую дебиторку CRM (ожидаемая оплата)…",
        )
        snap = await self._snapshot_debt_daily(client, source=f"verify-{mode}")
        snap_msg = (
            f" · дебиторка CRM {snap['crm_debt_sum']:.0f} / отчёты {snap['sheets_debt_sum']:.0f}"
            if snap
            else ""
        )
        await self.db.vyrobotka_set_debt_verify_state(
            status="idle",
            total=len(all_checked),
            done=len(all_checked),
            message=(
                f"{prefix}: в этом запуске {len(batch_results)}; "
                f"всего ок {report['ok']}, "
                f"расхождений {report['mismatch']}, "
                f"нет в CRM {report['missing']}, "
                f"ошибок {report['error']}{snap_msg}"
            ),
            report=report,
            cancel_requested=0,
            finished_at=_now(),
        )
        await self._safe_export_pages()

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
