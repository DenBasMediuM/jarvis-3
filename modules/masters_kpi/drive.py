"""Google Drive + Sheets клиент для отчётов мастеров."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from urllib.parse import quote

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
)
DRIVE_API = "https://www.googleapis.com/drive/v3"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"

MIME_FOLDER = "application/vnd.google-apps.folder"
MIME_SHEET = "application/vnd.google-apps.spreadsheet"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class MastersDriveError(RuntimeError):
    pass


def credentials_from_json(raw: str) -> service_account.Credentials:
    text = (raw or "").strip()
    if not text:
        raise MastersDriveError("Пустой JSON ключа service account")
    try:
        info = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MastersDriveError("Некорректный JSON ключа service account") from exc
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise MastersDriveError("Ожидается JSON с type=service_account")
    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)


class MastersDriveClient:
    def __init__(self, credentials_json: str) -> None:
        self._creds = credentials_from_json(credentials_json)

    def _token(self) -> str:
        if not self._creds.valid:
            self._creds.refresh(Request())
        if not self._creds.token:
            raise MastersDriveError("Не удалось получить access token Google")
        return self._creds.token

    @property
    def client_email(self) -> str:
        return str(getattr(self._creds, "service_account_email", "") or "")

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        raw: bool = False,
        retries: int = 4,
    ) -> Any:
        import asyncio

        last_err: Exception | None = None
        for attempt in range(max(1, retries)):
            try:
                headers = {"Authorization": f"Bearer {self._token()}"}
                async with httpx.AsyncClient(timeout=90.0) as client:
                    res = await client.request(
                        method, url, headers=headers, params=params
                    )
                    if raw:
                        if res.status_code in {429, 500, 502, 503, 504} and attempt + 1 < retries:
                            await asyncio.sleep(1.5 * (attempt + 1))
                            continue
                        if res.status_code >= 400:
                            raise MastersDriveError(
                                f"Drive HTTP {res.status_code}: {res.text[:300]}"
                            )
                        return res.content
                    data = res.json() if res.content else {}
                    if res.status_code in {429, 500, 502, 503, 504} and attempt + 1 < retries:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    if res.status_code >= 400:
                        err = data.get("error") if isinstance(data, dict) else None
                        msg = ""
                        if isinstance(err, dict):
                            msg = err.get("message") or json.dumps(
                                err, ensure_ascii=False
                            )
                        raise MastersDriveError(
                            msg or f"Google API HTTP {res.status_code}"
                        )
                    return data
            except (httpx.TransportError, MastersDriveError) as exc:
                last_err = exc
                if attempt + 1 >= retries:
                    break
                await asyncio.sleep(1.5 * (attempt + 1))
        raise MastersDriveError(str(last_err) if last_err else "Google API error")

    async def list_children(self, folder_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "q": f"'{folder_id}' in parents and trashed=false",
                "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,size)",
                "pageSize": 100,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
                "orderBy": "name",
            }
            if page_token:
                params["pageToken"] = page_token
            data = await self._request("GET", f"{DRIVE_API}/files", params=params)
            out.extend(data.get("files") or [])
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return out

    async def list_master_folders(self, root_id: str) -> list[dict[str, Any]]:
        kids = await self.list_children(root_id)
        return [
            {
                "id": f["id"],
                "name": f.get("name") or "",
                "mimeType": f.get("mimeType"),
            }
            for f in kids
            if f.get("mimeType") == MIME_FOLDER
        ]

    async def list_report_files(self, folder_id: str) -> list[dict[str, Any]]:
        kids = await self.list_children(folder_id)
        out = []
        for f in kids:
            mime = f.get("mimeType") or ""
            name = f.get("name") or ""
            if mime in {MIME_SHEET, MIME_XLSX} or name.lower().endswith(".xlsx"):
                out.append(
                    {
                        "id": f["id"],
                        "name": name,
                        "mimeType": mime,
                        "modifiedTime": f.get("modifiedTime"),
                    }
                )
        return out

    async def read_sheet_values(self, spreadsheet_id: str) -> tuple[str, list[list[Any]]]:
        meta = await self._request(
            "GET",
            f"{SHEETS_API}/{spreadsheet_id}",
            params={"fields": "spreadsheetId,properties.title,sheets.properties"},
        )
        sheets = meta.get("sheets") or []
        if not sheets:
            return str((meta.get("properties") or {}).get("title") or ""), []
        # Берём первый лист (отчёты однолистовые).
        title = sheets[0]["properties"]["title"]
        rng = quote(f"{title}!A:Z")
        data = await self._request(
            "GET",
            f"{SHEETS_API}/{spreadsheet_id}/values/{rng}",
            params={
                "valueRenderOption": "UNFORMATTED_VALUE",
                "dateTimeRenderOption": "SERIAL_NUMBER",
            },
        )
        values = data.get("values") or []
        book_title = str((meta.get("properties") or {}).get("title") or title)
        return book_title, values if isinstance(values, list) else []

    async def read_xlsx_values(self, file_id: str) -> list[list[Any]]:
        content = await self._request(
            "GET",
            f"{DRIVE_API}/files/{file_id}",
            params={"alt": "media", "supportsAllDrives": "true"},
            raw=True,
        )
        try:
            import openpyxl
        except ImportError as exc:
            raise MastersDriveError("Нужен пакет openpyxl для xlsx") from exc
        wb = openpyxl.load_workbook(BytesIO(content), data_only=True, read_only=True)
        try:
            ws = wb.active
            rows: list[list[Any]] = []
            for row in ws.iter_rows(values_only=True):
                rows.append(list(row[:26]))
            return rows
        finally:
            wb.close()
