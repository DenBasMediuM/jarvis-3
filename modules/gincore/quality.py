"""Service-center quality metrics from Gincore repair orders + live feed cache."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import parse_qs

from bs4 import BeautifulSoup

from modules.gincore.client import (
    GincoreClient,
    GincoreError,
    parse_gincore_date,
    parse_money,
)


# Filtered list from CRM (all branches except Сахарова, working statuses).
QUALITY_LIST_QUERY = (
    "dep=1-a,1-l,9-a,9-l,13-a,13-l,19-a,19-l,20-a,20-l,23-a,23-l,"
    "26-a,26-l,31-a,31-l,34-a,34-l,37-a,37-l,l-l"
    "&st=36,0,2,5,10,27,30,45,51,52,53,54,65"
)

WORKING_STATUSES = {
    "Готов частично",
    "Принят в ремонт",
    "На диагностике",
    "В процессе ремонта",
    "Ожидает запчастей",
    "На согласовании",
    "В удаленном сервисе",
    "Принят на доработку",
    "Не дозвонились",
    "Ждем оплату",
    "Ждем запч с Китая",
    "На продажу",
    "На тесте",
}

MASTER_CHANGED_RE = re.compile(
    r"изменил\s+мастера\s+на\s+(.+)$",
    re.IGNORECASE,
)
STATUS_CHANGED_RE = re.compile(
    r"изменил\s+статус\s+на\s+(.+)$",
    re.IGNORECASE,
)
AGREEMENT_HINT_RE = re.compile(
    r"согласован|согласуй|на\s+узгоджен|узгодь|сроки|срок\b|\+\s*в\s+отчет|"
    r"в\s+отч[её]т|диагност|ремонт\s+\d|\d+\s*(?:грн|uah|₴)",
    re.IGNORECASE,
)
PLAIN_PRICE_RE = re.compile(rf"^\s*(\d+(?:[.,]\d{{1,2}})?)\s*(?:грн|uah|₴)?\s*$", re.I)
NO_ANSWER_STATUS_RE = re.compile(r"не\s+дозвон|не\s+додзвон", re.IGNORECASE)
# Клиент согласился / пришёл (часто пишут коротко «согл»).
CLIENT_AGREED_RE = re.compile(
    r"^\s*согл\.?\s*$|"
    r"\bсогласован[оа]?\b|\bузгоджен[оа]?\b|"
    r"клиент\s+соглас|клієнт\s+згод|клиент\s+приш|клієнт\s+прийш",
    re.IGNORECASE,
)

_sync_lock = asyncio.Lock()
_sync_task: asyncio.Task | None = None


def quality_crm_params() -> dict[str, str]:
    raw = parse_qs(QUALITY_LIST_QUERY, keep_blank_values=True)
    return {k: v[0] if len(v) == 1 else ",".join(v) for k, v in raw.items()}


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _parse_feed_date(
    raw: str, *, accepted: date | None = None, today: date | None = None
) -> date | None:
    today = today or date.today()
    d = parse_gincore_date(raw, default_year=today.year)
    if d is None:
        return None
    # Feed often has no year; if month is far in the future vs today, use previous year.
    if d.year == today.year and d > today and (d.toordinal() - today.toordinal()) > 60:
        try:
            d = date(today.year - 1, d.month, d.day)
        except ValueError:
            pass
    if accepted and d.month < accepted.month and d.year == today.year:
        try:
            d = date(accepted.year, d.month, d.day)
        except ValueError:
            pass
    return d


def parse_accepted_from_list_cell(td) -> tuple[str, date | None]:
    """Accepter name + accept date from list column 3."""
    name = ""
    span = td.select_one(".visible-lg") or td.select_one("span")
    if span:
        name = span.get_text(" ", strip=True)
    muted = td.select_one(".orders-small-muted")
    date_s = ""
    if muted:
        date_s = (muted.get("title") or muted.get_text(" ", strip=True) or "").strip()
    # title like «6 Октябрь 2026 11:00:00» or «6 Окт.»
    d = None
    if date_s:
        m = re.search(
            r"(\d{1,2})\s+([А-Яа-яA-Za-z]+)[а-яА-Яa-zA-Z]*\.?(?:\s+(\d{4}))?",
            date_s,
        )
        if m:
            chunk = f"{m.group(1)} {m.group(2)[:3]}"
            if m.group(3):
                chunk += f" {m.group(3)}"
            d = parse_gincore_date(chunk)
        if d is None:
            d = parse_gincore_date(date_s)
    return name, d


def parse_quality_list_rows(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html or "", "lxml")
    orders: list[dict[str, Any]] = []
    for tr in soup.select("table.table-of-repair-orders tbody tr"):
        tds = tr.select("td")
        if len(tds) < 14:
            continue
        blob = " ".join(td.get_text(" ", strip=True) for td in tds).lower()
        if "нет заказ" in blob or "нет запис" in blob:
            continue
        oid = tds[1].get_text(" ", strip=True)
        if not re.fullmatch(r"\d{4,}", oid or ""):
            continue
        status = ""
        btn = tds[6].select_one(".btn-title") or tds[6].select_one("button.as_button")
        if btn:
            status = btn.get_text(" ", strip=True)
        accepter, accepted = parse_accepted_from_list_cell(tds[3])
        manager = ""
        mspan = tds[4].select_one(".visible-lg") or tds[4].select_one("span")
        if mspan:
            manager = mspan.get_text(" ", strip=True)
        engineer = ""
        if len(tds) > 5:
            espan = tds[5].select_one(".visible-lg") or tds[5].select_one("span")
            if espan:
                engineer = espan.get_text(" ", strip=True)
            else:
                engineer = tds[5].get_text(" ", strip=True)
        device = ""
        dspan = tds[9].select_one(".visible-lg")
        if dspan:
            device = dspan.get_text(" ", strip=True)
        client = ""
        cspan = tds[13].select_one(".visible-lg")
        if cspan:
            client = cspan.get_text(" ", strip=True)
        location = ""
        if len(tds) > 15:
            lspan = tds[15].select_one(".visible-lg")
            if lspan:
                location = lspan.get_text(" ", strip=True)
        fp = f"{status}|{engineer}|{_iso(accepted)}|{location}"
        orders.append(
            {
                "order_id": oid,
                "status": status,
                "engineer": engineer,
                "accepter": accepter,
                "manager": manager,
                "device": device,
                "client": client,
                "location": location,
                "accepted_at": _iso(accepted),
                "list_fingerprint": fp,
            }
        )
    return orders


def parse_order_page_meta(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html or "", "lxml")
    accepted = None
    for el in soup.select(".form-group, .panel-body, label, .row"):
        t = el.get_text(" ", strip=True)
        if "был принят" in t.lower():
            m = re.search(
                r"был\s+принят\s*:?\s*(\d{1,2}\s+[А-Яа-яA-Za-z]+\.?)",
                t,
                re.I,
            )
            if m:
                accepted = parse_gincore_date(m.group(1))
            break
    cost = None
    inp = soup.select_one('input[name="sum"]')
    if inp and inp.get("value") not in (None, ""):
        cost = parse_money(inp.get("value"))
    status = GincoreClient.parse_order_status(html)
    return {
        "accepted_at": _iso(accepted),
        "repair_cost": cost,
        "status_id": status.get("status_id"),
        "status_name": status.get("status_name"),
    }


def parse_order_feed_events(
    html: str, *, accepted: date | None = None
) -> list[dict[str, Any]]:
    """Full live-feed rows including calls (not only js-order-comment)."""
    soup = BeautifulSoup(html or "", "lxml")
    out: list[dict[str, Any]] = []
    for tr in soup.select(".js-comments-table tr"):
        body_el = tr.select_one(".order-comments__body")
        if not body_el:
            continue
        date_el = tr.select_one(".order-comments__date")
        author_el = tr.select_one(".order-comments__author")
        date_s = date_el.get_text(" ", strip=True) if date_el else ""
        author = author_el.get_text(" ", strip=True) if author_el else ""
        text = body_el.get_text(" ", strip=True)
        ctype = body_el.get("data-comment_type") or ""
        classes = " ".join(tr.get("class") or [])
        if not ctype and "comment-call" in (body_el.get("class") or []):
            ctype = "comment-call"
        if not ctype:
            if "comment-engineer" in classes:
                ctype = "comment-engineer"
            elif "comment-status" in classes:
                ctype = "comment-status"
            elif "comment-private" in classes:
                ctype = "comment-private"
            elif "comment-call" in classes:
                ctype = "comment-call"
        event_date = _parse_feed_date(date_s, accepted=accepted)
        kind = "comment"
        call_dir = None
        call_ok = None
        low = text.lower()
        if ctype == "comment-call" or "входящий" in low or "исходящий" in low:
            kind = "call"
            if "без оператора" in low:
                call_dir = "missed"
                call_ok = False
            elif "входящий" in low:
                call_dir = "inbound"
            elif "исходящий" in low:
                call_dir = "outbound"
            else:
                call_dir = "unknown"
            # Успешный звонок в CRM — есть кнопка прослушивания записи.
            has_record = bool(
                tr.select_one("a.play_record, .play_record, .record a[data-id]")
            )
            if call_dir != "missed":
                call_ok = has_record
        elif MASTER_CHANGED_RE.search(text):
            kind = "master_changed"
        elif STATUS_CHANGED_RE.search(text):
            kind = "status_changed"
        elif ctype == "comment-status":
            kind = "status_changed"
        elif ctype == "comment-engineer":
            kind = "master_changed"

        master_name = None
        mm = MASTER_CHANGED_RE.search(text)
        if mm:
            master_name = mm.group(1).strip()
            kind = "master_changed"
        status_name = None
        sm = STATUS_CHANGED_RE.search(text)
        if sm:
            status_name = sm.group(1).strip()
            kind = "status_changed"

        out.append(
            {
                "date": date_s,
                "date_iso": _iso(event_date),
                "author": author,
                "text": text,
                "type": ctype,
                "kind": kind,
                "call_dir": call_dir,
                "call_ok": call_ok,
                "master_name": master_name,
                "status_name": status_name,
            }
        )
    # Feed is newest-first in CRM; keep chronological for metrics.
    out.reverse()
    return out


def _engineer_assigned(name: str | None) -> bool:
    s = (name or "").strip()
    if not s or s in ("—", "-", "–", "−"):
        return False
    low = s.lower()
    if "не назнач" in low or "без мастера" in low or low == "нет":
        return False
    return True


def _is_no_answer_status(name: str | None) -> bool:
    return bool(name and NO_ANSWER_STATUS_RE.search(str(name)))


def _is_awaiting_client_status(name: str | None) -> bool:
    """После неуспешного звонка нормально ждать клиента в этих статусах."""
    if not name:
        return False
    if _is_no_answer_status(name):
        return True
    s = str(name).lower()
    return "на согласован" in s or "на узгоджен" in s


def _is_closed_status(name: str | None) -> bool:
    """Квитанция выдана клиенту — сроки до даты выдачи."""
    if not name:
        return False
    s = str(name).lower()
    if "не выдан" in s or "не видано" in s:
        return False
    markers = (
        "выдан",
        "видано",
        "выдача клиент",
        "выдан из ремонта",
        "выдан без ремонта",
    )
    return any(m in s for m in markers)


def _is_ready_status(name: str | None) -> bool:
    """Ремонт закончен, ждёт клиента («Готов») — в ремонте больше не считаем."""
    if not name:
        return False
    s = str(name).lower().strip()
    if s.startswith("не готов") or s.startswith("не готовий"):
        return False
    return (
        s == "готов"
        or s == "готовий"
        or s.startswith("готов ")
        or s.startswith("готовий ")
        or "готов к выдач" in s
        or "готовий до видач" in s
    )


def _last_status_date(
    feed: list[dict[str, Any]],
    predicate,
) -> date | None:
    found: date | None = None
    for ev in feed:
        if ev.get("kind") != "status_changed":
            continue
        if not predicate(ev.get("status_name")):
            continue
        iso = ev.get("date_iso")
        if iso:
            found = date.fromisoformat(iso)
    return found


def _find_closed_at(
    feed: list[dict[str, Any]],
    status: str | None,
) -> date | None:
    """Дата выдачи, если текущий статус — выдан."""
    if not _is_closed_status(status):
        return None
    closed_at = _last_status_date(feed, _is_closed_status)
    if closed_at is not None:
        return closed_at
    last: date | None = None
    for ev in feed:
        iso = ev.get("date_iso")
        if not iso:
            continue
        d = date.fromisoformat(iso)
        if last is None or d > last:
            last = d
    return last


def _find_ready_at(
    feed: list[dict[str, Any]],
    status: str | None,
) -> date | None:
    """Дата перехода в «Готов», если квитанция сейчас в этом статусе."""
    if not _is_ready_status(status):
        return None
    return _last_status_date(feed, _is_ready_status)


def _is_rework_accept_status(name: str | None) -> bool:
    """Статус приёма на доработку."""
    if not name:
        return False
    s = str(name).lower()
    return "доработ" in s or "доробк" in s


def _rework_days_penalty(days: int | None) -> float:
    """Штраф за срок (дней): 0–3 / 4–7 / 8–14 / 15–30 / 30+."""
    if days is None or days <= 3:
        return 0.0
    if days <= 7:
        return 10.0
    if days <= 14:
        return 25.0
    if days <= 30:
        return 40.0
    return 55.0


def compute_rework_kpi(
    *,
    rework_count: int,
    rework_diag_days: int | None,
    rework_repair_days: int | None,
    rework_total_days: int | None,
) -> int | None:
    """KPI доработок 0–100; None если доработок не было."""
    if rework_count <= 0:
        return None
    penalty = 20.0  # первая доработка
    if rework_count > 1:
        penalty += (rework_count - 1) * 25.0
    penalty += _rework_days_penalty(rework_total_days)
    # Долгая диагностика без старта ремонта — сильнее, чем долгий ремонт.
    if rework_repair_days is None:
        penalty += _rework_days_penalty(rework_diag_days) * 1.25
    else:
        penalty += _rework_days_penalty(rework_diag_days) * 0.5
        penalty += _rework_days_penalty(rework_repair_days) * 0.75
    return max(0, min(100, int(round(100.0 - penalty))))


def _days_to_kpi(days: int | None, *, ok: int, warn: int, bad: int) -> int | None:
    """Дни → оценка 0–100. ok/warn/bad — пороги как в таблице качества."""
    if days is None:
        return None
    d = max(0, int(days))
    if d <= ok:
        return 100
    if d <= warn:
        return int(round(100 - 30 * (d - ok) / max(1, warn - ok)))
    if d <= bad:
        return int(round(70 - 35 * (d - warn) / max(1, bad - warn)))
    extra = d - bad
    span = max(bad, 1)
    return max(0, int(round(35 - 35 * min(1.0, extra / span))))


def compute_order_kpi_breakdown(
    *,
    total_days: int | None,
    wait_master_days: int | None,
    diag_days: int | None,
    rework_kpi: int | None,
    calls_kpi: int | None,
    rework_count: int = 0,
    last_rework_at: str | None = None,
    rework_total_days: int | None = None,
) -> tuple[int | None, list[dict[str, Any]]]:
    """Итоговый KPI квитанции 0–100 + разбивка (без флага менеджера).

    Веса (перенормируются, если нет части данных):
      всего дн 25% · до мастера 15% · до диагн. 15% · дораб. 20% · звонки 25%.
    Нет доработок → 100 в компоненте доработок. Нет оценки звонков → компонент пропускается.
    """
    raw: list[dict[str, Any]] = []

    total_s = _days_to_kpi(total_days, ok=5, warn=7, bad=14)
    if total_s is not None:
        raw.append(
            {
                "key": "total",
                "label": "Всего дн",
                "score": total_s,
                "weight": 0.25,
                "detail": f"{total_days} дн в ремонте",
            }
        )
    wait_s = _days_to_kpi(wait_master_days, ok=1, warn=2, bad=5)
    if wait_s is not None:
        raw.append(
            {
                "key": "wait",
                "label": "До мастера",
                "score": wait_s,
                "weight": 0.15,
                "detail": f"{wait_master_days} дн ожидания",
            }
        )
    diag_s = _days_to_kpi(diag_days, ok=1, warn=3, bad=7)
    if diag_s is not None:
        raw.append(
            {
                "key": "diag",
                "label": "До диагн.",
                "score": diag_s,
                "weight": 0.15,
                "detail": f"{diag_days} дн до согласования",
            }
        )

    if rework_kpi is None:
        rw_score = 100
        rw_detail = "доработок не было — полный балл"
    else:
        rw_score = int(rework_kpi)
        bits = [f"{max(0, int(rework_count))}× приём"]
        if last_rework_at:
            bits.append(f"с {last_rework_at}")
        if rework_total_days is not None:
            bits.append(f"{rework_total_days} дн с последней")
        rw_detail = " · ".join(bits)
    raw.append(
        {
            "key": "rework",
            "label": "Дораб.",
            "score": rw_score,
            "weight": 0.20,
            "detail": rw_detail,
        }
    )

    if calls_kpi is not None:
        raw.append(
            {
                "key": "calls",
                "label": "Звонки",
                "score": int(calls_kpi),
                "weight": 0.25,
                "detail": "оценка коммуникации",
            }
        )

    if not raw:
        return None, []
    wsum = sum(float(p["weight"]) for p in raw)
    if wsum <= 0:
        return None, []
    score = sum(float(p["score"]) * float(p["weight"]) for p in raw) / wsum
    parts = [
        {
            **p,
            "weight_pct": int(round(100.0 * float(p["weight"]) / wsum)),
        }
        for p in raw
    ]
    return max(0, min(100, int(round(score)))), parts


def compute_order_kpi(
    *,
    total_days: int | None,
    wait_master_days: int | None,
    diag_days: int | None,
    rework_kpi: int | None,
    calls_kpi: int | None,
    rework_count: int = 0,
    last_rework_at: str | None = None,
    rework_total_days: int | None = None,
) -> int | None:
    kpi, _ = compute_order_kpi_breakdown(
        total_days=total_days,
        wait_master_days=wait_master_days,
        diag_days=diag_days,
        rework_kpi=rework_kpi,
        calls_kpi=calls_kpi,
        rework_count=rework_count,
        last_rework_at=last_rework_at,
        rework_total_days=rework_total_days,
    )
    return kpi


def _is_repair_progress_status(name: str | None) -> bool:
    """Ремонт уже идёт (после диагностики/согласования)."""
    if not name:
        return False
    s = str(name).lower()
    markers = (
        "процессе ремонта",
        "процесі ремонту",
        "ожидает зап",
        "очікує зап",
        "ждем запч",
        "на тесте",
        "на тесті",
        "ждем оплат",
        "чекаємо оплат",
        "удаленном",
    )
    return any(m in s for m in markers)


def _is_contact_recovered_status(name: str | None) -> bool:
    """Статус после реального контакта/согласия (клиент на связи или в сервисе)."""
    if not name or _is_awaiting_client_status(name):
        return False
    s = str(name).lower()
    markers = (
        "процессе ремонта",
        "процесі ремонту",
        "ожидает зап",
        "очікує зап",
        "готов",
        "на тесте",
        "на тесті",
        "ждем оплат",
        "чекаємо оплат",
        "ждем запч",
        "собираем на возврат",
        "збираємо на поверн",
        "удаленном",
        "на продажу",
        "на продаж",
        "доработ",
        "доробк",
    )
    return any(m in s for m in markers)


def _find_agreement_after(
    feed: list[dict[str, Any]],
    *,
    not_before: date,
    start: date | None,
    repair_cost: float | None,
) -> tuple[date | None, str | None]:
    """Первое согласование не раньше not_before (и не раньше start)."""
    agree_at: date | None = None
    agree_source: str | None = None
    floor = start or not_before
    for ev in feed:
        iso = ev.get("date_iso")
        if not iso:
            continue
        ed = date.fromisoformat(iso)
        if ed < not_before or ed < floor:
            continue
        text = str(ev.get("text") or "")
        if ev.get("kind") == "status_changed" and ev.get("status_name"):
            sn = str(ev["status_name"]).lower()
            waiting = "на согласован" in sn or "на узгоджен" in sn
            if not waiting and (
                "согласован" in sn or "согласовано" in sn or "узгоджен" in sn
            ):
                return ed, f"status:{ev['status_name']}"
        if PLAIN_PRICE_RE.match(text.strip()):
            val = parse_money(text)
            if val is not None and repair_cost is not None and abs(val - repair_cost) < 0.51:
                return ed, "price_match"
            if val is not None and val >= 100 and repair_cost is None:
                if agree_at is None:
                    agree_at = ed
                    agree_source = "plain_price"
        if AGREEMENT_HINT_RE.search(text) and ev.get("kind") == "comment":
            if agree_at is None or agree_source == "plain_price":
                agree_at = ed
                agree_source = "comment_hint"
        if CLIENT_AGREED_RE.search(text.strip()) and ev.get("kind") == "comment":
            return ed, "client_agreed"
    return agree_at, agree_source


def feed_missing_call_ok(feed: list[dict[str, Any]] | None) -> bool:
    """Old cache without success/fail flag — needs re-fetch from CRM."""
    for ev in feed or []:
        if ev.get("kind") == "call" and "call_ok" not in ev:
            return True
    return False


def compute_quality_metrics(
    *,
    accepted_at: str | None,
    repair_cost: float | None,
    feed: list[dict[str, Any]],
    engineer: str | None = None,
    status: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    accepted = date.fromisoformat(accepted_at) if accepted_at else None
    closed_at = _find_closed_at(feed, status)
    ready_at = _find_ready_at(feed, status)
    # Конец периода «в ремонте»: выдача → готовность → иначе сегодня.
    if closed_at is not None:
        as_of = closed_at
        as_of_reason = "closed"
    elif ready_at is not None:
        as_of = ready_at
        as_of_reason = "ready"
    else:
        as_of = today
        as_of_reason = "today"
    if accepted and as_of < accepted:
        as_of = accepted

    total_days = None
    if accepted:
        total_days = max(0, (as_of - accepted).days)

    master_at: date | None = None
    master_name = None
    for ev in feed:
        if ev.get("kind") != "master_changed":
            continue
        if ev.get("date_iso"):
            master_at = date.fromisoformat(ev["date_iso"])
            master_name = ev.get("master_name")
            break

    # Мастер часто ставится при приёмке — в ленте тогда нет «Изменил мастера».
    master_from_list = False
    if master_at is None and _engineer_assigned(engineer):
        master_at = accepted
        master_name = (engineer or "").strip()
        master_from_list = True

    wait_master_days = None
    if accepted and master_at is not None:
        wait_master_days = max(0, (master_at - accepted).days)
    elif accepted and master_at is None:
        wait_master_days = total_days  # still waiting

    agree_at: date | None = None
    agree_source = None
    start = master_at or accepted
    for ev in feed:
        iso = ev.get("date_iso")
        if not iso:
            continue
        ed = date.fromisoformat(iso)
        if start and ed < start:
            continue
        text = str(ev.get("text") or "")
        if ev.get("kind") == "status_changed" and ev.get("status_name"):
            sn = str(ev["status_name"]).lower()
            # «На согласовании» = ещё ждём, не считать согласованием.
            waiting = "на согласован" in sn or "на узгоджен" in sn
            if not waiting and (
                "согласован" in sn or "согласовано" in sn or "узгоджен" in sn
            ):
                agree_at = ed
                agree_source = f"status:{ev['status_name']}"
                break
        if PLAIN_PRICE_RE.match(text.strip()):
            val = parse_money(text)
            if val is not None and repair_cost is not None and abs(val - repair_cost) < 0.51:
                agree_at = ed
                agree_source = "price_match"
                break
            if val is not None and val >= 100 and repair_cost is None:
                # weak signal
                if agree_at is None:
                    agree_at = ed
                    agree_source = "plain_price"
        if AGREEMENT_HINT_RE.search(text) and ev.get("kind") == "comment":
            if agree_at is None or agree_source == "plain_price":
                agree_at = ed
                agree_source = "comment_hint"

    diag_days = None
    if start and agree_at:
        diag_days = max(0, (agree_at - start).days)
    elif start and not agree_at:
        diag_days = max(0, (as_of - start).days)

    inbound_ok = inbound_fail = 0
    outbound_ok = outbound_fail = 0
    missed = 0
    callback_same_day = 0
    post_day_buckets: dict[str, dict[str, int]] = {}
    pre_miss_days: list[date] = []
    pre_out_dates: list[date] = []
    pre_in_ok_dates: list[date] = []
    post_inbound_ok = 0
    post_outbound_ok = 0
    post_outbound_fail = 0
    pre_inbound_ok = 0

    def _post_bucket(day_key: str) -> dict[str, int]:
        return post_day_buckets.setdefault(
            day_key, {"in_ok": 0, "miss": 0, "out_ok": 0, "out_fail": 0}
        )

    for ev in feed:
        if ev.get("kind") != "call":
            continue
        iso = ev.get("date_iso") or ""
        ed = date.fromisoformat(iso) if iso else None
        pre = bool(accepted and ed and ed < accepted)
        direction = ev.get("call_dir")
        ok = ev.get("call_ok")

        if direction == "inbound":
            if ok is False:
                inbound_fail += 1
                if pre and ed:
                    pre_miss_days.append(ed)
                else:
                    _post_bucket(iso)["miss"] += 1
            else:
                inbound_ok += 1
                if pre:
                    pre_inbound_ok += 1
                    if ed:
                        pre_in_ok_dates.append(ed)
                else:
                    post_inbound_ok += 1
                    _post_bucket(iso)["in_ok"] += 1
        elif direction == "missed":
            missed += 1
            if pre and ed:
                pre_miss_days.append(ed)
            else:
                _post_bucket(iso)["miss"] += 1
        elif direction == "outbound":
            if ok is False:
                outbound_fail += 1
                if pre and ed:
                    pre_out_dates.append(ed)
                else:
                    post_outbound_fail += 1
                    _post_bucket(iso)["out_fail"] += 1
            else:
                outbound_ok += 1
                if pre and ed:
                    pre_out_dates.append(ed)
                else:
                    post_outbound_ok += 1
                    _post_bucket(iso)["out_ok"] += 1

    # До приёмки: только неуспешные входящие.
    # «Дозвонился в тот же день» = наш исходящий ИЛИ повторный успешный входящий.
    pre_miss_same_day = 0
    pre_miss_before_visit = 0  # связь до сдачи, но не в тот же день
    pre_miss_until_visit = 0  # до сдачи так и не связались
    for miss_day in pre_miss_days:
        same = any(o == miss_day for o in pre_out_dates) or any(
            i == miss_day for i in pre_in_ok_dates
        )
        later = False
        if accepted and not same:
            later = any(miss_day < o < accepted for o in pre_out_dates) or any(
                miss_day < i < accepted for i in pre_in_ok_dates
            )
        if same:
            pre_miss_same_day += 1
        elif later:
            pre_miss_before_visit += 1
        else:
            pre_miss_until_visit += 1

    missed_unrecovered = 0
    missed_recovered = 0
    for bucket in post_day_buckets.values():
        miss_n = bucket["miss"]
        has_out = bucket["out_ok"] > 0 or bucket["out_fail"] > 0
        has_client = miss_n > 0 or bucket["in_ok"] > 0
        if has_client and has_out:
            callback_same_day += 1
        if miss_n:
            if has_out:
                missed_recovered += miss_n
            else:
                missed_unrecovered += miss_n
    callback_same_day += pre_miss_same_day

    calls_ok = inbound_ok + outbound_ok
    calls_total = inbound_ok + inbound_fail + outbound_ok + outbound_fail + missed

    # KPI «Коммуникация» (0–100)
    # До приёмки: только неуспешные входящие (+ перезвон / отсутствие до сдачи).
    # Успешный входящий до сдачи — норма, не штраф.
    # После приёмки: исходящие✓ хорошо; клиент звонит сам — слабо;
    # не взяли без перезвона — очень плохо.
    calls_kpi: int | None = None
    kpi_relevant = (
        post_outbound_ok
        + post_inbound_ok
        + post_outbound_fail
        + missed_unrecovered
        + missed_recovered
        + pre_miss_same_day
        + pre_miss_before_visit
        + pre_miss_until_visit
    )
    if kpi_relevant > 0:
        good = post_outbound_ok * 5.0 + post_inbound_ok * 2.0
        bad = (
            missed_unrecovered * 10.0
            + missed_recovered * 4.0
            + post_outbound_fail * 1.5
            + post_inbound_ok * 1.0
            + pre_miss_same_day * 4.0
            + pre_miss_before_visit * 7.0
            + pre_miss_until_visit * 12.0
        )
        if (
            post_outbound_ok > 0
            and post_inbound_ok == 0
            and missed_unrecovered == 0
            and missed_recovered == 0
            and pre_miss_same_day == 0
            and pre_miss_before_visit == 0
            and pre_miss_until_visit == 0
            and post_outbound_fail == 0
        ):
            good += 10.0
        if good <= 0 and bad <= 0:
            calls_kpi = 50
        elif good <= 0:
            # Только штрафы (часто дозаказные пропуски) — не обнулять всё подряд.
            # same-day ~4 → ~56; until_visit ~12 → ~29
            calls_kpi = int(round(100.0 / (1.0 + bad / 5.0)))
            calls_kpi = max(0, min(100, calls_kpi))
        else:
            calls_kpi = int(round(100.0 * good / (good + bad)))
            calls_kpi = max(0, min(100, calls_kpi))

    # После согласования: неуспешный исходящий, дальше тишина (нет нового статуса /
    # успешного звонка / «согл»), и текущий статус не «На согласовании»/
    # «Не дозвонились» — похоже, менеджер забыл обновить статус.
    last_failed_out = False
    recovered_after_fail = False
    if agree_at:
        for ev in feed:
            iso = ev.get("date_iso")
            if not iso:
                continue
            ed = date.fromisoformat(iso)
            if ed < agree_at:
                continue
            if ev.get("kind") == "call":
                direction = ev.get("call_dir")
                ok = ev.get("call_ok")
                if direction == "outbound" and ok is False:
                    last_failed_out = True
                    recovered_after_fail = False
                elif ok is True and direction in ("outbound", "inbound"):
                    if last_failed_out:
                        recovered_after_fail = True
            text = str(ev.get("text") or "")
            if last_failed_out and ev.get("kind") == "comment" and CLIENT_AGREED_RE.search(
                text.strip()
            ):
                recovered_after_fail = True
            # Любая смена статуса после фейла = менеджер отреагировал (доработка,
            # ремонт, согласовние и т.д.) — не ошибка.
            if last_failed_out and ev.get("kind") == "status_changed":
                recovered_after_fail = True
    manager_no_answer_missed = bool(
        agree_at
        and last_failed_out
        and not recovered_after_fail
        and not _is_awaiting_client_status(status)
    )

    # --- Доработки (статус «Принят на доработку») ---
    rework_dates: list[date] = []
    for ev in feed:
        if ev.get("kind") != "status_changed":
            continue
        if not _is_rework_accept_status(ev.get("status_name")):
            continue
        iso = ev.get("date_iso")
        if iso:
            rework_dates.append(date.fromisoformat(iso))
    rework_count = len(rework_dates)
    last_rework_at = rework_dates[-1] if rework_dates else None

    rework_diag_days: int | None = None
    rework_repair_days: int | None = None
    rework_total_days: int | None = None
    rework_agree_at: date | None = None
    rework_agree_source: str | None = None

    if last_rework_at:
        rework_total_days = max(0, (as_of - last_rework_at).days)
        rework_master_at: date | None = None
        for ev in feed:
            iso = ev.get("date_iso")
            if not iso or ev.get("kind") != "master_changed":
                continue
            ed = date.fromisoformat(iso)
            if ed >= last_rework_at:
                rework_master_at = ed
                break
        rework_start = rework_master_at or last_rework_at
        rework_agree_at, rework_agree_source = _find_agreement_after(
            feed,
            not_before=last_rework_at,
            start=rework_start,
            repair_cost=repair_cost,
        )
        repair_start = rework_agree_at
        if repair_start is None:
            for ev in feed:
                iso = ev.get("date_iso")
                if not iso or ev.get("kind") != "status_changed":
                    continue
                ed = date.fromisoformat(iso)
                if ed < last_rework_at:
                    continue
                if _is_repair_progress_status(ev.get("status_name")):
                    repair_start = ed
                    rework_agree_source = rework_agree_source or f"status:{ev.get('status_name')}"
                    break
        if repair_start is not None:
            rework_diag_days = max(0, (repair_start - rework_start).days)
            rework_repair_days = max(0, (as_of - repair_start).days)
        else:
            rework_diag_days = max(0, (as_of - rework_start).days)
            rework_repair_days = None

    rework_kpi = compute_rework_kpi(
        rework_count=rework_count,
        rework_diag_days=rework_diag_days,
        rework_repair_days=rework_repair_days,
        rework_total_days=rework_total_days,
    )
    order_kpi, order_kpi_parts = compute_order_kpi_breakdown(
        total_days=total_days,
        wait_master_days=wait_master_days,
        diag_days=diag_days,
        rework_kpi=rework_kpi,
        calls_kpi=calls_kpi,
        rework_count=rework_count,
        last_rework_at=_iso(last_rework_at),
        rework_total_days=rework_total_days,
    )

    return {
        "total_days": total_days,
        "wait_master_days": wait_master_days,
        "master_assigned_at": _iso(master_at),
        "master_name": master_name,
        "master_from_list": master_from_list,
        "diag_days": diag_days,
        "agreement_at": _iso(agree_at),
        "agreement_source": agree_source,
        "as_of": _iso(as_of),
        "as_of_reason": as_of_reason,
        "closed_at": _iso(closed_at),
        "ready_at": _iso(ready_at),
        "is_closed": closed_at is not None,
        "is_ready": ready_at is not None and closed_at is None,
        "calls_inbound": inbound_ok + inbound_fail,
        "calls_inbound_ok": inbound_ok,
        "calls_inbound_fail": inbound_fail,
        "calls_outbound_ok": outbound_ok,
        "calls_outbound_fail": outbound_fail,
        "calls_missed": missed,
        "callback_same_day": callback_same_day,
        "calls_ok": calls_ok,
        "calls_total": calls_total,
        "calls_kpi": calls_kpi,
        "calls_missed_unrecovered": missed_unrecovered,
        "calls_missed_recovered": missed_recovered,
        "calls_pre_inbound_ok": pre_inbound_ok,
        "calls_pre_miss_same_day": pre_miss_same_day,
        "calls_pre_miss_before_visit": pre_miss_before_visit,
        "calls_pre_miss_until_visit": pre_miss_until_visit,
        "manager_no_answer_missed": manager_no_answer_missed,
        "rework_count": rework_count,
        "last_rework_at": _iso(last_rework_at),
        "rework_diag_days": rework_diag_days,
        "rework_repair_days": rework_repair_days,
        "rework_total_days": rework_total_days,
        "rework_agreement_at": _iso(rework_agree_at),
        "rework_agreement_source": rework_agree_source,
        "rework_kpi": rework_kpi,
        "order_kpi": order_kpi,
        "order_kpi_parts": order_kpi_parts,
        "feed_events": len(feed),
    }


class QualityService:
    def __init__(self, db: Any, client_factory: Any) -> None:
        self.db = db
        self._client_factory = client_factory

    async def list_rows(self) -> dict[str, Any]:
        rows = await self.db.quality_list_orders()
        sync = await self.db.quality_get_sync_state()
        out = []
        for r in rows:
            feed: list[dict[str, Any]] = []
            if r.get("feed_json"):
                try:
                    feed = json.loads(r["feed_json"])
                except json.JSONDecodeError:
                    feed = []
            if feed or r.get("accepted_at"):
                metrics = compute_quality_metrics(
                    accepted_at=r.get("accepted_at"),
                    repair_cost=r.get("repair_cost"),
                    feed=feed,
                    engineer=r.get("engineer"),
                    status=r.get("status"),
                )
            else:
                metrics = json.loads(r.get("metrics_json") or "{}")
            out.append(
                {
                    "order_id": r["order_id"],
                    "status": r.get("status"),
                    "engineer": r.get("engineer") or metrics.get("master_name"),
                    "accepter": r.get("accepter"),
                    "manager": r.get("manager"),
                    "device": r.get("device"),
                    "client": r.get("client"),
                    "location": r.get("location"),
                    "accepted_at": r.get("accepted_at"),
                    "repair_cost": r.get("repair_cost"),
                    "feed_synced_at": r.get("feed_synced_at"),
                    "list_synced_at": r.get("list_synced_at"),
                    "has_feed": bool(r.get("feed_json")),
                    "url": None,  # filled by API with base_url
                    **metrics,
                }
            )
        return {"ok": True, "orders": out, "sync": sync, "count": len(out)}

    async def start_sync(self, *, force: bool = False) -> dict[str, Any]:
        global _sync_task
        async with _sync_lock:
            state = await self.db.quality_get_sync_state()
            if state.get("status") == "running" and _sync_task and not _sync_task.done():
                return {"ok": True, "started": False, "sync": state}
            await self.db.quality_set_sync_state(
                status="running",
                total=0,
                done=0,
                queued=0,
                message="Загрузка списка заказов…",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at=None,
            )
            _sync_task = asyncio.create_task(self._run_sync(force=force))
            return {
                "ok": True,
                "started": True,
                "sync": await self.db.quality_get_sync_state(),
            }

    async def _run_sync(self, *, force: bool = False) -> None:
        client = None
        try:
            client = await self._client_factory()
            params = quality_crm_params()
            await self.db.quality_set_sync_state(message="Список заказов…")
            page = 1
            listed: list[dict[str, Any]] = []
            seen: set[str] = set()
            total_count = None
            while page <= 40:
                meta = await client._repair_orders_page(page=page, crm_params=params)
                if total_count is None:
                    total_count = int(meta.get("count") or 0)
                chunk = parse_quality_list_rows(meta.get("html") or "")
                if not chunk:
                    break
                new = 0
                for o in chunk:
                    oid = o["order_id"]
                    if oid in seen:
                        continue
                    seen.add(oid)
                    listed.append(o)
                    new += 1
                if new == 0:
                    break
                if total_count and len(listed) >= total_count:
                    break
                page += 1
                await asyncio.sleep(0.25)

            now = datetime.now(timezone.utc).isoformat()
            queue: list[str] = []
            for o in listed:
                prev = await self.db.quality_get_order(o["order_id"])
                need_feed = force or not prev or not prev.get("feed_json")
                if (
                    prev
                    and prev.get("list_fingerprint")
                    and prev.get("list_fingerprint") != o.get("list_fingerprint")
                ):
                    need_feed = True
                if prev and prev.get("feed_json") and not need_feed:
                    try:
                        old_feed = json.loads(prev["feed_json"])
                    except json.JSONDecodeError:
                        old_feed = []
                    if feed_missing_call_ok(old_feed):
                        need_feed = True
                await self.db.quality_upsert_order(
                    {
                        **o,
                        "list_synced_at": now,
                        "accepted_at": o.get("accepted_at")
                        or (prev or {}).get("accepted_at"),
                        "repair_cost": (prev or {}).get("repair_cost"),
                        "feed_json": (prev or {}).get("feed_json"),
                        "metrics_json": (prev or {}).get("metrics_json"),
                        "feed_synced_at": (prev or {}).get("feed_synced_at"),
                    }
                )
                if need_feed:
                    queue.append(o["order_id"])

            removed = await self.db.quality_delete_missing(seen)
            await self.db.quality_set_sync_state(
                total=len(queue),
                done=0,
                queued=len(queue),
                message=(
                    f"Список: {len(listed)} заказов"
                    + (f", снято {removed}" if removed else "")
                    + f". Лента: {len(queue)} к обновлению…"
                ),
            )

            for i, oid in enumerate(queue):
                await self._sync_one_feed(client, oid)
                await self.db.quality_set_sync_state(
                    done=i + 1,
                    queued=len(queue),
                    total=len(queue),
                    message=f"Лента {i + 1}/{len(queue)} · №{oid}",
                )
                await asyncio.sleep(0.4)

            # Refresh day counters for cached rows (total_days grows daily)
            for o in listed:
                if o["order_id"] in queue:
                    continue
                stored = await self.db.quality_get_order(o["order_id"])
                if not stored or not stored.get("feed_json"):
                    continue
                feed = json.loads(stored["feed_json"])
                metrics = compute_quality_metrics(
                    accepted_at=stored.get("accepted_at"),
                    repair_cost=stored.get("repair_cost"),
                    feed=feed,
                    engineer=stored.get("engineer"),
                    status=stored.get("status") or o.get("status"),
                )
                await self.db.quality_upsert_order(
                    {
                        "order_id": stored["order_id"],
                        "status": stored.get("status") or o.get("status"),
                        "engineer": stored.get("engineer"),
                        "accepter": stored.get("accepter"),
                        "manager": stored.get("manager"),
                        "device": stored.get("device"),
                        "client": stored.get("client"),
                        "location": stored.get("location"),
                        "accepted_at": stored.get("accepted_at"),
                        "repair_cost": stored.get("repair_cost"),
                        "list_fingerprint": stored.get("list_fingerprint"),
                        "list_synced_at": stored.get("list_synced_at"),
                        "feed_synced_at": stored.get("feed_synced_at"),
                        "feed_json": stored.get("feed_json"),
                        "metrics_json": json.dumps(metrics, ensure_ascii=False),
                    }
                )

            await self.db.quality_set_sync_state(
                status="idle",
                message=f"Готово: {len(listed)} в списке, обновлено лент {len(queue)}",
                finished_at=datetime.now(timezone.utc).isoformat(),
                done=len(queue),
                total=len(queue),
                queued=0,
            )
        except Exception as exc:  # noqa: BLE001
            await self.db.quality_set_sync_state(
                status="error",
                message=str(exc),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001
                    pass

    async def _sync_one_feed(self, client: GincoreClient, order_id: str) -> dict[str, Any]:
        html = await client.fetch_order_html(order_id)
        meta = parse_order_page_meta(html)
        stored = await self.db.quality_get_order(order_id) or {"order_id": order_id}
        accepted_iso = meta.get("accepted_at") or stored.get("accepted_at")
        accepted = date.fromisoformat(accepted_iso) if accepted_iso else None
        feed = parse_order_feed_events(html, accepted=accepted)
        cost = meta.get("repair_cost")
        if cost is None:
            cost = stored.get("repair_cost")
        engineer = stored.get("engineer")
        status = meta.get("status_name") or stored.get("status")
        metrics = compute_quality_metrics(
            accepted_at=accepted_iso,
            repair_cost=cost,
            feed=feed,
            engineer=engineer,
            status=status,
        )
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "order_id": order_id,
            "status": status,
            "engineer": engineer or metrics.get("master_name"),
            "accepter": stored.get("accepter"),
            "manager": stored.get("manager"),
            "device": stored.get("device"),
            "client": stored.get("client"),
            "location": stored.get("location"),
            "accepted_at": accepted_iso,
            "repair_cost": cost,
            "list_fingerprint": stored.get("list_fingerprint"),
            "list_synced_at": stored.get("list_synced_at"),
            "feed_json": json.dumps(feed, ensure_ascii=False),
            "metrics_json": json.dumps(metrics, ensure_ascii=False),
            "feed_synced_at": now,
        }
        await self.db.quality_upsert_order(row)
        return {
            "order_id": order_id,
            "status": status,
            "engineer": row["engineer"],
            "device": row.get("device"),
            "client": row.get("client"),
            "location": row.get("location"),
            "accepted_at": accepted_iso,
            "repair_cost": cost,
            "feed_synced_at": now,
            "metrics": metrics,
            "feed": feed,
            "feed_count": len(feed),
        }

    async def calc_order(self, order_id: str) -> dict[str, Any]:
        """Подтянуть квитанцию из CRM (даже вне рабочего списка) и посчитать KPI."""
        oid = str(order_id).strip()
        if not re.fullmatch(r"\d{4,}", oid):
            raise ValueError("Укажите корректный номер квитанции")
        client = None
        try:
            client = await self._client_factory()
            data = await self._sync_one_feed(client, oid)
        except GincoreError as exc:
            raise RuntimeError(str(exc) or "Ошибка CRM") from exc
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001
                    pass
        return data
