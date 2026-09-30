from __future__ import annotations

import re
from typing import Any


RU_MONTHS = [
    "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
    "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
]

_SERIES_COLORS = [
    ("rgba(198, 40, 40, 0.75)", "#c62828"),
    ("rgba(21, 101, 192, 0.75)", "#1565c0"),
    ("rgba(46, 125, 50, 0.75)", "#2e7d32"),
    ("rgba(245, 124, 0, 0.75)", "#f57c00"),
    ("rgba(123, 31, 162, 0.7)", "#7b1fa2"),
    ("rgba(0, 121, 107, 0.75)", "#00796b"),
]


def _month_index(label: str) -> int | None:
    for i, name in enumerate(RU_MONTHS, start=1):
        if label.startswith(name):
            return i
    m = re.search(r"(?:^|-)(\d{2})$", label)
    if m:
        return int(m.group(1))
    return None


def _year_from_label(label: str) -> str | None:
    m = re.search(r"(20\d{2})", label)
    return m.group(1) if m else None


def _series_year(result: dict[str, Any]) -> str:
    if result.get("label"):
        return str(result["label"])
    if result.get("year"):
        return str(result["year"])
    months = result.get("months") or []
    if months:
        if months[0].get("year"):
            return str(months[0]["year"])
        y = _year_from_label(str(months[0].get("label") or ""))
        if y:
            return y
    df = result.get("date_from") or (result.get("filters") or {}).get("date_from") or ""
    return df[:4] if len(df) >= 4 else "серия"


def month_comparison_chart(
    series: list[dict[str, Any]],
    *,
    title: str,
    metric: str = "expense",
) -> dict[str, Any]:
    """Build one grouped bar chart from several monthly aggregates."""
    max_month = 1
    prepared: list[tuple[str, dict[int, float]]] = []
    for result in series:
        by_m: dict[int, float] = {}
        for row in result.get("months") or []:
            m = int(row.get("month") or 0)
            if not m:
                continue
            by_m[m] = float(row.get(metric) or 0)
            max_month = max(max_month, m)
        prepared.append((_series_year(result), by_m))

    labels = RU_MONTHS[:max_month]
    datasets = []
    for i, (label, by_m) in enumerate(prepared):
        bg, border = _SERIES_COLORS[i % len(_SERIES_COLORS)]
        datasets.append(
            {
                "label": label,
                "data": [round(by_m.get(m, 0.0), 2) for m in range(1, max_month + 1)],
                "backgroundColor": bg,
                "borderColor": border,
            }
        )
    return {
        "type": "bar",
        "title": title,
        "labels": labels,
        "datasets": datasets,
    }


def _fmt_uah(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}".replace(",", " ")
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def month_comparison_table(
    series: list[dict[str, Any]],
    *,
    title: str,
    metric: str = "expense",
    unit: str | None = None,
) -> dict[str, Any]:
    """One comparison table: Month | year1 | year2 | …"""
    if unit is None:
        unit = "шт" if metric == "count" else "UAH"
    max_month = 1
    prepared: list[tuple[str, dict[int, float], float]] = []
    for result in series:
        by_m: dict[int, float] = {}
        for row in result.get("months") or []:
            m = int(row.get("month") or 0)
            if not m:
                continue
            by_m[m] = float(row.get(metric) or 0)
            max_month = max(max_month, m)
        total = float(
            (result.get("totals") or {}).get(metric)
            or result.get(f"{metric}_total")
            or result.get("count")
            or sum(by_m.values())
        )
        prepared.append((_series_year(result), by_m, total))

    fmt = (lambda v: str(int(round(v)))) if metric == "count" else _fmt_uah
    columns = ["Месяц", *[f"{y} ({unit})" for y, _, _ in prepared]]
    rows: list[list[str]] = []
    for m in range(1, max_month + 1):
        rows.append(
            [
                RU_MONTHS[m - 1],
                *[fmt(by_m.get(m, 0.0)) for _, by_m, _ in prepared],
            ]
        )
    footer = ["Итого", *[fmt(total) for _, _, total in prepared]]
    return {
        "title": title,
        "columns": columns,
        "rows": rows,
        "footer": footer,
    }


def month_series_table(
    result: dict[str, Any],
    *,
    title: str,
    metric: str = "expense",
) -> dict[str, Any]:
    year = _series_year(result)
    unit = "шт" if metric == "count" else "UAH"
    fmt = (lambda v: str(int(round(v)))) if metric == "count" else _fmt_uah
    columns = ["Месяц", f"{year} ({unit})"]
    rows = []
    total = 0.0
    for row in result.get("months") or []:
        m = int(row.get("month") or 0)
        if not m:
            continue
        val = float(row.get(metric) or 0)
        total += val
        rows.append([RU_MONTHS[m - 1], fmt(val)])
    return {
        "title": title,
        "columns": columns,
        "rows": rows,
        "footer": ["Итого", fmt(total)],
    }


def _is_repair_result(result: dict[str, Any]) -> bool:
    src = str(result.get("source") or "")
    if "orders#" in src or "repair" in src:
        return True
    months = result.get("months") or []
    if months and "count" in months[0] and "expense" not in months[0] and "income" not in months[0]:
        return True
    return False


def finalize_visuals(
    tool_results: list[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pick charts/tables from tool results. Multi-range answers already include both."""
    charts: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    repair_month: list[dict[str, Any]] = []
    finance_month: list[dict[str, Any]] = []

    # Prefer an already-complete multi-series answer (finance or repairs)
    for result in reversed(tool_results):
        if not isinstance(result, dict) or result.get("error"):
            continue
        series = result.get("series")
        result_charts = [c for c in (result.get("charts") or []) if isinstance(c, dict)]
        if isinstance(series, list) and len(series) >= 2 and result_charts:
            result_tables = [t for t in (result.get("tables") or []) if isinstance(t, dict)]
            if not result_tables and isinstance(result.get("table"), dict):
                result_tables = [result["table"]]
            return result_charts, result_tables
        if result_charts and len((result_charts[0].get("datasets") or [])) >= 2:
            result_tables = [t for t in (result.get("tables") or []) if isinstance(t, dict)]
            if not result_tables and isinstance(result.get("table"), dict):
                result_tables = [result["table"]]
            return result_charts, result_tables

    for result in tool_results:
        if not isinstance(result, dict) or result.get("error"):
            continue
        if isinstance(result.get("charts"), list):
            for ch in result["charts"]:
                if isinstance(ch, dict) and ch not in charts:
                    charts.append(ch)
        elif isinstance(result.get("chart"), dict) and result["chart"] not in charts:
            charts.append(result["chart"])
        if isinstance(result.get("tables"), list):
            for tb in result["tables"]:
                if isinstance(tb, dict) and tb not in tables:
                    tables.append(tb)
        elif isinstance(result.get("table"), dict) and result["table"] not in tables:
            tables.append(result["table"])
        if result.get("months") and result.get("group_by") == "month":
            if _is_repair_result(result):
                repair_month.append(result)
            else:
                finance_month.append(result)

    if len(repair_month) >= 2 and not any(len((c.get("datasets") or [])) >= 2 for c in charts):
        chart = month_comparison_chart(
            repair_month,
            title="Сравнение приёмов в ремонт по месяцам",
            metric="count",
        )
        table = month_comparison_table(
            repair_month,
            title="Сравнение приёмов в ремонт по месяцам",
            metric="count",
            unit="шт",
        )
        return [chart], [table]

    if len(finance_month) >= 2 and not any(len((c.get("datasets") or [])) >= 2 for c in charts):
        topic = "расходы"
        for result in finance_month:
            cat = result.get("category") or (result.get("filters") or {}).get("category")
            if isinstance(cat, dict) and cat.get("name"):
                topic = cat["name"]
                break
            if isinstance(cat, str) and cat:
                topic = cat
                break
        chart = month_comparison_chart(
            finance_month,
            title=f"Сравнение по месяцам · {topic}",
            metric="expense",
        )
        table = month_comparison_table(
            finance_month,
            title=f"Сравнение по месяцам · {topic}",
            metric="expense",
        )
        return [chart], [table]

    return charts, tables
