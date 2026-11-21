"""Постоянные клиенты: CRM-метрики клиентов и автопоиск кандидатов (чистые функции, без сети).

Клиент в Gincore узнаётся по телефону (колонка «Клиент» списка ремонтов: «Имя Имя +380…»):
статус/канал «Постоянные клиенты» в CRM ненадёжен.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

from modules.gincore.client import GincoreClient
from modules.gincore.quality import parse_quality_list_rows
from modules.outsource.compute import classify_status

PHONE_RE = re.compile(r"(?:\+?3?8)?\s*\(?0\d{2}\)?[\s\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
B2B_RE = re.compile(r"\b(тов|ооо|фоп|чп|пп|ltd|llc|магазин|маркет|сервис|сервіс|сц|офис|офіс|компан\w*|склад|школа|клиника|клініка|отель|готель|ресторан|кафе)\b", re.I)
DIAG_RE = re.compile(r"диагност", re.I)

# Окно истории (календарных месяцев, включая текущий): метрики за год и тренд.
HISTORY_MONTHS = 12
MAX_CANDIDATES = 150
ASLEEP_MIN_DAYS = 45


def norm_phone(raw: Any) -> str:
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else ""


def split_client(text: str) -> tuple[str, str]:
    """«Геннадий Геннадий +380969195362» → («Геннадий», «0969195362»)."""
    t = str(text or "").strip()
    m = PHONE_RE.search(t)
    phone = norm_phone(m.group(0)) if m else ""
    name = (t[: m.start()] + t[m.end():]).strip() if m else t
    name = re.sub(r"\s+", " ", name).strip(" ,.;-")
    # в списке имя часто задвоено: «Олена Олена», «Донченко Александра Донченко А...»
    words = name.split()
    if len(words) >= 2 and len(words) % 2 == 0:
        half = len(words) // 2
        a, b = " ".join(words[:half]), " ".join(words[half:]).replace("...", "").strip()
        if b and (a == b or a.startswith(b)):
            name = a
    name = name.replace("...", "").strip()
    return name[:120], phone


def parse_history_rows(html: str) -> list[dict[str, Any]]:
    """Строки списка ремонтов: поля Качества + клиент/телефон + стоимость/оплачено."""
    base = {r["order_id"]: r for r in parse_quality_list_rows(html)}
    money: dict[str, tuple[float | None, float | None]] = {}
    soup = BeautifulSoup(html or "", "lxml")
    for tr in soup.select("table.table-of-repair-orders tbody tr"):
        tds = tr.find_all("td", recursive=False) or tr.select("td")
        if len(tds) < 13:
            continue
        oid = tds[1].get_text(" ", strip=True)
        if not re.fullmatch(r"\d{4,}", oid or ""):
            continue
        money[oid] = (GincoreClient._money_from_td(tds[11]), GincoreClient._money_from_td(tds[12]))
    out: list[dict[str, Any]] = []
    for oid, r in base.items():
        name, phone = split_client(r.get("client") or "")
        cost, paid = money.get(oid, (None, None))
        out.append(
            {
                "order_id": oid,
                "status": r.get("status") or "",
                "device": r.get("device") or "",
                "accepted_at": r.get("accepted_at"),
                "name": name,
                "phone": phone,
                "cost": cost,
                "paid": paid,
            }
        )
    return out


def _d(iso: Any) -> date | None:
    try:
        return date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return None


def _money(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def index_by_phone(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    idx: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        p = r.get("phone")
        if p:
            idx.setdefault(p, []).append(r)
    return idx


def _avg_interval(days: list[date]) -> float | None:
    uniq = sorted(set(days))
    if len(uniq) < 3:
        return None
    gaps = [(b - a).days for a, b in zip(uniq, uniq[1:])]
    return round(sum(gaps) / len(gaps), 1) if gaps else None


def client_metrics(
    phones: list[str],
    by_phone: dict[str, list[dict[str, Any]]],
    *,
    today: date,
    order_url: Any = None,
) -> dict[str, Any]:
    """CRM-показатели клиента по всем его телефонам (окно истории — HISTORY_MONTHS)."""
    url = order_url or (lambda oid: None)
    rows: dict[str, dict[str, Any]] = {}
    for p in phones or []:
        for r in by_phone.get(p, []):
            rows[str(r["order_id"])] = r
    res: dict[str, Any] = {
        "phones_matched": [p for p in phones or [] if by_phone.get(p)],
        "orders": len(rows),
        "orders_30": 0,
        "orders_90": 0,
        "orders_prev_90": 0,
        "gross": 0.0,
        "gross_90": 0.0,
        "gross_prev_90": 0.0,
        "issued": 0,
        "refusals": 0,
        "first_order_at": None,
        "last_order_at": None,
        "days_since_last": None,
        "avg_interval": None,
        "asleep": False,
        "trend": None,
        "in_work": [],
        "debt": 0.0,
        "debt_orders": [],
        "by_month": {},
        "names": [],
        "devices": [],
    }
    if not rows:
        return res
    dates: list[date] = []
    names: dict[str, int] = {}
    devices: dict[str, int] = {}
    for oid, r in rows.items():
        d = _d(r.get("accepted_at"))
        kind = classify_status(r.get("status"))
        paid = _money(r.get("paid"))
        cost = _money(r.get("cost"))
        if r.get("name"):
            names[r["name"]] = names.get(r["name"], 0) + 1
        if r.get("device"):
            devices[r["device"]] = devices.get(r["device"], 0) + 1
        if d:
            dates.append(d)
            age = (today - d).days
            mkey = d.isoformat()[:7]
            mr = res["by_month"].setdefault(mkey, {"orders": 0, "gross": 0.0})
            mr["orders"] += 1
            if age <= 30:
                res["orders_30"] += 1
            if age <= 90:
                res["orders_90"] += 1
            elif age <= 180:
                res["orders_prev_90"] += 1
        if kind in ("issued", "refusal"):
            res["issued" if kind == "issued" else "refusals"] += 1
            res["gross"] += paid
            if d:
                res["by_month"][d.isoformat()[:7]]["gross"] += paid
                if (today - d).days <= 90:
                    res["gross_90"] += paid
                elif (today - d).days <= 180:
                    res["gross_prev_90"] += paid
            due = round(cost - paid, 2)
            if kind == "issued" and due > 0.5:
                res["debt"] += due
                res["debt_orders"].append(
                    {"ticket": oid, "cost": cost, "paid": paid, "due": due, "accepted_at": r.get("accepted_at"),
                     "days": (today - d).days if d else None, "url": url(oid)}
                )
        elif kind in ("working", "ready"):
            res["in_work"].append(
                {
                    "ticket": oid,
                    "status": r.get("status"),
                    "device": r.get("device"),
                    "accepted_at": r.get("accepted_at"),
                    "days": (today - d).days if d else None,
                    "diag": bool(DIAG_RE.search(r.get("status") or "")),
                    "ready": kind == "ready",
                    "url": url(oid),
                }
            )
    if dates:
        first, last = min(dates), max(dates)
        res["first_order_at"] = first.isoformat()
        res["last_order_at"] = last.isoformat()
        res["days_since_last"] = (today - last).days
        res["avg_interval"] = _avg_interval(dates)
        if res["avg_interval"]:
            limit = max(ASLEEP_MIN_DAYS, res["avg_interval"] * 2)
            res["asleep"] = res["days_since_last"] > limit and not res["in_work"]
    if res["gross_prev_90"] > 0:
        res["trend"] = round((res["gross_90"] - res["gross_prev_90"]) / res["gross_prev_90"], 3)
    res["gross"] = round(res["gross"], 2)
    res["gross_90"] = round(res["gross_90"], 2)
    res["gross_prev_90"] = round(res["gross_prev_90"], 2)
    res["debt"] = round(res["debt"], 2)
    for mr in res["by_month"].values():
        mr["gross"] = round(mr["gross"], 2)
    res["in_work"].sort(key=lambda o: -(o.get("days") or 0))
    res["debt_orders"].sort(key=lambda o: -(o.get("days") or 0))
    res["names"] = sorted(names, key=lambda n: -names[n])[:3]
    res["devices"] = sorted(devices, key=lambda n: -devices[n])[:8]
    return res


def find_candidates(
    by_phone: dict[str, list[dict[str, Any]]],
    *,
    today: date,
    thresholds: dict[str, Any],
    skip_phones: set[str],
    order_url: Any = None,
) -> list[dict[str, Any]]:
    """Клиенты, которые часто обращаются в последнее время и ещё не в разделе."""
    url = order_url or (lambda oid: None)
    months = int(thresholds.get("months") or 6)
    min_orders = int(thresholds.get("orders") or 3)
    recent_days = int(thresholds.get("recent_days") or 60)
    recent_min = int(thresholds.get("recent_orders") or 2)
    min_gross = float(thresholds.get("gross") or 0)
    window_days = months * 30.5
    out: list[dict[str, Any]] = []
    for phone, rows in by_phone.items():
        if phone in skip_phones:
            continue
        win = []
        for r in rows:
            d = _d(r.get("accepted_at"))
            if d and (today - d).days <= window_days:
                win.append((d, r))
        if len(win) < 2:
            continue
        recent = sum(1 for d, _ in win if (today - d).days <= recent_days)
        gross = sum(_money(r.get("paid")) for _, r in win if classify_status(r.get("status")) in ("issued", "refusal"))
        visits = len({d for d, _ in win})
        hit_orders = len(win) >= min_orders
        hit_recent = recent >= recent_min
        hit_gross = min_gross > 0 and gross >= min_gross
        if not (hit_orders or hit_recent or hit_gross):
            continue
        devices: dict[str, int] = {}
        names: dict[str, int] = {}
        for _, r in win:
            if r.get("device"):
                devices[r["device"]] = devices.get(r["device"], 0) + 1
            if r.get("name"):
                names[r["name"]] = names.get(r["name"], 0) + 1
        name = max(names, key=lambda n: names[n]) if names else ""
        last = max(d for d, _ in win)
        first = min(d for d, _ in win)
        refusals = sum(1 for _, r in win if classify_status(r.get("status")) == "refusal")
        multi = len(win) - visits  # несколько устройств за один визит
        b2b = bool(B2B_RE.search(name))
        days_since = (today - last).days
        score = (
            len(win) * 10
            + recent * 8
            + min(len(devices), 6) * 3
            + min(gross / 1000, 40)
            + multi * 4
            + (15 if b2b else 0)
            - days_since / 10
            - refusals * 3
        )
        reasons = [f"{len(win)} заказ(ов) за {months} мес."]
        if recent:
            reasons.append(f"{recent} за {recent_days} дн.")
        if len(devices) >= 2:
            reasons.append(f"{len(devices)} разных устройств")
        if multi > 0:
            reasons.append(f"по нескольку устройств за раз ({multi})")
        if gross > 0:
            reasons.append(f"{gross:,.0f} грн".replace(",", " "))
        if b2b:
            reasons.append("похоже на компанию")
        reasons.append(f"последний {days_since} дн. назад")
        last_orders = sorted(win, key=lambda x: x[0], reverse=True)[:6]
        out.append(
            {
                "phone": phone,
                "name": name,
                "orders": len(win),
                "recent": recent,
                "gross": round(gross, 2),
                "visits": visits,
                "devices": sorted(devices, key=lambda n: -devices[n])[:6],
                "first_at": first.isoformat(),
                "last_at": last.isoformat(),
                "days_since": days_since,
                "refusals": refusals,
                "b2b": b2b,
                "score": round(score, 1),
                "reasons": reasons,
                "tickets": [
                    {"ticket": r["order_id"], "date": d.isoformat(), "device": r.get("device"), "status": r.get("status"), "url": url(r["order_id"])}
                    for d, r in last_orders
                ],
            }
        )
    out.sort(key=lambda c: -c["score"])
    return out[:MAX_CANDIDATES]
