"""Клиент админ-API Worker'а jarvis-feedback (заявки «Улучшения»)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

# Не импортируем core.config: core/__init__ тянет core.main → циклический импорт.
ROOT = Path(__file__).resolve().parents[2]

STATUSES: dict[str, str] = {
    "new": "На рассмотрении",
    "approved": "Одобрено",
    "in_progress": "В работе",
    "done": "Готово",
    "rejected": "Отклонено",
}

TYPES: dict[str, str] = {
    "feature": "Новая функция",
    "improvement": "Улучшение",
    "bug": "Ошибка",
    "data": "Данные / расчёты",
    "ux": "Удобство / интерфейс",
    "other": "Другое",
}


class FeedbackError(RuntimeError):
    pass


def product_doc_path() -> Path:
    return ROOT / "PRODUCT.md"


def intake_rules_path() -> Path:
    return ROOT / "workers" / "feedback" / "intake_rules.md"


def validate_update(body: dict[str, Any]) -> dict[str, Any]:
    """Проверить решение администратора до отправки в Worker."""
    out: dict[str, Any] = {}
    if body.get("status") is not None:
        status = str(body["status"])
        if status not in STATUSES:
            raise ValueError(f"Неизвестный статус: {status}")
        out["status"] = status
    if body.get("admin_comment") is not None:
        out["admin_comment"] = str(body["admin_comment"]).strip()[:2000]
    if "priority" in body:
        pr = body.get("priority")
        out["priority"] = None if pr in (None, "") else int(pr)
    if out.get("status") == "rejected" and not out.get("admin_comment"):
        raise ValueError("Укажите причину отклонения — её увидит автор заявки")
    if not out:
        raise ValueError("Нечего сохранять")
    return out


def summarize(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {k: 0 for k in STATUSES}
    for it in items:
        st = it.get("status")
        if st in counts:
            counts[st] += 1
    return counts


class FeedbackClient:
    def __init__(
        self,
        base_url: str,
        admin_key: str,
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.admin_key = admin_key or ""
        self.timeout = timeout
        self._transport = transport  # для тестов (httpx.MockTransport)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.admin_key)

    async def _request(self, method: str, path: str, json: Any = None) -> dict[str, Any]:
        if not self.configured:
            raise FeedbackError(
                "Модуль «Улучшения» не настроен: задайте JARVIS_FEEDBACK_URL и "
                "JARVIS_FEEDBACK_ADMIN_KEY в .env"
            )
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            try:
                res = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=json,
                    headers={"Authorization": f"Bearer {self.admin_key}"},
                )
            except httpx.HTTPError as exc:
                raise FeedbackError(f"Worker недоступен: {exc}") from exc
        try:
            data = res.json()
        except ValueError:
            data = {}
        if res.status_code >= 400 or data.get("ok") is False:
            msg = data.get("message") or data.get("error") or res.text[:200]
            raise FeedbackError(f"Worker {res.status_code}: {msg}")
        return data

    async def list_requests(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/admin/requests")
        return list(data.get("items") or [])

    async def update_request(self, request_id: int, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/admin/requests/{int(request_id)}", json=body)

    async def push_product(self, markdown: str | None = None) -> dict[str, Any]:
        text = markdown if markdown is not None else product_doc_path().read_text(encoding="utf-8")
        return await self._request("PUT", "/admin/product", json={"markdown": text})

    async def product_status(self) -> dict[str, Any]:
        return await self._request("GET", "/admin/product")

    async def push_config(self, *, rules: str | None = None, model: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if rules is not None:
            body["rules"] = rules
        if model is not None:
            body["model"] = model
        return await self._request("PUT", "/admin/config", json=body)

    async def push_rules(self) -> dict[str, Any]:
        return await self.push_config(rules=intake_rules_path().read_text(encoding="utf-8"))

    async def get_config(self) -> dict[str, Any]:
        return await self._request("GET", "/admin/config")

    async def simulate(
        self,
        messages: list[dict[str, str]],
        *,
        context: dict[str, Any] | None = None,
        rounds: int = 0,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Прогнать диалог через ИИ без сохранения (настройка промпта)."""
        return await self._request(
            "POST",
            "/admin/simulate",
            json={"messages": messages, "context": context or {}, "rounds": rounds, "model": model or ""},
        )
