"""Синхронизация Google Sheets → локальный кэш и статистика «Выработка»."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from core.db import Database
from modules.vyrobotka.parse import (
    aggregate_sheet_upsell,
    normalize_sheet_title,
    parse_week_rows,
    select_week_sheets,
)
from modules.vyrobotka.sheets import GoogleSheetsClient, SheetsError

SettingsProvider = Callable[[], Awaitable[dict[str, Any]]]

_sync_lock = asyncio.Lock()
_sync_task: asyncio.Task | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VyrobotkaService:
    def __init__(self, db: Database, settings_provider: SettingsProvider) -> None:
        self.db = db
        self._settings_provider = settings_provider

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
        return {
            "ok": True,
            "sheets": sheets,
            "sync": sync,
            "sheets_count": len(sheets),
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
