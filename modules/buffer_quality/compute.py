"""Коэффициент загрузки мастеров и ретроспектива раздачи буфера."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from modules.gincore.quality import _engineer_assigned

OPEN_CAP = 8.0
AGE_CAP = 40.0
REWORK_CAP = 3.0
NO_DIAG_CAP = 4.0

WEIGHT_OPEN = 0.40
WEIGHT_AGE = 0.25
WEIGHT_REWORK = 0.20
WEIGHT_NO_DIAG = 0.15

ZONE_LOW = "low"
ZONE_OK = "ok"
ZONE_HIGH = "high"

ASSIGN_GOOD = "good"
ASSIGN_OK = "ok"
ASSIGN_BAD = "bad"
ASSIGN_UNKNOWN = "unknown"

NO_DIAG_STATUSES = frozenset({"На диагностике", "Принят в ремонт"})


def master_key(name: str | None) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _parse_day(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    s = str(value).strip()[:10]
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def order_age_days(order: dict[str, Any], *, as_of: date) -> int:
    td = order.get("total_days")
    if td is not None:
        try:
            return max(0, int(td))
        except (TypeError, ValueError):
            pass
    accepted = _parse_day(order.get("accepted_at"))
    if accepted is None:
        return 0
    return max(0, (as_of - accepted).days)


def is_no_diag(order: dict[str, Any]) -> bool:
    status = str(order.get("status") or "").strip()
    if status == "На диагностике":
        return True
    if status in NO_DIAG_STATUSES and not order.get("agreement_at"):
        return True
    return False


def _component(value: float, cap: float) -> float:
    if cap <= 0:
        return 0.0
    return min(1.5, max(0.0, float(value) / cap))


def load_index_from_signals(
    *,
    open_count: float,
    age_sum_days: float,
    rework_orders: float,
    no_diag_count: float,
) -> float:
    raw = (
        WEIGHT_OPEN * _component(open_count, OPEN_CAP)
        + WEIGHT_AGE * _component(age_sum_days, AGE_CAP)
        + WEIGHT_REWORK * _component(rework_orders, REWORK_CAP)
        + WEIGHT_NO_DIAG * _component(no_diag_count, NO_DIAG_CAP)
    )
    return round(raw * 100.0, 2)


def zone_for_load(load_index: float) -> str:
    if load_index > 70:
        return ZONE_HIGH
    if load_index >= 40:
        return ZONE_OK
    return ZONE_LOW


def assign_quality_for_zone(zone: str | None) -> str:
    if zone == ZONE_LOW:
        return ASSIGN_GOOD
    if zone == ZONE_OK:
        return ASSIGN_OK
    if zone == ZONE_HIGH:
        return ASSIGN_BAD
    return ASSIGN_UNKNOWN


def buffer_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [o for o in orders if not _engineer_assigned(o.get("engineer"))]


def build_master_loads(
    orders: list[dict[str, Any]], *, as_of: date | None = None
) -> list[dict[str, Any]]:
    as_of = as_of or date.today()
    buckets: dict[str, dict[str, Any]] = {}
    for o in orders:
        eng = str(o.get("engineer") or o.get("master_name") or "").strip()
        if not _engineer_assigned(eng):
            continue
        key = master_key(eng)
        b = buckets.get(key)
        if not b:
            b = {
                "master_key": key,
                "display_name": eng,
                "open_count": 0,
                "age_sum_days": 0.0,
                "rework_orders": 0,
                "no_diag_count": 0,
            }
            buckets[key] = b
        b["open_count"] += 1
        b["age_sum_days"] += float(order_age_days(o, as_of=as_of))
        if int(o.get("rework_count") or 0) > 0:
            b["rework_orders"] += 1
        if is_no_diag(o):
            b["no_diag_count"] += 1

    out: list[dict[str, Any]] = []
    for b in buckets.values():
        load = load_index_from_signals(
            open_count=b["open_count"],
            age_sum_days=b["age_sum_days"],
            rework_orders=b["rework_orders"],
            no_diag_count=b["no_diag_count"],
        )
        out.append(
            {
                **b,
                "age_sum_days": round(float(b["age_sum_days"]), 2),
                "load_index": load,
                "zone": zone_for_load(load),
                "assigned_from_buffer": 0,
                "assign_quality": None,
            }
        )
    out.sort(key=lambda r: (-float(r["load_index"]), r["display_name"].lower()))
    return out


def build_buffer_snapshot(
    orders: list[dict[str, Any]], *, as_of: date | None = None
) -> dict[str, Any]:
    as_of = as_of or date.today()
    buf = buffer_orders(orders)
    over3 = [o for o in buf if order_age_days(o, as_of=as_of) >= 3]
    ids = sorted(
        {str(o.get("order_id")) for o in buf if o.get("order_id")},
        key=lambda x: x,
    )
    return {
        "buffer_count": len(buf),
        "buffer_over_3d": len(over3),
        "buffer_ids": ids,
    }


def classify_assignments(
    *,
    prev_buffer_ids: list[str] | set[str],
    orders: list[dict[str, Any]],
    prev_masters: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Заказы, вчера бывшие в буфере и сегодня с мастером → качество раздачи."""
    by_id = {
        str(o.get("order_id")): o
        for o in orders
        if o.get("order_id")
    }
    prev_zone = {
        str(m.get("master_key")): str(m.get("zone") or "")
        for m in (prev_masters or [])
        if m.get("master_key")
    }
    per_master: dict[str, dict[str, Any]] = {}
    assign_to_high = assign_to_ok = assign_to_low = assign_unknown = 0
    details: list[dict[str, Any]] = []

    for oid in prev_buffer_ids:
        o = by_id.get(str(oid))
        if not o:
            continue
        eng = str(o.get("engineer") or o.get("master_name") or "").strip()
        if not _engineer_assigned(eng):
            continue
        key = master_key(eng)
        zone = prev_zone.get(key)
        quality = assign_quality_for_zone(zone)
        if quality == ASSIGN_BAD:
            assign_to_high += 1
        elif quality == ASSIGN_OK:
            assign_to_ok += 1
        elif quality == ASSIGN_GOOD:
            assign_to_low += 1
        else:
            assign_unknown += 1

        slot = per_master.get(key)
        if not slot:
            slot = {
                "master_key": key,
                "display_name": eng,
                "assigned_from_buffer": 0,
                "assign_quality": quality,
            }
            per_master[key] = slot
        slot["assigned_from_buffer"] += 1
        # если хоть одно назначение bad — мастер помечается bad
        rank = {ASSIGN_BAD: 3, ASSIGN_OK: 2, ASSIGN_UNKNOWN: 1, ASSIGN_GOOD: 0}
        if rank.get(quality, 0) > rank.get(slot["assign_quality"] or ASSIGN_GOOD, 0):
            slot["assign_quality"] = quality

        details.append(
            {
                "order_id": str(oid),
                "master_key": key,
                "display_name": eng,
                "prev_zone": zone or None,
                "assign_quality": quality,
            }
        )

    total = assign_to_high + assign_to_ok + assign_to_low + assign_unknown
    return {
        "assigned_from_buffer": total if prev_buffer_ids else None,
        "assign_to_high": assign_to_high,
        "assign_to_ok": assign_to_ok,
        "assign_to_low": assign_to_low,
        "assign_unknown": assign_unknown,
        "per_master": list(per_master.values()),
        "details": details,
    }


def dispatch_score(
    *,
    assigned: int | None,
    assign_to_high: int,
    assign_to_ok: int,
    buffer_over_3d: int,
    prev_buffer_over_3d: int | None,
) -> float | None:
    if assigned is None:
        return None
    if assigned <= 0:
        score = 100.0
    else:
        score = (
            100.0
            - 60.0 * (assign_to_high / assigned)
            - 20.0 * (assign_to_ok / assigned)
        )
    if prev_buffer_over_3d is not None and buffer_over_3d > prev_buffer_over_3d:
        score -= 15.0
    return round(max(0.0, min(100.0, score)), 2)


def merge_masters_with_assignments(
    masters: list[dict[str, Any]],
    assignments: dict[str, Any],
) -> list[dict[str, Any]]:
    by_key = {m["master_key"]: dict(m) for m in masters}
    for a in assignments.get("per_master") or []:
        key = a["master_key"]
        row = by_key.get(key)
        if not row:
            row = {
                "master_key": key,
                "display_name": a.get("display_name") or key,
                "open_count": 0,
                "age_sum_days": 0.0,
                "rework_orders": 0,
                "no_diag_count": 0,
                "load_index": 0.0,
                "zone": ZONE_LOW,
                "assigned_from_buffer": 0,
                "assign_quality": None,
            }
            by_key[key] = row
        row["assigned_from_buffer"] = int(a.get("assigned_from_buffer") or 0)
        row["assign_quality"] = a.get("assign_quality")
    out = list(by_key.values())
    out.sort(
        key=lambda r: (
            -int(r.get("assigned_from_buffer") or 0),
            -float(r.get("load_index") or 0),
            str(r.get("display_name") or "").lower(),
        )
    )
    return out


def build_day_payload(
    orders: list[dict[str, Any]],
    *,
    day: date | None = None,
    prev_buffer_ids: list[str] | None = None,
    prev_masters: list[dict[str, Any]] | None = None,
    prev_buffer_over_3d: int | None = None,
    prev_day: str | None = None,
) -> dict[str, Any]:
    """prev_day — дата снимка, с которым сравниваем (не обязательно вчера)."""
    day = day or date.today()
    day_s = day.isoformat()
    buf = build_buffer_snapshot(orders, as_of=day)
    masters = build_master_loads(orders, as_of=day)

    if prev_buffer_ids is None:
        assignments = {
            "assigned_from_buffer": None,
            "assign_to_high": 0,
            "assign_to_ok": 0,
            "assign_to_low": 0,
            "assign_unknown": 0,
            "per_master": [],
            "details": [],
        }
    else:
        assignments = classify_assignments(
            prev_buffer_ids=prev_buffer_ids,
            orders=orders,
            prev_masters=prev_masters,
        )

    masters = merge_masters_with_assignments(masters, assignments)
    zone_counts = {ZONE_HIGH: 0, ZONE_OK: 0, ZONE_LOW: 0}
    for m in masters:
        z = m.get("zone") or ZONE_LOW
        if z in zone_counts:
            zone_counts[z] += 1

    loads = [float(m["load_index"]) for m in masters]
    avg_load = round(sum(loads) / len(loads), 2) if loads else None
    assigned_n = assignments["assigned_from_buffer"]
    score = dispatch_score(
        assigned=assigned_n,
        assign_to_high=int(assignments["assign_to_high"]),
        assign_to_ok=int(assignments["assign_to_ok"]),
        buffer_over_3d=int(buf["buffer_over_3d"]),
        prev_buffer_over_3d=prev_buffer_over_3d,
    )

    daily = {
        "day": day_s,
        "buffer_count": buf["buffer_count"],
        "buffer_over_3d": buf["buffer_over_3d"],
        "assigned_from_buffer": assigned_n,
        "masters_high": zone_counts[ZONE_HIGH],
        "masters_ok": zone_counts[ZONE_OK],
        "masters_low": zone_counts[ZONE_LOW],
        "assign_to_high": assignments["assign_to_high"],
        "assign_to_ok": assignments["assign_to_ok"],
        "assign_to_low": assignments["assign_to_low"],
        "assign_unknown": assignments["assign_unknown"],
        "avg_load_index": avg_load,
        "dispatch_score": score,
        "prev_day": prev_day if prev_buffer_ids is not None else None,
        "gap_days": (
            (day - date.fromisoformat(prev_day)).days
            if prev_day and prev_buffer_ids is not None
            else None
        ),
    }
    return {
        "day": day_s,
        "daily": daily,
        "masters": masters,
        "buffer_ids": buf["buffer_ids"],
        "assignment_details": assignments.get("details") or [],
    }
