"""Минимальный клиент Google Sheets API (service account, read-only)."""

from __future__ import annotations

import json
from typing import Any

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",)
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"


class SheetsError(RuntimeError):
    pass


def credentials_from_json(raw: str) -> service_account.Credentials:
    text = (raw or "").strip()
    if not text:
        raise SheetsError("Пустой JSON ключа service account")
    try:
        info = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SheetsError("Некорректный JSON ключа service account") from exc
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise SheetsError("Ожидается JSON с type=service_account")
    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)


class GoogleSheetsClient:
    def __init__(self, credentials_json: str) -> None:
        self._creds = credentials_from_json(credentials_json)

    def _token(self) -> str:
        if not self._creds.valid:
            self._creds.refresh(Request())
        if not self._creds.token:
            raise SheetsError("Не удалось получить access token Google")
        return self._creds.token

    @property
    def client_email(self) -> str:
        return str(getattr(self._creds, "service_account_email", "") or "")

    async def _get(
        self,
        url: str,
        *,
        params: dict[str, Any] | list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token()}"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.get(url, headers=headers, params=params)
            data = res.json() if res.content else {}
            if res.status_code >= 400:
                err = data.get("error") if isinstance(data, dict) else None
                msg = ""
                if isinstance(err, dict):
                    msg = err.get("message") or json.dumps(err, ensure_ascii=False)
                raise SheetsError(msg or f"Google Sheets API HTTP {res.status_code}")
            if not isinstance(data, dict):
                raise SheetsError("Неожиданный ответ Sheets API")
            return data

    async def probe(self, spreadsheet_id: str) -> dict[str, Any]:
        """Проверка доступа: метаданные таблицы + список листов."""
        sid = (spreadsheet_id or "").strip()
        if not sid:
            raise SheetsError("Не указан ID таблицы (spreadsheet_id)")
        meta = await self._get(
            f"{SHEETS_API}/{sid}",
            params={"fields": "spreadsheetId,properties.title,sheets.properties"},
        )
        sheets_out: list[dict[str, Any]] = []
        for sh in meta.get("sheets") or []:
            props = sh.get("properties") or {}
            sheets_out.append(
                {
                    "sheet_id": props.get("sheetId"),
                    "title": props.get("title") or "",
                    "index": props.get("index"),
                }
            )
        title = ((meta.get("properties") or {}).get("title")) or sid
        return {
            "spreadsheet_id": meta.get("spreadsheetId") or sid,
            "title": title,
            "sheets": sheets_out,
            "sheets_count": len(sheets_out),
            "client_email": self.client_email,
        }

    @staticmethod
    def a1_range(sheet_title: str, cells: str = "A:O") -> str:
        title = (sheet_title or "").replace("'", "''")
        return f"'{title}'!{cells}"

    async def batch_get_values(
        self,
        spreadsheet_id: str,
        ranges: list[str],
        *,
        chunk_size: int = 40,
    ) -> dict[str, list[list[Any]]]:
        """Читает несколько диапазонов; ключ — исходный range A1."""
        sid = (spreadsheet_id or "").strip()
        if not sid:
            raise SheetsError("Не указан ID таблицы (spreadsheet_id)")
        out: dict[str, list[list[Any]]] = {}
        if not ranges:
            return out
        for i in range(0, len(ranges), max(1, chunk_size)):
            chunk = ranges[i : i + chunk_size]
            params: list[tuple[str, str]] = [
                ("valueRenderOption", "UNFORMATTED_VALUE"),
                ("majorDimension", "ROWS"),
            ]
            for r in chunk:
                params.append(("ranges", r))
            data = await self._get(
                f"{SHEETS_API}/{sid}/values:batchGet",
                params=params,
            )
            for vr in data.get("valueRanges") or []:
                rng = str(vr.get("range") or "")
                values = vr.get("values") or []
                if not isinstance(values, list):
                    values = []
                # Сопоставить с запрошенным range: API может вернуть Sheet!A1:O99
                matched = None
                for req in chunk:
                    # req вида 'Title'!A:O — сравниваем по имени листа
                    req_title = req.split("!", 1)[0].strip("'")
                    resp_title = rng.split("!", 1)[0].strip("'")
                    if req_title == resp_title:
                        matched = req
                        break
                out[matched or rng] = values
        return out
