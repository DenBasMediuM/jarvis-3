from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from openai import AsyncOpenAI

from modules.base import ToolSpec
from modules.gincore.charts import finalize_visuals


def _collect_cash_journals(tool_traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in tool_traces:
        result = t.get("result")
        if isinstance(result, dict) and isinstance(result.get("cash_journal"), dict):
            out.append(result["cash_journal"])
    return out


_ORDER_NUM_RE = re.compile(r"\b\d{4,}\s*[+\-−–]")
_OPENING_CASH_RE = re.compile(r"касс?[аыу]?\s*[:\-–—]\s*\d", re.IGNORECASE)
_OPENING_CARD_RE = re.compile(r"карт[аыу]?\s*[:\-–—]\s*\d", re.IGNORECASE)


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user" and isinstance(msg.get("content"), str):
            return msg["content"]
    return ""


def _prefer_verbatim_journal(user_text: str, tool_text: str) -> str:
    """Если модель выкинула номера квитанций из text — взять исходное сообщение пользователя."""
    user = user_text or ""
    tool = tool_text or ""
    if not user.strip():
        return tool
    user_orders = len(_ORDER_NUM_RE.findall(user))
    tool_orders = len(_ORDER_NUM_RE.findall(tool))
    if user_orders > tool_orders:
        return user
    user_has_open = bool(_OPENING_CASH_RE.search(user) or _OPENING_CARD_RE.search(user))
    tool_has_open = bool(_OPENING_CASH_RE.search(tool) or _OPENING_CARD_RE.search(tool))
    if user_has_open and not tool_has_open:
        return user
    # также если модель сильно ужалила журнал (мало строк), а у пользователя полный чат
    if user.count("\n") >= tool.count("\n") + 3 and user_orders >= tool_orders:
        if "касс" in user.lower() or _ORDER_NUM_RE.search(user):
            return user
    return tool


SYSTEM_PROMPT = """Ты — Jarvis, локальный личный ассистент пользователя.
Помогаешь с личными вопросами, планами и задачами.
Доступен модуль Gincore CRM. В нём РАЗНЫЕ разделы — не всё через кассы.

Сегодня: {today_iso} ({today_ru}). Текущий год: {year}.
Относительные периоды считай от этой даты. Не угадывай год из обучения модели.

Сведение кассы из чата / журнала («свести кассу», «Касса: … Карта: …», операции Vikki):
→ один вызов reconcile_cash_journal с полным текстом журнала.
text = РОВНО сообщение пользователя (copy-paste), БЕЗ правок.
НЕ удаляй номера квитанций/заказов (122990 +1000, 123122 -505) — они обязательны.
НЕ сокращай строки до «+1000» / «-505 на зп». НЕ нормализуй и НЕ переписывай операции.
НЕ gincore_cashbox_balance. НЕ считай итоги сам — только closing_cash / closing_card
из результата инструмента (они совпадают с блоком UI).
Разбор транзакций делает ТОЛЬКО код инструмента — НЕ предлагай proposed_ops,
НЕ вызывай инструмент повторно, НЕ додумывай суммы по нераспознанным строкам.
В ответе: 1–2 предложения + итоговые остатки из closing_*. Не перечисляй операции —
они в интерактивном блоке, пользователь правит кнопками.
«на карту» / «на счёт ФОП» — отдельные корзины; расшифровку ЗЧ инструмент не дублирует.

Маршрутизация Gincore:
- Деньги / статьи / зарплаты / аренда / транзакции → gincore_query
- Остаток кассы В CRM по имени точки → gincore_cashbox_balance
- Ремонты / устройства / заказы на ремонт → gincore_repair_orders
  (раздел /orders#show_repair_orders). НЕ через кассы и gincore_query.
  Фильтры (можно комбинировать): current, status, engineer, manager, accepter,
  location, repair_type, person, other, client, device, defect, channel, order_id.
  «Сейчас в ремонте» → current=true; «у мастера X» → engineer=X;
  «в удаленном сервисе» → status=В удаленном сервисе;
  «на Левитане» → location=Левитан; «постоянные клиенты» → channel=Постоянные клиенты (+ current);
  «срочные» → other=срочные; «юрлица» → person=юр.
  Не подставляй period=this_year для «сейчас»-вопросов.
  «Принято в ремонт» за период → period + group_by=month|total.
  Сравнение за N лет → years_count=N, group_by=month.

gincore_query: category? / contractor? / group_by / period или years / years_count.
Сравнение за N лет = один вызов с years или years_count.

Правила:
- Для CRM и сведения кассы всегда вызывай нужный инструмент; не выдумывай цифры.
- По-русски, кратко; деньги — UAH с разделителями тысяч.
- UI рисует charts/tables сам — не копируй таблицы markdown'ом и не вставляй ![...](…).
"""


def build_system_prompt(today: date | None = None) -> str:
    today = today or date.today()
    return SYSTEM_PROMPT.format(
        today_iso=today.isoformat(),
        today_ru=today.strftime("%d.%m.%Y"),
        year=today.year,
    )

class LLMService:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        tools: list[ToolSpec],
    ) -> None:
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.tools = {t.name: t for t in tools}

    def openai_tools(self) -> list[dict[str, Any]]:
        result = []
        for tool in self.tools.values():
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )
        return result

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tool_rounds: int = 6,
    ) -> dict[str, Any]:
        history = [{"role": "system", "content": build_system_prompt()}, *messages]
        tool_traces: list[dict[str, Any]] = []

        for _ in range(max_tool_rounds):
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": history,
            }
            tools = self.openai_tools()
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = await self.client.chat.completions.create(**kwargs)
            message = response.choices[0].message
            tool_calls = message.tool_calls or []

            if not tool_calls:
                content = message.content or ""
                charts_out, tables_out = finalize_visuals(
                    [t.get("result") for t in tool_traces]
                )
                return {
                    "content": content,
                    "tool_traces": tool_traces,
                    "charts": charts_out,
                    "tables": tables_out,
                    "cash_journals": _collect_cash_journals(tool_traces),
                }

            history.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            for tc in tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                if name == "reconcile_cash_journal" and isinstance(args, dict):
                    args["text"] = _prefer_verbatim_journal(
                        _last_user_text(messages),
                        str(args.get("text") or ""),
                    )

                tool = self.tools.get(name)
                if not tool:
                    result: Any = {"error": f"Unknown tool: {name}"}
                else:
                    try:
                        result = await tool.handler(args)
                    except Exception as exc:  # noqa: BLE001 - surface to model
                        result = {"error": str(exc)}

                # Never send huge row dumps to the model — only aggregates/samples.
                if isinstance(result, dict) and "rows" in result:
                    result = {k: v for k, v in result.items() if k != "rows"}

                tool_traces.append({"tool": name, "args": args, "result": result})
                history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str)[:20000],
                    }
                )

        charts_out, tables_out = finalize_visuals([t.get("result") for t in tool_traces])
        return {
            "content": "Достигнут лимит вызовов инструментов. Попробуйте уточнить запрос.",
            "tool_traces": tool_traces,
            "charts": charts_out,
            "tables": tables_out,
            "cash_journals": _collect_cash_journals(tool_traces),
        }
