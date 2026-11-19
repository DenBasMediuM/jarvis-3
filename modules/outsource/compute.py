"""Аутсорс мастера: расчёт CRM-метрик по аутсорсерам (чистые функции, без сети).

Аутсорсер в Gincore — обычный «мастер» в карточке заказа (например «Саша Андрусяк»).
Привязку «кандидат воронки → мастер Gincore / получатель в кассе» задаёт менеджер на витрине.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

from modules.gincore.client import GincoreClient
from modules.gincore.quality import (
    _is_closed_status,
    _is_ready_status,
    parse_quality_list_rows,
)

# «Возврат» по договорённости с руководителем: не подлежит ремонту / выдан без ремонта / клиент отказался.
# «Собран(ираем) на возврат» и «Переведен в донор» — тоже итог без ремонта.
REFUSAL_RE = re.compile(
    r"не\s*подлеж|не\s*підляг|без\s*ремонт|отказ|відмов|на\s*возврат|в\s*донор",
    re.IGNORECASE,
)

# Долго у аутсорсера (дней с назначения мастера) — подсветка на витрине.
LONG_AT_MASTER_DAYS = 14

# Стадии, на которых по кандидату ждём устройства в работе.
ACTIVE_STAGES = {"trial", "regular"}


def norm_name(value: Any) -> str:
    s = str(value or "").lower().replace("ё", "е")
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


_NOT_SURNAME = {"аутсорс", "мастер", "сц", "сервис"}


def guess_surname_tokens(name: Any) -> list[str]:
    """Слова имени мастера, по которым можно искать получателя в кассе (без «аутсорс» и коротких)."""
    return [t for t in norm_name(name).split() if len(t) >= 4 and t not in _NOT_SURNAME]


def engineer_matches(binding: Any, engineer: Any) -> bool:
    """Мастер из CRM совпадает с привязкой: все слова привязки есть в имени мастера.

    «Андрусяк» ↔ «Саша Андрусяк», «Саша Андрусяк» ↔ «Саша Андрусяк».
    """
    b = norm_name(binding)
    e = norm_name(engineer)
    if not b or not e:
        return False
    if b == e:
        return True
    etoks = set(e.split())
    return all(t in etoks for t in b.split())


def classify_status(name: Any) -> str:
    """working | ready | issued | refusal."""
    s = str(name or "")
    if REFUSAL_RE.search(s):
        return "refusal"
    if _is_closed_status(s):
        return "issued"
    if _is_ready_status(s) or re.search(r"курьер.*готов", s, re.IGNORECASE):
        return "ready"
    return "working"


def parse_history_rows(html: str) -> list[dict[str, Any]]:
    """Строки списка ремонтов: поля как в Качестве + стоимость/оплачено."""
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
        cost, paid = money.get(oid, (None, None))
        out.append(
            {
                "order_id": oid,
                "status": r.get("status") or "",
                "engineer": r.get("engineer") or "",
                "device": r.get("device") or "",
                "accepted_at": r.get("accepted_at"),
                "location": r.get("location") or "",
                "cost": cost,
                "paid": paid,
            }
        )
    return out


def _days_between(a: str | None, today: date) -> int | None:
    if not a:
        return None
    try:
        return max(0, (today - date.fromisoformat(str(a)[:10])).days)
    except ValueError:
        return None


def _money(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def build_outsourcer_metrics(
    candidate: dict[str, Any],
    *,
    working: list[dict[str, Any]],
    history: list[dict[str, Any]],
    payouts: dict[str, Any] | None,
    today: date,
    order_url: Any = None,
) -> dict[str, Any]:
    """CRM-показатели одного аутсорсера.

    working — рабочие заказы из кэша Качества (engineer, status, accepted_at, master_assigned_at…);
    history — строки списка ремонтов за окно (parse_history_rows);
    payouts — {"total": float, "by_month": {"YYYY-MM": float}, "contractor": str|None, "matched": bool}.
    """
    binding = (candidate.get("crm_engineer") or "").strip()
    url = order_url or (lambda oid: None)
    res: dict[str, Any] = {
        "candidate_id": candidate.get("id"),
        "crm_engineer": binding or None,
        "bound": bool(binding),
        "engineers_matched": [],
        "in_work": 0,
        "ready": 0,
        "long_at_master": 0,
        "in_work_orders": [],
        "orders_total": 0,
        "issued": 0,
        "refusals": 0,
        "in_progress": 0,
        "return_rate": None,
        "gross": 0.0,
        "payouts": None,
        "net": None,
        "by_month": [],
        "payouts_contractor": None,
        "payouts_matched": None,
    }
    if not binding:
        return res

    matched_names: set[str] = set()
    seen_working: set[str] = set()
    for o in working:
        eng = o.get("engineer") or o.get("master_name") or ""
        if not engineer_matches(binding, eng):
            continue
        matched_names.add(str(eng))
        oid = str(o.get("order_id"))
        seen_working.add(oid)
        kind = classify_status(o.get("status"))
        if kind == "ready":
            res["ready"] += 1
            continue
        if kind != "working":
            continue
        at_master = _days_between(o.get("master_assigned_at") or o.get("accepted_at"), today)
        long_ = at_master is not None and at_master > LONG_AT_MASTER_DAYS
        res["in_work"] += 1
        if long_:
            res["long_at_master"] += 1
        res["in_work_orders"].append(
            {
                "ticket": oid,
                "status": o.get("status"),
                "device": o.get("device"),
                "accepted_at": o.get("accepted_at"),
                "days_total": _days_between(o.get("accepted_at"), today),
                "days_at_master": at_master,
                "long": long_,
                "location": o.get("location"),
                "url": url(oid),
            }
        )
    res["in_work_orders"].sort(key=lambda r: -(r.get("days_at_master") or 0))

    months: dict[str, dict[str, Any]] = {}

    def month_row(key: str) -> dict[str, Any]:
        return months.setdefault(
            key, {"month": key, "orders": 0, "issued": 0, "refusals": 0, "gross": 0.0, "payouts": 0.0}
        )

    for r in history:
        eng = r.get("engineer") or ""
        if not engineer_matches(binding, eng):
            continue
        matched_names.add(str(eng))
        res["orders_total"] += 1
        kind = classify_status(r.get("status"))
        mkey = str(r.get("accepted_at") or "")[:7] or "—"
        mr = month_row(mkey)
        mr["orders"] += 1
        if kind == "ready" and str(r.get("order_id")) not in seen_working:
            # рабочий список Качества не включает «Готов» — готовые берём из истории
            res["ready"] += 1
        if kind == "issued":
            res["issued"] += 1
            mr["issued"] += 1
        elif kind == "refusal":
            res["refusals"] += 1
            mr["refusals"] += 1
        else:
            res["in_progress"] += 1
        if kind in ("issued", "refusal"):
            paid = _money(r.get("paid"))
            res["gross"] += paid
            mr["gross"] += paid

    closed = res["issued"] + res["refusals"]
    res["return_rate"] = round(res["refusals"] / closed, 4) if closed else None
    res["gross"] = round(res["gross"], 2)

    if payouts is not None:
        res["payouts_contractor"] = payouts.get("contractor")
        res["payouts_auto"] = bool(payouts.get("auto"))
        res["payouts_matched"] = bool(payouts.get("matched"))
        if payouts.get("matched"):
            res["payouts"] = round(_money(payouts.get("total")), 2)
            res["net"] = round(res["gross"] - res["payouts"], 2)
            for mkey, amount in (payouts.get("by_month") or {}).items():
                month_row(mkey)["payouts"] += _money(amount)

    for mr in months.values():
        mr["gross"] = round(mr["gross"], 2)
        mr["payouts"] = round(mr["payouts"], 2)
        mr["net"] = round(mr["gross"] - mr["payouts"], 2) if res["payouts_matched"] else None
    res["by_month"] = sorted(months.values(), key=lambda m: m["month"])
    res["engineers_matched"] = sorted(matched_names)
    return res


def sum_payouts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Сумма расходов (выплат) из транзакций кассы по месяцам."""
    total = 0.0
    by_month: dict[str, float] = {}
    for r in rows:
        exp = r.get("expense")
        if exp is None or not r.get("month"):
            continue
        amount = abs(_money(exp))
        if amount <= 0:
            continue
        total += amount
        by_month[str(r["month"])] = by_month.get(str(r["month"]), 0.0) + amount
    return {"total": round(total, 2), "by_month": {k: round(v, 2) for k, v in sorted(by_month.items())}}


def engineer_names(working: list[dict[str, Any]], history: list[dict[str, Any]]) -> list[str]:
    """Все мастера из CRM — для выпадающего списка привязки на витрине."""
    names: dict[str, int] = {}
    for o in list(working) + list(history):
        n = str(o.get("engineer") or o.get("master_name") or "").strip()
        if n:
            names[n] = names.get(n, 0) + 1
    return sorted(names, key=lambda n: norm_name(n))


def trial_ticket_info(
    ticket: str,
    *,
    working_by_id: dict[str, dict[str, Any]],
    history_by_id: dict[str, dict[str, Any]],
    fetched: dict[str, dict[str, Any]],
    order_url: Any = None,
) -> dict[str, Any] | None:
    """Статус квитанции пробника из CRM (рабочий список → история → карточка)."""
    url = order_url or (lambda oid: None)
    src = working_by_id.get(ticket) or history_by_id.get(ticket) or fetched.get(ticket)
    if not src:
        return None
    status = src.get("status") or src.get("status_name") or ""
    return {
        "ticket": ticket,
        "status": status or None,
        "kind": classify_status(status) if status else None,
        "engineer": src.get("engineer") or src.get("master_name") or None,
        "device": src.get("device") or None,
        "accepted_at": src.get("accepted_at"),
        "paid": src.get("paid"),
        "url": url(ticket),
    }
