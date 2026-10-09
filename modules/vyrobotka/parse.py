"""Парсинг недельных листов таблицы «Выработка» и агрегаты по досогласованиям."""

from __future__ import annotations

import re
from typing import Any

# Недельные листы: 202609(16-23), !20250804(28-03), 202512(09-15), с хвостовыми пробелами.
WEEK_SHEET_RE = re.compile(
    r"^!?(?P<head>\d{6,8})\((?P<a>\d{2})-(?P<b>\d{2})\)$"
)

SKIP_TITLES = {
    "dosoglasi",
    "сводка",
    "затраты",
    "прибль с мастеров из отчетов",
}


def normalize_sheet_title(title: str) -> str:
    return (title or "").strip()


def is_week_sheet(title: str) -> bool:
    t = normalize_sheet_title(title)
    if not t or t.casefold() in SKIP_TITLES:
        return False
    return bool(WEEK_SHEET_RE.match(t))


def sheet_sort_key(title: str) -> tuple[int, int, str]:
    """Хронологический ключ листа.

    Если в имени есть YYYYMMDD (!20250804(28-03)) — сортируем по этой дате.
    Иначе YYYYMM + день начала периода: 202609(16-23) → 20260916.
    """
    t = normalize_sheet_title(title)
    m = WEEK_SHEET_RE.match(t)
    if not m:
        return (0, 0, t)
    head = m.group("head")
    a = int(m.group("a"))
    b = int(m.group("b"))
    if len(head) >= 8:
        stamp = int(head[:8])
    else:
        stamp = int(head[:6]) * 100 + a
    return (stamp, b, t)


def parse_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("\xa0", " ").replace(" ", "").replace(",", ".")
    if not s:
        return None
    # убрать валютные хвосты
    s = re.sub(r"[^\d.\-]+$", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def _cell(row: list[Any], idx: int) -> Any:
    if idx < 0 or idx >= len(row):
        return None
    return row[idx]


def _is_header_row(row: list[Any]) -> bool:
    b = str(_cell(row, 1) or "").strip().casefold()
    a = str(_cell(row, 0) or "").strip().casefold()
    if b in {"кв", "квитанция", "квитанція", "ticket"}:
        return True
    if a in {"мастер", "майстер", "master"}:
        return True
    return False


def parse_week_rows(sheet_title: str, values: list[list[Any]]) -> list[dict[str, Any]]:
    """Нормализованные строки квитанций с fill-down мастера."""
    title = normalize_sheet_title(sheet_title)
    out: list[dict[str, Any]] = []
    master = ""
    for i, raw in enumerate(values or []):
        if not isinstance(raw, list):
            continue
        if i == 0 and _is_header_row(raw):
            continue
        a = _cell(raw, 0)
        if a is not None and str(a).strip():
            master = str(a).strip()
        ticket_raw = _cell(raw, 1)
        ticket_num = parse_number(ticket_raw)
        if ticket_num is None:
            # пустая / нечисловая квитанция — не строка данных
            continue
        ticket = str(int(ticket_num)) if ticket_num == int(ticket_num) else str(ticket_num)

        report = parse_number(_cell(raw, 2))
        salary = parse_number(_cell(raw, 3))
        parts = parse_number(_cell(raw, 4))
        total = parse_number(_cell(raw, 5))
        paid = parse_number(_cell(raw, 6))
        upsell = parse_number(_cell(raw, 7))
        remainder = parse_number(_cell(raw, 8))
        arith_check = str(_cell(raw, 9) or "").strip() or None  # Норм / Лажа
        status = str(_cell(raw, 10) or "").strip() or None
        control = str(_cell(raw, 11) or "").strip() or None
        upsell_floor = _cell(raw, 12)  # число / Минималка / Проверить
        upsell_floor_num = parse_number(upsell_floor)
        upsell_floor_label = None
        if upsell_floor_num is None and upsell_floor is not None and str(upsell_floor).strip():
            upsell_floor_label = str(upsell_floor).strip()

        comments_parts: list[str] = []
        for j in range(13, len(raw)):
            c = _cell(raw, j)
            if c is None or c == "":
                continue
            comments_parts.append(str(c).strip())
        comments = " | ".join(comments_parts) if comments_parts else None

        out.append(
            {
                "sheet_title": title,
                "row_index": i + 1,  # 1-based как в Sheets
                "master": master or None,
                "ticket": ticket,
                "report_amount": report,
                "salary": salary,
                "parts": parts,
                "total_repair": total,
                "paid": paid,
                "upsell": upsell,
                "remainder": remainder,
                "arith_check": arith_check,  # «Арифметика квитанции»
                "status": status,
                "control": control,
                "upsell_floor": upsell_floor_num,  # «Оценка досогласования» (число)
                "upsell_floor_label": upsell_floor_label,
                "comments": comments,
            }
        )
    return out


def aggregate_sheet_upsell(sheet_title: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Обязательные метрики досогласований по одному недельному листу."""
    title = normalize_sheet_title(sheet_title)
    tickets = len(rows)
    report_sum = 0.0
    upsell_sum = 0.0
    upsell_count = 0
    upsell_values: list[float] = []

    for r in rows:
        ra = r.get("report_amount")
        if ra is not None:
            report_sum += float(ra)
        u = r.get("upsell")
        if u is not None and float(u) > 0:
            uv = float(u)
            upsell_sum += uv
            upsell_count += 1
            upsell_values.append(uv)

    avg_upsell = (sum(upsell_values) / len(upsell_values)) if upsell_values else None
    ratio = (upsell_count / tickets) if tickets else None

    stamp, b, _ = sheet_sort_key(title)
    # sort_ym / sort_a храним как stamp и end-day для совместимости со схемой БД
    return {
        "sheet_title": title,
        "sort_ym": stamp,
        "sort_a": stamp % 100,
        "sort_b": b,
        "tickets_count": tickets,
        "report_sum": report_sum,
        "upsell_sum": upsell_sum,
        "upsell_count": upsell_count,
        "avg_upsell": avg_upsell,
        "upsell_ratio": ratio,
    }


def underpayment_amount(total_repair: Any, paid: Any) -> float | None:
    """Недоплата: общая стоимость ремонта − оплачено клиентом. None если нет долга."""
    if total_repair is None:
        return None
    try:
        total = float(total_repair)
    except (TypeError, ValueError):
        return None
    try:
        paid_v = float(paid) if paid is not None else 0.0
    except (TypeError, ValueError):
        paid_v = 0.0
    debt = total - paid_v
    if debt <= 0.005:
        return None
    return round(debt, 2)


def aggregate_sheet_debt(sheet_title: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Дебиторка по листу: сумма и число недоплаченных квитанций."""
    title = normalize_sheet_title(sheet_title)
    debt_sum = 0.0
    debt_count = 0
    tickets = len(rows)
    for r in rows:
        d = underpayment_amount(r.get("total_repair"), r.get("paid"))
        if d is None:
            continue
        debt_sum += d
        debt_count += 1
    stamp, b, _ = sheet_sort_key(title)
    return {
        "sheet_title": title,
        "sort_ym": stamp,
        "sort_a": stamp % 100,
        "sort_b": b,
        "tickets_count": tickets,
        "debt_sum": round(debt_sum, 2),
        "debt_count": debt_count,
        "debt_ratio": (debt_count / tickets) if tickets else None,
        "avg_debt": (round(debt_sum / debt_count, 2) if debt_count else None),
    }


def collect_underpaid_tickets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Все недоплаченные квитанции (для таблицы дебиторки)."""
    out: list[dict[str, Any]] = []
    for r in rows:
        d = underpayment_amount(r.get("total_repair"), r.get("paid"))
        if d is None:
            continue
        total = float(r["total_repair"]) if r.get("total_repair") is not None else None
        paid = float(r["paid"]) if r.get("paid") is not None else 0.0
        out.append(
            {
                "sheet_title": r.get("sheet_title"),
                "master": r.get("master"),
                "ticket": r.get("ticket"),
                "total_repair": total,
                "paid": paid,
                "debt": d,
                "status": r.get("status"),
                "control": r.get("control"),
                "arith_check": r.get("arith_check"),
                "comments": r.get("comments"),
            }
        )
    out.sort(
        key=lambda x: (
            -float(x.get("debt") or 0),
            sheet_sort_key(str(x.get("sheet_title") or "")),
            str(x.get("ticket") or ""),
        )
    )
    return out


def select_week_sheets(sheets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Оставить только недельные листы, отсортированные по периоду."""
    picked = [s for s in sheets if is_week_sheet(str(s.get("title") or ""))]
    picked.sort(key=lambda s: sheet_sort_key(str(s.get("title") or "")))
    return picked
