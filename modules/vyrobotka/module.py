"""Модуль «Выработка»: подключение к Google Sheets."""

from __future__ import annotations

from typing import Any

from modules.base import BaseModule, SettingField
from modules.vyrobotka.sheets import GoogleSheetsClient, SheetsError


class VyrobotkaModule(BaseModule):
    id = "vyrobotka"
    name = "Выработка"
    description = (
        "Google Таблица прибыльности: синхронизация недельных листов "
        "и статистика досогласований."
    )

    def settings_schema(self) -> list[SettingField]:
        return [
            SettingField(
                key="spreadsheet_id",
                label="ID таблицы Google",
                type="text",
                placeholder="1ardPmT-a-eyFZmEk97J70aPiirlLDhoySCXlauZbT-c",
                help="Из URL: docs.google.com/spreadsheets/d/<ВОТ_ЭТОТ_ID>/edit",
            ),
            SettingField(
                key="service_account_json",
                label="JSON ключ service account",
                type="textarea",
                secret=True,
                help="Вставьте целиком содержимое скачанного JSON-ключа Google Cloud.",
            ),
            SettingField(key="enabled", label="Модуль включён", type="checkbox"),
        ]

    async def test_connection(self, settings: dict[str, Any]) -> dict[str, Any]:
        if settings.get("enabled") is False:
            raise SheetsError("Модуль «Выработка» выключен")
        raw = settings.get("service_account_json") or ""
        if not raw or raw == "********":
            raise SheetsError("Сначала вставьте JSON ключ service account и сохраните настройки")
        sid = (settings.get("spreadsheet_id") or "").strip()
        client = GoogleSheetsClient(raw)
        probe = await client.probe(sid)
        return {"ok": True, **probe}
