"""Unit tests for service-center quality feed/metrics parsing."""

from __future__ import annotations

from datetime import date

from modules.gincore.quality import (
    compute_order_kpi,
    compute_quality_metrics,
    compute_rework_kpi,
    parse_order_feed_events,
    parse_quality_list_rows,
    quality_crm_params,
)


SAMPLE_LIST_HTML = """
<table class="table-of-repair-orders">
<tbody>
<tr>
  <td></td>
  <td>123456</td>
  <td></td>
  <td><span class="visible-lg">Иван</span><span class="orders-small-muted" title="1 Октябрь 2026 10:00:00">1 Окт.</span></td>
  <td><span class="visible-lg">Менеджер</span></td>
  <td><span class="visible-lg">Петров</span></td>
  <td><button class="as_button"><span class="btn-title">На диагностике</span></button></td>
  <td></td><td></td>
  <td><span class="visible-lg">iPhone 12</span></td>
  <td></td><td></td><td></td>
  <td><span class="visible-lg">Клиент</span></td>
  <td></td>
  <td><span class="visible-lg">Центр</span></td>
</tr>
</tbody>
</table>
"""

# CRM live feed is newest-first in HTML.
SAMPLE_FEED_HTML = """
<table class="js-comments-table">
<tr class="comment-status">
  <td class="order-comments__date">4 окт.</td>
  <td class="order-comments__author">Админ</td>
  <td class="order-comments__body" data-comment_type="comment-status">Изменил статус на На согласовании</td>
</tr>
<tr>
  <td class="order-comments__date">3 окт.</td>
  <td class="order-comments__author">Петров</td>
  <td class="order-comments__body" data-comment_type="">Согласован ремонт 2500 грн</td>
</tr>
<tr class="comment-call">
  <td class="order-comments__date">2 окт.</td>
  <td class="order-comments__author">Система</td>
  <td class="comment_data">
    <div class="order-comments__body comment-call" data-comment_type="comment-call">Исходящий</div>
    <div class="record"><a href="#" class="play_record" data-id="1"><span class="fa"></span></a></div>
  </td>
</tr>
<tr class="comment-call">
  <td class="order-comments__date">2 окт.</td>
  <td class="order-comments__author">Система</td>
  <td class="order-comments__body comment-call" data-comment_type="comment-call">Входящий звонок без оператора</td>
</tr>
<tr class="comment-engineer">
  <td class="order-comments__date">1 окт.</td>
  <td class="order-comments__author">Админ</td>
  <td class="order-comments__body" data-comment_type="comment-engineer">Изменил мастера на Петров</td>
</tr>
</table>
"""

# Agreement + failed outbound, no «Не дозвонились» — manager mistake.
SAMPLE_MANAGER_MISS_HTML = """
<table class="js-comments-table">
<tr class="comment-call">
  <td class="order-comments__date">2 окт.</td>
  <td class="order-comments__author">Инна</td>
  <td class="order-comments__body comment-call" data-comment_type="comment-call">Исходящий</td>
</tr>
<tr>
  <td class="order-comments__date">2 окт.</td>
  <td class="order-comments__author">Инна</td>
  <td class="order-comments__body">123769 Согласуйте (Восстановление головы, 1500)</td>
</tr>
<tr class="comment-engineer">
  <td class="order-comments__date">10 сен.</td>
  <td class="order-comments__author">Аля</td>
  <td class="order-comments__body" data-comment_type="comment-engineer">Изменил мастера на Сатаулов Владислав</td>
</tr>
<tr class="comment-call">
  <td class="order-comments__date">7 сен.</td>
  <td class="order-comments__author">Виктория</td>
  <td class="comment_data">
    <div class="order-comments__body comment-call" data-comment_type="comment-call">Входящий</div>
    <div class="record"><a href="#" class="play_record" data-id="9"><span class="fa"></span></a></div>
  </td>
</tr>
</table>
"""


def test_quality_crm_params():
    p = quality_crm_params()
    assert "dep" in p and "st" in p
    assert "1-a" in p["dep"]
    assert "36" in p["st"]


def test_parse_quality_list_rows():
    rows = parse_quality_list_rows(SAMPLE_LIST_HTML)
    assert len(rows) == 1
    r = rows[0]
    assert r["order_id"] == "123456"
    assert r["status"] == "На диагностике"
    assert r["engineer"] == "Петров"
    assert r["device"] == "iPhone 12"
    assert r["accepted_at"] == "2026-10-01"
    assert "На диагностике" in r["list_fingerprint"]


def test_parse_feed_and_metrics():
    feed = parse_order_feed_events(SAMPLE_FEED_HTML, accepted=date(2026, 10, 1))
    assert len(feed) == 5
    assert feed[0]["kind"] == "master_changed"
    assert feed[0]["master_name"] == "Петров"
    assert feed[1]["call_dir"] == "missed"
    assert feed[1]["call_ok"] is False
    assert feed[2]["call_dir"] == "outbound"
    assert feed[2]["call_ok"] is True

    m = compute_quality_metrics(
        accepted_at="2026-10-01",
        repair_cost=2500.0,
        feed=feed,
        today=date(2026, 10, 7),
    )
    assert m["total_days"] == 6
    assert m["wait_master_days"] == 0
    assert m["master_name"] == "Петров"
    assert m["diag_days"] == 2  # master 1 okt -> agreement comment 3 окт
    assert m["agreement_source"] == "comment_hint"
    assert m["calls_inbound"] == 0
    assert m["calls_missed"] == 1
    assert m["calls_outbound_ok"] == 1
    assert m["callback_same_day"] == 1
    # пропуск + исходящий в тот же день → recovered; KPI между 0 и 100
    assert m["calls_missed_recovered"] == 1
    assert m["calls_missed_unrecovered"] == 0
    assert m["calls_kpi"] is not None and 40 <= m["calls_kpi"] <= 80
    assert m["manager_no_answer_missed"] is False


def test_calls_comm_kpi_patterns():
    today = date(2026, 10, 7)

    pure_out = compute_quality_metrics(
        accepted_at="2026-10-01",
        repair_cost=None,
        feed=[
            {
                "date_iso": "2026-10-02",
                "kind": "call",
                "call_dir": "outbound",
                "call_ok": True,
                "text": "Исходящий",
            },
            {
                "date_iso": "2026-10-03",
                "kind": "call",
                "call_dir": "outbound",
                "call_ok": True,
                "text": "Исходящий",
            },
        ],
        today=today,
    )
    assert pure_out["calls_kpi"] == 100

    no_callback = compute_quality_metrics(
        accepted_at="2026-10-01",
        repair_cost=None,
        feed=[
            {
                "date_iso": "2026-10-02",
                "kind": "call",
                "call_dir": "missed",
                "call_ok": False,
                "text": "Входящий без оператора",
            }
        ],
        today=today,
    )
    assert no_callback["calls_missed_unrecovered"] == 1
    assert no_callback["calls_kpi"] is not None and no_callback["calls_kpi"] < 40

    client_first = compute_quality_metrics(
        accepted_at="2026-10-01",
        repair_cost=None,
        feed=[
            {
                "date_iso": "2026-10-02",
                "kind": "call",
                "call_dir": "inbound",
                "call_ok": True,
                "text": "Входящий",
            }
        ],
        today=today,
    )
    assert client_first["calls_kpi"] is not None
    assert client_first["calls_kpi"] < pure_out["calls_kpi"]
    assert client_first["calls_kpi"] > no_callback["calls_kpi"]

    # Успешный входящий до сдачи — норма, KPI не портит (и не считается).
    pre_ok_only = compute_quality_metrics(
        accepted_at="2026-10-05",
        repair_cost=None,
        feed=[
            {
                "date_iso": "2026-10-02",
                "kind": "call",
                "call_dir": "inbound",
                "call_ok": True,
                "text": "Входящий",
            }
        ],
        today=today,
    )
    assert pre_ok_only["calls_pre_inbound_ok"] == 1
    assert pre_ok_only["calls_kpi"] is None

    # Неуспешный + в тот же день успешный входящий (как 124464) — не «до сдачи не связались».
    pre_retry_in = compute_quality_metrics(
        accepted_at="2026-10-05",
        repair_cost=None,
        feed=[
            {
                "date_iso": "2026-10-02",
                "kind": "call",
                "call_dir": "inbound",
                "call_ok": False,
                "text": "Входящий",
            },
            {
                "date_iso": "2026-10-02",
                "kind": "call",
                "call_dir": "inbound",
                "call_ok": True,
                "text": "Входящий",
            },
        ],
        today=today,
    )
    assert pre_retry_in["calls_pre_miss_same_day"] == 1
    assert pre_retry_in["calls_pre_miss_until_visit"] == 0
    assert pre_retry_in["calls_kpi"] is not None and pre_retry_in["calls_kpi"] > 0

    # Неуспешный до сдачи и без связи до прихода — хуже, чем same-day.
    pre_miss = compute_quality_metrics(
        accepted_at="2026-10-05",
        repair_cost=None,
        feed=[
            {
                "date_iso": "2026-10-02",
                "kind": "call",
                "call_dir": "missed",
                "call_ok": False,
                "text": "Входящий без оператора",
            }
        ],
        today=today,
    )
    assert pre_miss["calls_pre_miss_until_visit"] == 1
    assert pre_miss["calls_kpi"] is not None
    assert pre_miss["calls_kpi"] < pre_retry_in["calls_kpi"]

    pre_cb2 = compute_quality_metrics(
        accepted_at="2026-10-05",
        repair_cost=None,
        feed=[
            {
                "date_iso": "2026-10-02",
                "kind": "call",
                "call_dir": "missed",
                "call_ok": False,
                "text": "Входящий без оператора",
            },
            {
                "date_iso": "2026-10-02",
                "kind": "call",
                "call_dir": "outbound",
                "call_ok": True,
                "text": "Исходящий",
            },
            {
                "date_iso": "2026-10-06",
                "kind": "call",
                "call_dir": "outbound",
                "call_ok": True,
                "text": "Исходящий",
            },
        ],
        today=today,
    )
    pre_miss2 = compute_quality_metrics(
        accepted_at="2026-10-05",
        repair_cost=None,
        feed=[
            {
                "date_iso": "2026-10-02",
                "kind": "call",
                "call_dir": "missed",
                "call_ok": False,
                "text": "Входящий без оператора",
            },
            {
                "date_iso": "2026-10-06",
                "kind": "call",
                "call_dir": "outbound",
                "call_ok": True,
                "text": "Исходящий",
            },
        ],
        today=today,
    )
    assert pre_cb2["calls_kpi"] > pre_miss2["calls_kpi"]


def test_manager_no_answer_missed_flag():
    feed = parse_order_feed_events(
        SAMPLE_MANAGER_MISS_HTML, accepted=date(2026, 9, 7)
    )
    m = compute_quality_metrics(
        accepted_at="2026-09-07",
        repair_cost=None,
        feed=feed,
        engineer="Сатаулов Владислав",
        status="Принят в ремонт",
        today=date(2026, 10, 7),
    )
    assert m["agreement_at"] == "2026-10-02"
    assert m["agreement_source"] == "comment_hint"
    assert m["diag_days"] == 22  # 10 сен → 2 окт
    assert m["calls_outbound_fail"] == 1
    assert m["calls_inbound_ok"] == 1
    assert m["manager_no_answer_missed"] is True

    fixed = compute_quality_metrics(
        accepted_at="2026-09-07",
        repair_cost=None,
        feed=feed,
        engineer="Сатаулов Владислав",
        status="Не дозвонились",
        today=date(2026, 10, 7),
    )
    assert fixed["manager_no_answer_missed"] is False

    on_agree = compute_quality_metrics(
        accepted_at="2026-09-07",
        repair_cost=None,
        feed=feed,
        engineer="Сатаулов Владислав",
        status="На согласовании",
        today=date(2026, 10, 7),
    )
    assert on_agree["manager_no_answer_missed"] is False


def test_manager_recovered_after_failed_outbound():
    """Неуспешный исходящий, потом успешный — флаг не ставим (как 124260)."""
    feed = [
        {
            "date_iso": "2026-09-29",
            "kind": "comment",
            "text": "узгодити заміна 1800 грн",
            "call_dir": None,
            "call_ok": None,
        },
        {
            "date_iso": "2026-09-29",
            "kind": "call",
            "call_dir": "outbound",
            "call_ok": False,
            "text": "Исходящий",
        },
        {
            "date_iso": "2026-09-29",
            "kind": "call",
            "call_dir": "outbound",
            "call_ok": True,
            "text": "Исходящий",
        },
        {
            "date_iso": "2026-09-29",
            "kind": "status_changed",
            "status_name": "В процессе ремонта",
            "text": "Изменил статус на В процессе ремонта",
            "call_dir": None,
            "call_ok": None,
        },
    ]
    m = compute_quality_metrics(
        accepted_at="2026-09-26",
        repair_cost=None,
        feed=feed,
        engineer="Галанчук Вадим",
        status="В процессе ремонта",
        today=date(2026, 10, 7),
    )
    assert m["agreement_at"] == "2026-09-29"
    assert m["calls_outbound_fail"] == 1
    assert m["calls_outbound_ok"] == 1
    assert m["manager_no_answer_missed"] is False


def test_manager_recovered_client_came_in_person():
    """Исходящий ✗, клиент пришёл сам — «согл» и статус в ремонт (как 124223)."""
    feed = [
        {
            "date_iso": "2026-10-01",
            "kind": "comment",
            "text": "1500",
            "call_dir": None,
            "call_ok": None,
        },
        {
            "date_iso": "2026-10-01",
            "kind": "status_changed",
            "status_name": "На согласовании",
            "text": "Изменил статус на На согласовании",
            "call_dir": None,
            "call_ok": None,
        },
        {
            "date_iso": "2026-10-01",
            "kind": "call",
            "call_dir": "outbound",
            "call_ok": False,
            "text": "Исходящий",
        },
        {
            "date_iso": "2026-10-01",
            "kind": "comment",
            "text": "согл",
            "call_dir": None,
            "call_ok": None,
        },
        {
            "date_iso": "2026-10-01",
            "kind": "status_changed",
            "status_name": "В процессе ремонта",
            "text": "Изменил статус на В процессе ремонта",
            "call_dir": None,
            "call_ok": None,
        },
    ]
    m = compute_quality_metrics(
        accepted_at="2026-09-25",
        repair_cost=1500.0,
        feed=feed,
        engineer="Ефимов",
        status="В процессе ремонта",
        today=date(2026, 10, 7),
    )
    assert m["calls_outbound_fail"] == 1
    assert m["manager_no_answer_missed"] is False


def test_rework_metrics():
    feed = [
        {
            "date_iso": "2026-03-03",
            "kind": "status_changed",
            "status_name": "Готов",
            "text": "Изменил статус на Готов",
        },
        {
            "date_iso": "2026-03-09",
            "kind": "status_changed",
            "status_name": "Принят на доработку",
            "text": "Изменил статус на Принят на доработку",
        },
        {
            "date_iso": "2026-06-18",
            "kind": "master_changed",
            "master_name": "Дубовой",
            "text": "Изменил мастера на Дубовой",
        },
        {
            "date_iso": "2026-06-29",
            "kind": "comment",
            "text": "Согласуйте ремонт 2000 грн",
        },
        {
            "date_iso": "2026-07-04",
            "kind": "status_changed",
            "status_name": "В процессе ремонта",
            "text": "Изменил статус на В процессе ремонта",
        },
    ]
    m = compute_quality_metrics(
        accepted_at="2026-01-20",
        repair_cost=None,
        feed=feed,
        engineer="Дубовой",
        status="В процессе ремонта",
        today=date(2026, 10, 7),
    )
    assert m["rework_count"] == 1
    assert m["last_rework_at"] == "2026-03-09"
    assert m["rework_total_days"] == (date(2026, 10, 7) - date(2026, 3, 9)).days
    # диаг: мастер 18.06 → согл 29.06
    assert m["rework_diag_days"] == 11
    # ремонт: с согласования 29.06
    assert m["rework_repair_days"] == (date(2026, 10, 7) - date(2026, 6, 29)).days
    assert m["rework_kpi"] is not None and m["rework_kpi"] < 50  # долго с доработки

    none = compute_quality_metrics(
        accepted_at="2026-10-01",
        repair_cost=None,
        feed=[],
        engineer="X",
        status="Принят в ремонт",
        today=date(2026, 10, 7),
    )
    assert none["rework_count"] == 0
    assert none["rework_total_days"] is None
    assert none["rework_kpi"] is None

    fresh = compute_rework_kpi(
        rework_count=1,
        rework_diag_days=1,
        rework_repair_days=None,
        rework_total_days=1,
    )
    stuck = compute_rework_kpi(
        rework_count=1,
        rework_diag_days=20,
        rework_repair_days=None,
        rework_total_days=20,
    )
    multi = compute_rework_kpi(
        rework_count=3,
        rework_diag_days=2,
        rework_repair_days=2,
        rework_total_days=5,
    )
    assert fresh is not None and stuck is not None and multi is not None
    assert fresh > stuck
    assert fresh > multi


def test_order_kpi():
    good = compute_order_kpi(
        total_days=3,
        wait_master_days=0,
        diag_days=1,
        rework_kpi=None,
        calls_kpi=100,
    )
    slow = compute_order_kpi(
        total_days=30,
        wait_master_days=10,
        diag_days=14,
        rework_kpi=20,
        calls_kpi=30,
    )
    no_calls = compute_order_kpi(
        total_days=3,
        wait_master_days=0,
        diag_days=1,
        rework_kpi=None,
        calls_kpi=None,
    )
    assert good is not None and slow is not None and no_calls is not None
    assert good >= 90
    assert slow < 40
    assert good > slow
    assert no_calls >= 85  # без звонков веса перенормируются

    m = compute_quality_metrics(
        accepted_at="2026-10-01",
        repair_cost=None,
        feed=[
            {
                "date_iso": "2026-10-01",
                "kind": "master_changed",
                "master_name": "X",
                "text": "Изменил мастера на X",
            },
            {
                "date_iso": "2026-10-02",
                "kind": "call",
                "call_dir": "outbound",
                "call_ok": True,
                "text": "play_record",
            },
        ],
        engineer="X",
        status="В процессе ремонта",
        today=date(2026, 10, 7),
    )
    assert m["order_kpi"] is not None
    assert isinstance(m["order_kpi_parts"], list) and len(m["order_kpi_parts"]) >= 3
    assert all("weight_pct" in p for p in m["order_kpi_parts"])
    rw_part = next(p for p in m["order_kpi_parts"] if p["key"] == "rework")
    assert rw_part["score"] == 100
    assert "не было" in rw_part["detail"]


def test_closed_order_uses_issue_date_not_today():
    """Статус «Выдан» — сроки до даты выдачи, а не до today."""
    feed = [
        {
            "date_iso": "2026-01-02",
            "kind": "master_changed",
            "master_name": "Иванов",
            "text": "Изменил мастера на Иванов",
        },
        {
            "date_iso": "2026-01-05",
            "kind": "status_changed",
            "status_name": "В процессе ремонта",
            "text": "Изменил статус на В процессе ремонта",
        },
        {
            "date_iso": "2026-01-20",
            "kind": "status_changed",
            "status_name": "Выдан",
            "text": "Изменил статус на Выдан",
        },
    ]
    m = compute_quality_metrics(
        accepted_at="2026-01-01",
        repair_cost=None,
        feed=feed,
        engineer="Иванов",
        status="Выдан",
        today=date(2026, 10, 7),
    )
    assert m["is_closed"] is True
    assert m["closed_at"] == "2026-01-20"
    assert m["as_of"] == "2026-01-20"
    assert m["total_days"] == 19  # 01.01 → 20.01, не до октября
    open_m = compute_quality_metrics(
        accepted_at="2026-01-01",
        repair_cost=None,
        feed=feed[:-1],
        engineer="Иванов",
        status="В процессе ремонта",
        today=date(2026, 10, 7),
    )
    assert open_m["is_closed"] is False
    assert open_m["total_days"] == (date(2026, 10, 7) - date(2026, 1, 1)).days


def test_ready_status_stops_total_days():
    """Статус «Готов» — «всего дн» до даты готовности, не до сегодня."""
    feed = [
        {
            "date_iso": "2026-07-26",
            "kind": "master_changed",
            "master_name": "X",
            "text": "Изменил мастера на X",
        },
        {
            "date_iso": "2026-07-26",
            "kind": "status_changed",
            "status_name": "Готов",
            "text": "Изменил статус на Готов",
        },
    ]
    m = compute_quality_metrics(
        accepted_at="2026-07-25",
        repair_cost=None,
        feed=feed,
        engineer="X",
        status="Готов",
        today=date(2026, 10, 7),
    )
    assert m["is_ready"] is True
    assert m["ready_at"] == "2026-07-26"
    assert m["as_of"] == "2026-07-26"
    assert m["total_days"] == 1


def test_manager_recovered_status_after_fail_rework():
    """Исходящий ✗, позже «Принят на доработку» — ошибки нет (как 123711)."""
    feed = [
        {
            "date_iso": "2026-09-14",
            "kind": "comment",
            "text": "5500",
            "call_dir": None,
            "call_ok": None,
        },
        {
            "date_iso": "2026-09-18",
            "kind": "status_changed",
            "status_name": "Готов",
            "text": "Изменил статус на Готов",
            "call_dir": None,
            "call_ok": None,
        },
        {
            "date_iso": "2026-09-19",
            "kind": "call",
            "call_dir": "outbound",
            "call_ok": False,
            "text": "Исходящий",
        },
        {
            "date_iso": "2026-09-26",
            "kind": "status_changed",
            "status_name": "Принят на доработку",
            "text": "Изменил статус на Принят на доработку",
            "call_dir": None,
            "call_ok": None,
        },
    ]
    m = compute_quality_metrics(
        accepted_at="2026-09-04",
        repair_cost=5500.0,
        feed=feed,
        engineer="Сатаулов",
        status="Принят на доработку",
        today=date(2026, 10, 7),
    )
    assert m["manager_no_answer_missed"] is False


def test_master_from_list_when_no_feed_event():
    """Мастер при приёмке — в ленте нет «Изменил мастера»."""
    feed = [
        {
            "date": "9 сен.",
            "date_iso": "2026-09-09",
            "author": "Юрий",
            "text": "Изменил статус на На диагностике",
            "kind": "status_changed",
            "status_name": "На диагностике",
            "call_dir": None,
            "master_name": None,
        }
    ]
    m = compute_quality_metrics(
        accepted_at="2026-09-08",
        repair_cost=None,
        feed=feed,
        engineer="Дубовой Юрий Владимирович",
        today=date(2026, 10, 7),
    )
    assert m["total_days"] == 29
    assert m["wait_master_days"] == 0
    assert m["master_from_list"] is True
    assert m["master_name"] == "Дубовой Юрий Владимирович"
    assert m["master_assigned_at"] == "2026-09-08"

    waiting = compute_quality_metrics(
        accepted_at="2026-09-08",
        repair_cost=None,
        feed=feed,
        engineer="",
        today=date(2026, 10, 7),
    )
    assert waiting["wait_master_days"] == 29
    assert waiting["master_from_list"] is False
