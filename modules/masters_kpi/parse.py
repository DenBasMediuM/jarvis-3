"""Парсинг отчётов мастеров (Sheets / xlsx) → строки квитанций."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from modules.masters_kpi.config import COPY_NAME_MARKERS

# Excel serial date epoch (Windows / Sheets).
_EXCEL_EPOCH = date(1899, 12, 30)

_TOTAL_RE = re.compile(r"грн|%|\bzп\b|итого|сумма\s*работ|всего", re.I)
_DATE_IN_NAME_RE = re.compile(
    r"(?P<d>\d{1,2})[.,/\- ]+(?P<m>\d{1,2})(?:[.,/\- ]+(?P<y>\d{2,4}))?"
)


def normalize_header(cell: Any) -> str:
    s = str(cell or "").strip().casefold().replace("ё", "е")
    s = re.sub(r"\s+", " ", s)
    return s


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
    s = re.sub(r"[^\d.\-]+$", "", s)
    s = re.sub(r"^[^\d.\-]+", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def excel_serial_to_date(n: float) -> date | None:
    try:
        # Sheets иногда даёт огромные числа-«даты» вроде 140520 — отсекаем.
        if n < 20000 or n > 60000:
            return None
        return _EXCEL_EPOCH + timedelta(days=int(n))
    except (OverflowError, ValueError):
        return None


def parse_ready_date(value: Any, *, fallback_year: int | None = None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return excel_serial_to_date(float(value))
    s = str(value).strip()
    if not s or s.casefold() in {"почти готов", "пример"}:
        return None
    # "22 , 09 , 2026" / "23,07.2020" / "12.08" / "14.08"
    compact = re.sub(r"\s+", "", s)
    m = re.match(
        r"^(\d{1,2})[.,/](\d{1,2})(?:[.,/](\d{2,4}))?$",
        compact,
    )
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y_raw = m.group(3)
        if y_raw:
            y = int(y_raw)
            if y < 100:
                y += 2000
        else:
            y = fallback_year or date.today().year
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    # "21 , 09 ,2026" already handled via compact; try loose
    nums = re.findall(r"\d+", s)
    if len(nums) >= 3:
        d, mo, y = int(nums[0]), int(nums[1]), int(nums[2])
        if y < 100:
            y += 2000
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    if len(nums) == 2:
        d, mo = int(nums[0]), int(nums[1])
        y = fallback_year or date.today().year
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def date_from_report_name(name: str) -> date | None:
    """Последняя дата в имени отчёта → fallback для строк без даты готовности."""
    text = name or ""
    found: list[date] = []
    for m in _DATE_IN_NAME_RE.finditer(text):
        d, mo = int(m.group("d")), int(m.group("m"))
        y_raw = m.group("y")
        if not y_raw:
            continue
        y = int(y_raw)
        if y < 100:
            y += 2000
        # Отсечь ложные хвосты вроде «24-01.09» → 2009
        if y < 2023:
            continue
        try:
            found.append(date(y, mo, d))
        except ValueError:
            continue
    return found[-1] if found else None


def is_copy_or_template_name(name: str) -> bool:
    t = (name or "").casefold()
    return any(m in t for m in COPY_NAME_MARKERS)


def _cell(row: list[Any], idx: int | None) -> Any:
    if idx is None or idx < 0 or idx >= len(row):
        return None
    return row[idx]


# Сводные графики и периодные итоги: с ISO-недели 2025-W31.
CHART_START = date.fromisocalendar(2025, 31, 1)


def in_chart_window(d: date) -> bool:
    iso = d.isocalendar()
    return int(iso.year) > 2025 or (int(iso.year) == 2025 and int(iso.week) >= 31)


def detect_layout(header_row: list[Any]) -> dict[str, int | None] | None:
    """Маппинг колонок по строке заголовка. None — не заголовок."""
    norms = [normalize_header(c) for c in header_row]
    joined = " | ".join(norms)
    cols: dict[str, int | None] = {
        "ticket": None,
        "work": None,
        "hours": None,
        "ready": None,
        "desc": None,
        "accept": None,
    }

    # Знайденов: «номер квитанции» / «Акт» + «стоимость работ»
    znay = any("номер квитанц" in n or n == "акт" for n in norms) and any(
        "стоимость" in n for n in norms
    )
    if znay or ("модель устройства" in joined and "заявленн" in joined):
        for i, n in enumerate(norms):
            if "номер квитанц" in n or n == "акт":
                cols["ticket"] = i
            if n.startswith("стоимость") or "стоимость работ" in n:
                cols["work"] = i
            if "дата готовн" in n:
                cols["ready"] = i
            if "дата прием" in n or "дата приём" in n:
                cols["accept"] = i
            if "ремонт" in n or "диагност" in n:
                cols["desc"] = cols["desc"] if cols["desc"] is not None else i
        # В шапке Знайденова «дата приема» часто в первой колонке второй строки
        if cols["accept"] is None and norms and (
            "дата прием" in norms[0] or norms[0] == ""
        ):
            # пустая/служебная A0 — дата приёма всё равно в col 0 у строк данных
            cols["accept"] = 0
        if cols["ticket"] is not None and cols["work"] is not None:
            return cols

    # Стандарт: Кв-я / Стоимость работ / Время / Дата готовности
    for i, n in enumerate(norms):
        if n in {"кв", "кв-я", "кв.", "квитанция", "квитанція", "ticket"} or n.startswith(
            "кв"
        ):
            cols["ticket"] = i
        if "стоимость работ" in n or n in {"стоимость", "сумма работ"}:
            cols["work"] = i
        if n in {"время", "часы", "час"} or "затрачен" in n or n.startswith("время"):
            cols["hours"] = i
        if "дата готовн" in n:
            cols["ready"] = i
        if "дата прием" in n or "дата приём" in n:
            cols["accept"] = i
        if "диагност" in n or "ремонт" in n:
            cols["desc"] = cols["desc"] if cols["desc"] is not None else i

    if cols["ticket"] is not None and cols["work"] is not None:
        return cols
    return None


def _section_date_from_row(row: list[Any]) -> date | None:
    """Строка-разделитель периода: дата в колонке B (формат Вовчука)."""
    if not row:
        return None
    a = row[0] if len(row) > 0 else None
    b = row[1] if len(row) > 1 else None
    # [None, datetime] или ['', datetime]
    if a is not None and str(a).strip() != "":
        return None
    if isinstance(b, datetime):
        return b.date()
    if isinstance(b, date) and not isinstance(b, datetime):
        return b
    return parse_ready_date(b)


def _looks_like_header(row: list[Any]) -> bool:
    norms = [normalize_header(c) for c in row if c is not None and str(c).strip()]
    if not norms:
        return False
    joined = " ".join(norms)
    markers = ("кв", "квитанц", "стоимость", "время", "дата готовн", "акт", "номер квитанц")
    hits = sum(1 for m in markers if m in joined)
    return hits >= 2


def _is_total_or_noise(row: list[Any], ticket_idx: int, work_idx: int) -> bool:
    ticket_raw = _cell(row, ticket_idx)
    work_raw = _cell(row, work_idx)
    # Итого без квитанции: "", "2700 грн"
    if ticket_raw is None or str(ticket_raw).strip() == "":
        blob = " ".join(str(c) for c in row if c is not None)
        if _TOTAL_RE.search(blob):
            return True
        # ЗП / аванс
        if any(normalize_header(c) in {"зп", "аванс"} for c in row if c is not None):
            return True
        return True  # без квитанции — не строка работ
    # ПРИМЕР
    blob = " ".join(str(c) for c in row if c is not None).casefold()
    if "пример" in blob:
        return True
    # ticket must be number-like
    tnum = parse_number(ticket_raw)
    if tnum is None:
        return True
    # huge fake tickets like 20444 in examples sometimes ok; skip if work is 0 and ПРИМЕР already
    if work_raw is not None and isinstance(work_raw, str) and _TOTAL_RE.search(work_raw):
        # "3900 грн" in work column with empty ticket handled above
        if tnum < 1000:
            return True
    return False


def parse_report_rows(
    values: list[list[Any]],
    *,
    source_name: str = "",
    fallback_ready: date | None = None,
) -> list[dict[str, Any]]:
    """Разобрать лист отчёта в список работ."""
    rows = [list(r) if isinstance(r, (list, tuple)) else [] for r in (values or [])]
    if not rows:
        return []

    header_idx = None
    cols = None
    for i, row in enumerate(rows[:8]):
        if _looks_like_header(row):
            maybe = detect_layout(row)
            if maybe:
                header_idx = i
                cols = maybe
                break
            # вторая строка заголовка ( Crow + labels )
            if i + 1 < len(rows):
                maybe2 = detect_layout(rows[i + 1])
                if maybe2:
                    header_idx = i + 1
                    cols = maybe2
                    break

    # Без заголовка — предполагаем стандарт A=ticket B=desc C=work D=hours E=ready
    if cols is None:
        cols = {"ticket": 0, "work": 2, "hours": 3, "ready": 4, "desc": 1}
        start = 0
    else:
        start = (header_idx or 0) + 1

    year_hint = (fallback_ready or date.today()).year
    out: list[dict[str, Any]] = []
    section_date: date | None = None
    for i, row in enumerate(rows[start:], start=start):
        if not row or not any(c is not None and str(c).strip() != "" for c in row):
            continue
        # Вовчук: строки-даты разделов «24.08 / 01.09 / …»
        sec = _section_date_from_row(row)
        if sec is not None:
            section_date = sec
            continue
        if _is_total_or_noise(row, cols["ticket"], cols["work"]):  # type: ignore[arg-type]
            continue
        ticket_num = parse_number(_cell(row, cols["ticket"]))  # type: ignore[arg-type]
        if ticket_num is None:
            continue
        # отсечь «примерные» маленькие id вроде 5 в шапке
        if ticket_num < 1000:
            continue
        work = parse_number(_cell(row, cols["work"]))  # type: ignore[arg-type]
        if work is None:
            continue
        if work < 0:
            continue
        # Явно битые/служебные суммы в одной строке
        if work > 80_000:
            continue
        # Строки % от выработки: B=0.5 / 0.45, C=сумма периода — без квитанции уже отсечены
        hours = parse_number(_cell(row, cols.get("hours")))  # type: ignore[arg-type]
        if hours is not None and hours < 0:
            hours = None
        # Защита: в колонку «Время» иногда попадает serial-дата Excel (~45xxx).
        if hours is not None and hours > 48:
            as_date = excel_serial_to_date(hours)
            hours = None
        else:
            as_date = None
        ready = parse_ready_date(
            _cell(row, cols.get("ready")),  # type: ignore[arg-type]
            fallback_year=year_hint,
        )
        if ready is None and as_date is not None:
            ready = as_date
        # Знайденов: нет «даты готовности» → дата приёма
        if ready is None and cols.get("accept") is not None:
            ready = parse_ready_date(
                _cell(row, cols.get("accept")),  # type: ignore[arg-type]
                fallback_year=year_hint,
            )
        # Вовчук: дата из заголовка блока
        if ready is None and section_date is not None:
            ready = section_date
        if ready is None:
            ready = fallback_ready
        ticket = (
            str(int(ticket_num))
            if ticket_num == int(ticket_num)
            else str(ticket_num)
        )
        desc = _cell(row, cols.get("desc"))  # type: ignore[arg-type]
        out.append(
            {
                "ticket": ticket,
                "work_sum": round(float(work), 2),
                "hours": round(float(hours), 2) if hours is not None else None,
                "ready_day": ready.isoformat() if ready else None,
                "description": str(desc).strip() if desc is not None else "",
                "source_row": i + 1,
                "source_name": source_name,
            }
        )
    return out


def week_key(d: date) -> tuple[int, int]:
    iso = d.isocalendar()
    return int(iso.year), int(iso.week)


def compute_kpi(
    work_sum: float | None,
    tickets: int | None,
    avg_ticket: float | None = None,
) -> float | None:
    """КПД без часов: выработка × (средний чек / 1000).

    Больше сумма и выше средний чек → выше КПД.
    """
    work = float(work_sum or 0)
    n = int(tickets or 0)
    if work <= 0 or n <= 0:
        return None
    avg = float(avg_ticket) if avg_ticket is not None else work / n
    if avg <= 0:
        return None
    return round(work * (avg / 1000.0), 2)


def apply_ready_fallback(
    rows: list[dict[str, Any]],
    fallback: date | None,
    *,
    max_undated: int = 40,
    max_undated_ratio: float = 0.55,
) -> list[dict[str, Any]]:
    """Подставить дату из имени файла для коротких недельных отчётов.

    Недельные листы Сатаулова часто без колонки даты (все строки undated) —
    для них fallback нужен. Накопительные (много строк И высокая доля без даты)
    не трогаем, иначе вся история сваливается в одну неделю.
    """
    if not fallback or not rows:
        return rows
    undated = [r for r in rows if not r.get("ready_day")]
    if not undated:
        return rows
    ratio = len(undated) / max(len(rows), 1)
    # AND: короткий недельный отчёт (≤40 строк без даты) всегда ок,
    # даже если 100% строк без даты.
    if len(undated) > max_undated and ratio > max_undated_ratio:
        return rows
    day = fallback.isoformat()
    for r in undated:
        r["ready_day"] = day
    return rows


def aggregate_weeks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Агрегат по ISO-неделе: tickets, work_sum, avg, kpi (без часов)."""
    buckets: dict[tuple[int, int], dict[str, Any]] = {}
    for r in rows:
        day_s = r.get("ready_day")
        if not day_s:
            continue
        try:
            d = date.fromisoformat(str(day_s)[:10])
        except ValueError:
            continue
        # Сводная динамика — с 2025-W31 (раньше только хвост Дубового).
        if not in_chart_window(d):
            continue
        key = week_key(d)
        b = buckets.get(key)
        if not b:
            b = {
                "iso_year": key[0],
                "iso_week": key[1],
                "week_start": date.fromisocalendar(key[0], key[1], 1).isoformat(),
                "tickets_set": set(),
                "work_sum": 0.0,
                "lines": 0,
            }
            buckets[key] = b
        b["tickets_set"].add(str(r.get("ticket") or ""))
        b["work_sum"] += float(r.get("work_sum") or 0)
        b["lines"] += 1

    out: list[dict[str, Any]] = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        tickets = len(b["tickets_set"])
        work = round(b["work_sum"], 2)
        avg = round(work / tickets, 2) if tickets else None
        # Отсечь явные свалки (одна «неделя» = сотни квитанций из накопительного листа)
        if tickets >= 80 and work >= 150_000:
            continue
        out.append(
            {
                "iso_year": b["iso_year"],
                "iso_week": b["iso_week"],
                "week_start": b["week_start"],
                "tickets": tickets,
                "lines": b["lines"],
                "work_sum": work,
                "hours": None,
                "avg_ticket": avg,
                "efficiency": compute_kpi(work, tickets, avg),
            }
        )
    return out


def master_key_from_name(name: str) -> str | None:
    from modules.masters_kpi.config import SURNAME_TO_KEY

    parts = re.split(r"\s+", (name or "").strip())
    if not parts:
        return None
    surname = parts[0].casefold().replace("ё", "е")
    # «Дубовой Юрий…» / folder «Дубовой»
    key = SURNAME_TO_KEY.get(surname)
    if key:
        return key
    # CRM: «Знайдёнов»
    surname2 = parts[0].casefold()
    return SURNAME_TO_KEY.get(surname2)
