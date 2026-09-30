from __future__ import annotations

from typing import Any

from modules.base import BaseModule, ToolSpec
from modules.cash_journal.parser import reconcile_cash_journal


class CashJournalModule(BaseModule):
    id = "cash_journal"
    name = "Сведение кассы"
    description = (
        "Разбор журнала кассы из чата (касса / карта / ФОП) без CRM. "
        "Только детерминированный парсер; расшифровки ЗЧ не дублируют списание. "
        "Нераспознанные строки — в UI для ручной пометки."
    )

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="reconcile_cash_journal",
                description=(
                    "Свести кассу из текста чата/журнала. "
                    "text — РОВНО полный текст пользователя (copy-paste), без правок. "
                    "ОБЯЗАТЕЛЬНО сохрани номера квитанций: «122990 +1000», «123122 -505 на зп». "
                    "НЕ сокращай до «+1000» / «-505». "
                    "Разбор только кодом (без ИИ-уточнений). "
                    "Считает кассу/карту/ФОП; расшифровку ЗЧ не дублирует. "
                    "Нераспознанные строки попадают в блок UI — пользователь правит кнопками. "
                    "НЕ вызывай инструмент повторно. НЕ gincore_cashbox_balance. "
                    "НЕ складывай суммы сам — бери closing_cash / closing_card."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": (
                                "Полный текст журнала из чата КАК ЕСТЬ, "
                                "включая номера заказов/квитанций перед +/− суммой"
                            ),
                        },
                        "opening_cash": {
                            "type": "number",
                            "description": "Стартовая касса только если в text нет строки «Касса: …»",
                        },
                        "opening_card": {
                            "type": "number",
                            "description": "Стартовая карта только если в text нет строки «Карта: …»",
                        },
                        "opening_fop": {
                            "type": "number",
                            "description": "Стартовый остаток ФОП (обычно 0)",
                        },
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
                handler=self._reconcile,
            )
        ]

    async def _reconcile(self, args: dict[str, Any]) -> Any:
        text = args.get("text") or ""
        return reconcile_cash_journal(
            text,
            opening_cash=args.get("opening_cash"),
            opening_card=args.get("opening_card"),
            opening_fop=args.get("opening_fop"),
        )
