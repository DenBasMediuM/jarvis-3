"""Платная диагностика: кандидаты из буфера / непродиагностированных и статусы квитанций (без сети).

Источник кандидатов — кэш «Качества» (рабочие заказы со статусом, мастером, лентой и метриками):
лишних запросов в Gincore модуль не делает.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from modules.outsource.compute import classify_status

# Категории техники: (id, название, regex, сложность 1–3). Порядок важен — первое совпадение.
CATEGORIES: list[tuple[str, str, str, int]] = [
    ("cartridge", "Картриджи / заправка", r"картр|катрид|картидж|заправк|тонер", 0),
    ("power_station", "Зарядные станции", r"зар\w*\.?\s*станц|станци|ecoflow|bluetti|pecron|jackery|генератор", 3),
    ("inverter_ups", "Инверторы, ИБП, стабилизаторы", r"инверт|інверт|ибп|\bups\b|упс|стабил|стабіл|ресанта|бесперебо|безперебо", 3),
    ("laptop", "Ноутбуки", r"ноут|макбук|macbook|ультрабук|chromebook", 3),
    ("pc", "ПК, моноблоки, комплектующие", r"\bпк\b|системн|моноблок|материн|видеокарт|відеокарт|компьютер|комп'ютер|блок питания пк|сервер", 3),
    ("tv_monitor", "Телевизоры, мониторы, проекторы", r"телевиз|телевіз|\bтв\b|монитор|монітор|проектор", 3),
    ("console", "Игровые приставки", r"приставк|playstation|\bps ?[345]\b|xbox|nintendo|steam deck", 3),
    ("printer", "Принтеры, МФУ, 3D-принтеры", r"принтер|мфу|плоттер|\b3d\b|\b3д\b", 2),
    ("coffee", "Кофемашины", r"кофемаш|кавомаш|кофевар|кавовар", 2),
    ("robot_vac", "Роботы-пылесосы", r"робот", 2),
    ("audio", "Аудио: усилители, колонки", r"усилит|підсил|ресивер|колонк|саундбар|акустик|сабвуф", 2),
    ("tools", "Электроинструмент", r"перфорат|шуруповерт|шуруповёрт|болгарк|сварочн|зварюв|дрел|лобзик|фрезер|пила", 2),
    ("appliances", "Крупная техника", r"стиральн|пральн|посудомо|холодил|духов|варочн|кондицион", 2),
    ("phone_tablet", "Телефоны, планшеты", r"телефон|смартфон|айфон|iphone|samsung|xiaomi|redmi|планшет|ipad", 1),
    ("other", "Прочее", r".", 1),
]
CATEGORY_LABELS = {c[0]: c[1] for c in CATEGORIES}
_CAT_RE = [(cid, re.compile(rx, re.I), cx) for cid, _l, rx, cx in CATEGORIES]

# Статусы «ещё не продиагностировано / не согласовано»
OPEN_STATUSES = ("принят в ремонт", "на диагностике")
PAID_DIAG_RE = re.compile(r"платн\w*\s+ді?и?агн|ді?и?агн\w*\s+платн|платн\w*\s+діагн", re.I)
MAX_CANDIDATES = 80


def categorize(device: Any) -> tuple[str, int]:
    d = str(device or "")
    for cid, rx, cx in _CAT_RE:
        if rx.search(d):
            return cid, cx
    return "other", 1


def category_stats(history: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """По истории ремонтов (12 мес.): сколько в категории закрыто без ремонта и средний чек."""
    acc: dict[str, dict[str, float]] = {}
    for r in history:
        kind = classify_status(r.get("status"))
        if kind not in ("issued", "refusal"):
            continue
        cid, _ = categorize(r.get("device"))
        a = acc.setdefault(cid, {"closed": 0, "refusals": 0, "paid_sum": 0.0, "paid_n": 0})
        a["closed"] += 1
        if kind == "refusal":
            a["refusals"] += 1
        elif float(r.get("paid") or 0) > 0:
            a["paid_sum"] += float(r.get("paid") or 0)
            a["paid_n"] += 1
    out: dict[str, dict[str, Any]] = {}
    for cid, a in acc.items():
        out[cid] = {
            "label": CATEGORY_LABELS.get(cid, cid),
            "closed": int(a["closed"]),
            "refusal_share": round(a["refusals"] / a["closed"], 3) if a["closed"] else None,
            "avg_check": round(a["paid_sum"] / a["paid_n"]) if a["paid_n"] else None,
        }
    return out


def _days(iso: Any, today: date) -> int | None:
    try:
        return max(0, (today - date.fromisoformat(str(iso)[:10])).days)
    except (TypeError, ValueError):
        return None


def find_candidates(
    working: list[dict[str, Any]],
    *,
    today: date,
    stats: dict[str, dict[str, Any]],
    taken: set[str],
    order_url: Any = None,
) -> list[dict[str, Any]]:
    """Устройства в буфере или ещё не продиагностированные, где стоит предложить платную диагностику."""
    url = order_url or (lambda oid: None)
    out: list[dict[str, Any]] = []
    for o in working:
        oid = str(o.get("order_id") or "")
        if not oid or oid in taken:
            continue
        status = str(o.get("status") or "")
        if status.strip().lower() not in OPEN_STATUSES:
            continue
        if o.get("agreement_at") or o.get("is_ready") or o.get("is_closed"):
            continue
        feed_text = " ".join(str(e.get("text") or "") for e in (o.get("feed") or o.get("feed_events_list") or []))
        if PAID_DIAG_RE.search(feed_text):
            continue  # платную диагностику уже обсуждали в ленте
        cid, cx = categorize(o.get("device"))
        if cx == 0:
            continue
        engineer = str(o.get("engineer") or o.get("master_name") or "").strip()
        buffer = not engineer
        age = _days(o.get("accepted_at"), today)
        st = stats.get(cid) or {}
        share = st.get("refusal_share")
        # свежие важнее: платную диагностику надо согласовать ДО того, как мастер начал разбирать бесплатно;
        # «Принят в ремонт» старше 3 недель без согласования — скорее всего уже продиагностирован или завис
        fresh = 12 if (age or 0) <= 3 else 6 if (age or 0) <= 7 else 0 if (age or 0) <= 21 else -15
        score = cx * 30 + (share or 0) * 40 + fresh + (8 if buffer else 0)
        reasons = [CATEGORY_LABELS.get(cid, cid)]
        if cx >= 3:
            reasons.append("сложная диагностика")
        if share is not None and st.get("closed", 0) >= 10:
            reasons.append(f"{round(share * 100)}% в категории уходят без ремонта")
        if age is not None:
            reasons.append(f"принят {age} дн. назад" + (" — проверьте, не продиагностирован ли уже" if age > 21 else ""))
        out.append(
            {
                "ticket": oid,
                "device": o.get("device"),
                "status": status,
                "category": cid,
                "complexity": cx,
                "source": "buffer" if buffer else "undiagnosed",
                "engineer": engineer or None,
                "accepted_at": o.get("accepted_at"),
                "days": age,
                "location": o.get("location"),
                "score": round(score, 1),
                "reasons": reasons,
                "url": url(oid),
            }
        )
    out.sort(key=lambda c: -c["score"])
    return out[:MAX_CANDIDATES]


def ticket_info(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """Статус квитанции записи по CRM: kind open|paid_closed|closed_unpaid, оплачено."""
    if not row:
        return None
    status = row.get("status") or row.get("status_name") or ""
    kind = classify_status(status) if status else None
    paid = row.get("paid")
    return {
        "status": status or None,
        "kind": kind,
        "closed": kind in ("issued", "refusal"),
        "paid": float(paid) if paid is not None else None,
        "cost": row.get("cost") if row.get("cost") is not None else row.get("repair_cost"),
        "engineer": row.get("engineer") or row.get("master_name") or None,
    }
