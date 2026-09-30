from __future__ import annotations

from datetime import date
from typing import Any, Callable

from modules.base import BaseModule, SettingField, ToolSpec
from modules.gincore.client import GincoreClient, GincoreError, month_bounds, year_bounds


class GincoreModule(BaseModule):
    id = "gincore"
    name = "Gincore CRM"
    description = (
        "CRM Gincore: кассы и денежные транзакции. "
        "Основной инструмент — gincore_query (фильтры + группировка + серии периодов)."
    )

    def __init__(self) -> None:
        self._settings_provider: Callable[[], dict[str, Any]] | None = None

    def bind_settings_provider(self, provider: Callable[[], dict[str, Any]]) -> None:
        self._settings_provider = provider

    def settings_schema(self) -> list[SettingField]:
        return [
            SettingField(
                key="base_url",
                label="URL CRM",
                type="url",
                placeholder="https://itserviceoutsourcing.gincore.net",
            ),
            SettingField(key="login", label="Логин", type="text"),
            SettingField(
                key="password",
                label="Пароль",
                type="password",
                secret=True,
                help="Хранится локально в зашифрованном виде",
            ),
            SettingField(key="enabled", label="Модуль включён", type="checkbox"),
        ]

    def _cfg(self) -> dict[str, Any]:
        return (self._settings_provider() if self._settings_provider else {}) or {}

    def _client(self) -> GincoreClient:
        cfg = self._cfg()
        base_url = (cfg.get("base_url") or "").strip()
        login = (cfg.get("login") or "").strip()
        password = cfg.get("password") or ""
        if not base_url or not login or not password:
            raise GincoreError("Укажите URL, логин и пароль Gincore в настройках модуля")
        if cfg.get("enabled") is False:
            raise GincoreError("Модуль Gincore выключен")
        return GincoreClient(base_url=base_url, login=login, password=password)

    def _resolve_period(self, args: dict[str, Any]) -> tuple[str, str]:
        if args.get("date_from") and args.get("date_to"):
            return args["date_from"], args["date_to"]
        if args.get("year") is not None:
            return year_bounds(int(args["year"]), clip_to_today=True)
        period = args.get("period") or "this_month"
        today = date.today()
        if period == "today":
            d = today.isoformat()
            return d, d
        if period == "this_month":
            return month_bounds(today.year, today.month)
        if period == "last_month":
            y, m = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
            return month_bounds(y, m)
        if period == "this_year":
            return year_bounds(today.year, clip_to_today=True)
        if period == "last_year":
            return year_bounds(today.year - 1)
        if period == "last_12_months":
            start = date(today.year - 1, today.month, 1)
            return start.isoformat(), today.isoformat()
        return month_bounds(today.year, today.month)

    def _resolve_ranges(self, args: dict[str, Any]) -> list[dict[str, str]]:
        """Build 1..N date ranges for a single query (comparisons = multiple ranges)."""
        ranges: list[dict[str, str]] = []

        years = args.get("years")
        if isinstance(years, list) and years:
            for y in years:
                df, dt = year_bounds(int(y), clip_to_today=True)
                ranges.append({"date_from": df, "date_to": dt, "label": str(int(y))})
            return ranges

        years_count = args.get("years_count")
        if years_count:
            n = max(1, min(int(years_count), 15))
            today = date.today()
            for y in range(today.year - n + 1, today.year + 1):
                df, dt = year_bounds(y, clip_to_today=True)
                ranges.append({"date_from": df, "date_to": dt, "label": str(y)})
            return ranges

        raw_ranges = args.get("ranges")
        if isinstance(raw_ranges, list) and raw_ranges:
            for item in raw_ranges:
                if not isinstance(item, dict):
                    continue
                df, dt = self._resolve_period(item)
                label = item.get("label") or (df[:4] if df[:4].isdigit() else df)
                ranges.append({"date_from": df, "date_to": dt, "label": str(label)})
            if ranges:
                return ranges

        # Single range from top-level period / dates / year
        df, dt = self._resolve_period(args)
        label = str(args.get("year") or df[:4])
        return [{"date_from": df, "date_to": dt, "label": label}]

    def tools(self) -> list[ToolSpec]:
        period_enum = ["today", "this_month", "last_month", "this_year", "last_year", "custom"]
        range_item = {
            "type": "object",
            "properties": {
                "period": {"type": "string", "enum": period_enum},
                "year": {"type": "integer", "description": "Календарный год"},
                "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                "label": {"type": "string", "description": "Подпись серии на графике/в таблице"},
            },
            "additionalProperties": False,
        }
        return [
            ToolSpec(
                name="gincore_query",
                description=(
                    "Универсальный запрос по деньгам в Gincore. "
                    "Фильтры: category?, contractor?. Группировка: group_by. "
                    "Периоды: либо один (period / year / date_from+date_to), "
                    "либо сразу несколько для сравнения на ОДНОМ графике и ОДНОЙ таблице — "
                    "years=[…] / years_count=N / ranges=[…]. "
                    "Сравнение за N лет (2, 3, 4…) = ОДИН вызов, не N вызовов. "
                    "Примеры: "
                    "зарплата Юре за месяц → category=зарплаты, contractor=Дубовой, period=this_month, group_by=total; "
                    "аренда в этом году → category=аренда, period=this_year, group_by=month; "
                    "аренда за 4 года → category=аренда, years_count=4, group_by=month; "
                    "сегодня → period=today, group_by=list."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "period": {
                            "type": "string",
                            "enum": period_enum,
                            "description": "Один период, если нет years/years_count/ranges",
                        },
                        "year": {
                            "type": "integer",
                            "description": "Один календарный год",
                        },
                        "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                        "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                        "years": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Явный список лет, напр. [2023,2024,2025,2026]",
                        },
                        "years_count": {
                            "type": "integer",
                            "description": (
                                "Сколько последних календарных лет включая текущий. "
                                "«За 4 года» → years_count=4."
                            ),
                        },
                        "ranges": {
                            "type": "array",
                            "items": range_item,
                            "description": "Произвольные периоды для сравнения, если не years",
                        },
                        "category": {
                            "type": "string",
                            "description": "Статья: аренда, зарплаты, хозтовары… Пусто = все",
                        },
                        "contractor": {
                            "type": "string",
                            "description": "Контрагент / сотрудник",
                        },
                        "group_by": {
                            "type": "string",
                            "enum": ["auto", "total", "month", "category", "list"],
                            "description": (
                                "total — сумма; month — по месяцам (в т.ч. сравнение лет); "
                                "category — топ статей; list — список операций; auto — по длине периода"
                            ),
                        },
                    },
                    "additionalProperties": False,
                },
                handler=self._query,
            ),
            ToolSpec(
                name="gincore_cashbox_balance",
                description="Текущий остаток кассы по названию (Левитан, Сахарова, Сейф…).",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Название или часть названия кассы"}
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
                handler=self._cashbox,
            ),
            ToolSpec(
                name="gincore_list_categories",
                description="Список статей доходов/расходов — если неясно, как называется статья.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                handler=self._categories,
            ),
            ToolSpec(
                name="gincore_repair_orders",
                description=(
                    "Заказы на РЕМОНТ (/orders#show_repair_orders). НЕ кассы. "
                    "Фильтры CRM: current, status, engineer, manager, accepter, location, "
                    "repair_type, person, other, client, device, defect, channel, order_id, serial. "
                    "«Сейчас…» → current=true (без period!). "
                    "«В удаленном сервисе» → status=В удаленном сервисе. "
                    "«У мастера X» → engineer=X. «На точке Левитан» → location=Левитан. "
                    "«От постоянных клиентов» → channel=Постоянные клиенты (+ обычно current=true). "
                    "Статистика приёма за период → period + group_by=month|total. "
                    "Сравнение лет → years_count=N, group_by=month."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "period": {
                            "type": "string",
                            "enum": [
                                "today",
                                "this_month",
                                "last_month",
                                "this_year",
                                "last_year",
                                "last_12_months",
                                "custom",
                            ],
                        },
                        "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                        "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                        "years": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Явный список лет, напр. [2023,2024,2025,2026]",
                        },
                        "years_count": {
                            "type": "integer",
                            "description": "Сколько последних лет включая текущий. «За 4 года» → 4.",
                        },
                        "current": {
                            "type": "boolean",
                            "description": "true = сейчас в ремонте (активные). Без period.",
                        },
                        "status": {
                            "type": "string",
                            "description": (
                                "Статус заказа: «В удаленном сервисе», «На диагностике», "
                                "«Готов», «Выдан», …"
                            ),
                        },
                        "engineer": {
                            "type": "string",
                            "description": "Мастер (фамилия/ФИО). «у Сатаулова» → Сатаулов.",
                        },
                        "manager": {
                            "type": "string",
                            "description": "Менеджер заказа (ФИО).",
                        },
                        "accepter": {
                            "type": "string",
                            "description": "Кто принял заказ (приёмщик).",
                        },
                        "location": {
                            "type": "string",
                            "description": (
                                "Точка/склад: Левитан, Каретный, Сегедская, логистика… "
                                "По умолчанию «находится на точке»."
                            ),
                        },
                        "location_mode": {
                            "type": "string",
                            "enum": ["l", "a"],
                            "description": "l=находится (default), a=принят на точке.",
                        },
                        "repair_type": {
                            "type": "string",
                            "description": "Платный / Доработка / Гарантийный Canon / Ricoh.",
                        },
                        "person": {
                            "type": "string",
                            "description": "Физ. лицо / Юр. лицо.",
                        },
                        "other": {
                            "type": "string",
                            "description": (
                                "Срочные / Вызов мастера на дом / курьер / почта / "
                                "неоплаченные / подменный фонд / вложения…"
                            ),
                        },
                        "client": {
                            "type": "string",
                            "description": "Поиск по клиенту (ФИО/название).",
                        },
                        "device": {
                            "type": "string",
                            "description": "Поиск по устройству.",
                        },
                        "defect": {
                            "type": "string",
                            "description": "По неисправности.",
                        },
                        "channel": {
                            "type": "string",
                            "description": (
                                "Рекламный канал: «Постоянные клиенты», «Интернет», "
                                "«Живет рядом»… Лучше с current=true."
                            ),
                        },
                        "order_id": {"type": "string", "description": "Номер заказа."},
                        "serial": {"type": "string", "description": "Серийный номер."},
                        "price_from": {"type": "number"},
                        "price_to": {"type": "number"},
                        "date_type": {
                            "type": "string",
                            "enum": ["accepted", "issued", "ready"],
                            "description": "Какую дату считать в period: приём / выдача / готов.",
                        },
                        "group_by": {
                            "type": "string",
                            "enum": ["auto", "total", "month", "list"],
                            "description": (
                                "month — по месяцам; total — число; list — строки; "
                                "для current/status обычно total или list."
                            ),
                        },
                    },
                    "additionalProperties": False,
                },
                handler=self._repair_orders,
            ),
            ToolSpec(
                name="gincore_find_contractor",
                description="Найти контрагента по ФИО/названию, если gincore_query не нашёл.",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
                handler=self._find_contractor,
            ),
            ToolSpec(
                name="gincore_test_connection",
                description="Проверить вход в Gincore.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                handler=self._test_connection,
            ),
        ]

    async def _query(self, args: dict[str, Any]) -> Any:
        has_multi = bool(args.get("years") or args.get("ranges") or args.get("years_count"))
        if (
            not has_multi
            and not args.get("period")
            and not args.get("date_from")
            and args.get("year") is None
        ):
            gb = (args.get("group_by") or "auto").lower()
            args = {
                **args,
                "period": "this_year" if gb in {"month", "category"} else "this_month",
            }
        ranges = self._resolve_ranges(args)
        gb = args.get("group_by") or "auto"
        if len(ranges) > 1 and gb in {"auto", "month"}:
            gb = "month"
        async with self._client() as client:
            return await client.query(
                ranges=ranges,
                category_query=args.get("category"),
                contractor_query=args.get("contractor"),
                group_by=gb,
            )

    async def _repair_orders(self, args: dict[str, Any]) -> Any:
        gb = (args.get("group_by") or "auto").lower()
        filter_keys = (
            "current",
            "status",
            "engineer",
            "manager",
            "accepter",
            "location",
            "department",
            "branch",
            "location_mode",
            "repair_type",
            "repair",
            "person",
            "person_type",
            "other",
            "flag",
            "client",
            "device",
            "defect",
            "comment",
            "channel",
            "ad_channel",
            "source",
            "order_id",
            "serial",
            "price_from",
            "price_to",
            "date_type",
        )
        filters = {k: args[k] for k in filter_keys if args.get(k) not in (None, "")}
        if "current" in filters:
            filters["current"] = bool(filters["current"])

        has_multi = bool(args.get("years") or args.get("ranges") or args.get("years_count"))
        has_period = bool(
            args.get("period") or args.get("date_from") or args.get("year") is not None
        )
        snapshot = bool(filters)

        # Snapshot-фильтры — без дефолтного period=today/this_year.
        if snapshot and not has_period and not has_multi:
            if gb == "auto":
                gb = (
                    "list"
                    if filters.get("current")
                    or filters.get("status")
                    or filters.get("channel")
                    or filters.get("engineer")
                    else "total"
                )
            async with self._client() as client:
                return await client.repair_orders(
                    group_by=gb,
                    filters=filters,
                    max_sample=100,
                )

        if not has_multi and not has_period:
            args = {
                **args,
                "period": "this_year" if gb == "month" else "today",
            }
        ranges = self._resolve_ranges(args)
        if len(ranges) > 1 and gb in {"auto", "month"}:
            gb = "month"
        async with self._client() as client:
            return await client.repair_orders(
                ranges=ranges,
                group_by=gb,
                filters=filters,
                max_sample=100 if filters else 20,
            )

    async def _test_connection(self, args: dict[str, Any]) -> Any:
        async with self._client() as client:
            return await client.login()

    async def _cashbox(self, args: dict[str, Any]) -> Any:
        async with self._client() as client:
            return await client.cashbox_balance(args["name"])

    async def _categories(self, args: dict[str, Any]) -> Any:
        async with self._client() as client:
            cats = await client.list_categories()
            return {"count": len(cats), "categories": cats}

    async def _find_contractor(self, args: dict[str, Any]) -> Any:
        async with self._client() as client:
            found = await client.find_contractor(args["query"])
            return {"query": args["query"], "matches": found[:20]}
