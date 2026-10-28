"""Тесты коэффициента загрузки и ретроспективы буфера."""

from __future__ import annotations

from datetime import date

from modules.buffer_quality.compute import (
    ASSIGN_BAD,
    ASSIGN_GOOD,
    ASSIGN_OK,
    ASSIGN_UNKNOWN,
    ZONE_HIGH,
    ZONE_LOW,
    ZONE_OK,
    build_day_payload,
    build_master_loads,
    classify_assignments,
    dispatch_score,
    load_index_from_signals,
    zone_for_load,
)


def test_load_index_and_zones():
    low = load_index_from_signals(
        open_count=1, age_sum_days=2, rework_orders=0, no_diag_count=0
    )
    assert low < 40
    assert zone_for_load(low) == ZONE_LOW

    mid = load_index_from_signals(
        open_count=5, age_sum_days=20, rework_orders=1, no_diag_count=1
    )
    assert 40 <= mid <= 70
    assert zone_for_load(mid) == ZONE_OK

    high = load_index_from_signals(
        open_count=12, age_sum_days=60, rework_orders=4, no_diag_count=5
    )
    assert high > 70
    assert zone_for_load(high) == ZONE_HIGH


def test_build_master_loads_signals():
    as_of = date(2026, 10, 28)
    orders = [
        {
            "order_id": "1",
            "engineer": "Иван Петров",
            "status": "На диагностике",
            "accepted_at": "2026-10-20",
            "total_days": 8,
            "rework_count": 0,
            "agreement_at": None,
        },
        {
            "order_id": "2",
            "engineer": "Иван Петров",
            "status": "В процессе ремонта",
            "accepted_at": "2026-10-10",
            "total_days": 18,
            "rework_count": 1,
            "agreement_at": "2026-10-12",
        },
        {
            "order_id": "3",
            "engineer": "",
            "status": "Принят в ремонт",
            "accepted_at": "2026-10-25",
            "total_days": 3,
        },
        {
            "order_id": "4",
            "engineer": "не назначен",
            "status": "Принят в ремонт",
            "accepted_at": "2026-10-01",
            "total_days": 27,
        },
    ]
    masters = build_master_loads(orders, as_of=as_of)
    assert len(masters) == 1
    m = masters[0]
    assert m["display_name"] == "Иван Петров"
    assert m["open_count"] == 2
    assert m["rework_orders"] == 1
    assert m["no_diag_count"] == 1
    assert m["age_sum_days"] == 26.0
    assert m["zone"] in (ZONE_LOW, ZONE_OK, ZONE_HIGH)


def test_classify_assignments_uses_yesterday_zone():
    orders = [
        {"order_id": "101", "engineer": "Алексей"},
        {"order_id": "102", "engineer": "Борис"},
        {"order_id": "103", "engineer": ""},  # still buffer
    ]
    prev_masters = [
        {"master_key": "алексей", "zone": ZONE_LOW},
        {"master_key": "борис", "zone": ZONE_HIGH},
    ]
    out = classify_assignments(
        prev_buffer_ids=["101", "102", "103", "999"],
        orders=orders,
        prev_masters=prev_masters,
    )
    assert out["assigned_from_buffer"] == 2
    assert out["assign_to_low"] == 1
    assert out["assign_to_high"] == 1
    by_master = {p["master_key"]: p for p in out["per_master"]}
    assert by_master["алексей"]["assign_quality"] == ASSIGN_GOOD
    assert by_master["борис"]["assign_quality"] == ASSIGN_BAD


def test_classify_unknown_without_prev_master():
    out = classify_assignments(
        prev_buffer_ids=["1"],
        orders=[{"order_id": "1", "engineer": "Новый"}],
        prev_masters=[],
    )
    assert out["assign_unknown"] == 1
    assert out["per_master"][0]["assign_quality"] == ASSIGN_UNKNOWN


def test_dispatch_score_penalties():
    assert dispatch_score(
        assigned=None,
        assign_to_high=0,
        assign_to_ok=0,
        buffer_over_3d=5,
        prev_buffer_over_3d=4,
    ) is None
    good = dispatch_score(
        assigned=10,
        assign_to_high=0,
        assign_to_ok=0,
        buffer_over_3d=3,
        prev_buffer_over_3d=5,
    )
    assert good == 100.0
    bad = dispatch_score(
        assigned=10,
        assign_to_high=5,
        assign_to_ok=5,
        buffer_over_3d=8,
        prev_buffer_over_3d=5,
    )
    # 100 - 30 - 10 - 15 = 45
    assert bad == 45.0


def test_build_day_payload_first_day_null_assigned():
    orders = [
        {
            "order_id": "1",
            "engineer": "",
            "status": "Принят в ремонт",
            "accepted_at": "2026-10-20",
            "total_days": 8,
        },
        {
            "order_id": "2",
            "engineer": "Мастер А",
            "status": "В процессе ремонта",
            "accepted_at": "2026-10-25",
            "total_days": 3,
            "rework_count": 0,
            "agreement_at": "2026-10-26",
        },
    ]
    day1 = build_day_payload(orders, day=date(2026, 10, 28), prev_buffer_ids=None)
    assert day1["daily"]["buffer_count"] == 1
    assert day1["daily"]["buffer_over_3d"] == 1
    assert day1["daily"]["assigned_from_buffer"] is None
    assert day1["daily"]["dispatch_score"] is None
    assert "1" in day1["buffer_ids"]

    # day2: order 1 got a master who was low yesterday
    orders2 = [
        {
            "order_id": "1",
            "engineer": "Мастер А",
            "status": "На диагностике",
            "accepted_at": "2026-10-20",
            "total_days": 9,
            "rework_count": 0,
        },
        {
            "order_id": "2",
            "engineer": "Мастер А",
            "status": "В процессе ремонта",
            "accepted_at": "2026-10-25",
            "total_days": 4,
            "rework_count": 0,
            "agreement_at": "2026-10-26",
        },
    ]
    day2 = build_day_payload(
        orders2,
        day=date(2026, 10, 29),
        prev_buffer_ids=day1["buffer_ids"],
        prev_masters=day1["masters"],
        prev_buffer_over_3d=day1["daily"]["buffer_over_3d"],
    )
    assert day2["daily"]["assigned_from_buffer"] == 1
    assert day2["daily"]["assign_to_low"] + day2["daily"]["assign_to_ok"] + day2[
        "daily"
    ]["assign_to_high"] + day2["daily"]["assign_unknown"] == 1
    assert day2["daily"]["dispatch_score"] is not None
    m = next(x for x in day2["masters"] if x["master_key"] == "мастер а")
    assert m["assigned_from_buffer"] == 1
    assert m["assign_quality"] in (ASSIGN_GOOD, ASSIGN_OK, ASSIGN_BAD, ASSIGN_UNKNOWN)
