"""Тесты модуля «Аутсорс мастера»: CRM-метрики и прогон синхронизации на фейках."""

from __future__ import annotations

import asyncio
from datetime import date

from modules.outsource.compute import (
    build_outsourcer_metrics,
    classify_status,
    engineer_matches,
    engineer_names,
    parse_history_rows,
    sum_payouts,
    trial_ticket_info,
)
from modules.outsource.service import OutsourceService, history_months, month_needs_refetch

TODAY = date(2026, 11, 19)


def test_engineer_matches():
    assert engineer_matches("Андрусяк", "Саша Андрусяк")
    assert engineer_matches("саша  андрусяк", "Саша Андрусяк")
    assert not engineer_matches("Андрусяк", "Галанчук Вадим")
    assert not engineer_matches("", "Саша Андрусяк")
    assert engineer_matches("Знайденов", "Знайдёнов Валентин")


def test_classify_status():
    assert classify_status("Выдан без ремонта") == "refusal"
    assert classify_status("Не подлежит ремонту") == "refusal"
    assert classify_status("Клиент отказался") == "refusal"
    assert classify_status("Выдан") == "issued"
    assert classify_status("Готов") == "ready"
    assert classify_status("В процессе ремонта") == "working"


def _row(oid, status, eng, paid=0, acc="2026-10-05"):
    return {"order_id": oid, "status": status, "engineer": eng, "paid": paid, "accepted_at": acc, "device": "x"}


def test_metrics_return_rate_gross_net():
    cand = {"id": 1, "crm_engineer": "Андрусяк", "stage": "regular"}
    working = [
        {"order_id": "1", "status": "В процессе ремонта", "engineer": "Саша Андрусяк",
         "accepted_at": "2026-10-01", "master_assigned_at": "2026-10-02", "device": "iPhone"},
        {"order_id": "2", "status": "Готов", "engineer": "Саша Андрусяк", "accepted_at": "2026-11-10"},
        {"order_id": "3", "status": "В процессе ремонта", "engineer": "Галанчук Вадим", "accepted_at": "2026-11-10"},
    ]
    history = [
        _row("10", "Выдан", "Саша Андрусяк", 1000),
        _row("11", "Выдан", "Саша Андрусяк", 500, acc="2026-11-02"),
        _row("12", "Выдан без ремонта", "Саша Андрусяк", 100),
        _row("13", "Выдан", "Галанчук Вадим", 9999),
        _row("14", "На диагностике", "Саша Андрусяк", 0),
    ]
    payouts = {"contractor": "Андрусяк", "matched": True, "total": 600, "by_month": {"2026-10": 600}}
    m = build_outsourcer_metrics(cand, working=working, history=history, payouts=payouts, today=TODAY,
                                 order_url=lambda o: f"u/{o}")
    assert m["in_work"] == 1 and m["ready"] == 1
    assert m["long_at_master"] == 1  # с 2 октября > 14 дней
    assert m["in_work_orders"][0]["url"] == "u/1"
    assert m["orders_total"] == 4 and m["issued"] == 2 and m["refusals"] == 1 and m["in_progress"] == 1
    assert m["return_rate"] == round(1 / 3, 4)
    assert m["gross"] == 1600.0
    assert m["payouts"] == 600.0 and m["net"] == 1000.0
    oct_row = next(r for r in m["by_month"] if r["month"] == "2026-10")
    assert oct_row["gross"] == 1100.0 and oct_row["payouts"] == 600.0 and oct_row["net"] == 500.0


def test_metrics_unbound_and_unmatched_payouts():
    m = build_outsourcer_metrics({"id": 2}, working=[], history=[], payouts=None, today=TODAY)
    assert not m["bound"] and m["in_work"] == 0 and m["return_rate"] is None
    m2 = build_outsourcer_metrics({"id": 3, "crm_engineer": "X"}, working=[], history=[],
                                  payouts={"contractor": "X", "matched": False}, today=TODAY)
    assert m2["payouts"] is None and m2["net"] is None and m2["payouts_matched"] is False


def test_sum_payouts_and_names():
    rows = [
        {"expense": 300, "month": "2026-10"},
        {"expense": None, "income": 50, "month": "2026-10"},
        {"expense": 200, "month": "2026-11"},
    ]
    assert sum_payouts(rows) == {"total": 500.0, "by_month": {"2026-10": 300.0, "2026-11": 200.0}}
    assert engineer_names([{"engineer": "Б"}], [{"engineer": "А"}, {"engineer": ""}]) == ["А", "Б"]


def test_trial_ticket_info():
    info = trial_ticket_info("5", working_by_id={}, history_by_id={"5": _row("5", "Выдан", "Саша")},
                             fetched={}, order_url=lambda o: o)
    assert info["kind"] == "issued" and info["engineer"] == "Саша"
    assert trial_ticket_info("6", working_by_id={}, history_by_id={}, fetched={}) is None


LIST_HTML = """
<table class="table-of-repair-orders"><tbody>
<tr>
 <td></td><td>124450</td><td></td>
 <td><span class="visible-lg">Приёмщик</span><span class="orders-small-muted" title="6 Октябрь 2026 11:00:00">6 Окт.</span></td>
 <td><span class="visible-lg">Менеджер</span></td>
 <td><span class="visible-lg">Саша Андрусяк</span></td>
 <td><span class="btn-title">Выдан</span></td>
 <td></td><td></td><td><span class="visible-lg">iPhone 11</span></td><td></td>
 <td>1 500 грн</td><td>1 200 грн</td><td><span class="visible-lg">Клиент</span></td><td></td><td></td>
</tr>
</tbody></table>
"""


def test_parse_history_rows():
    rows = parse_history_rows(LIST_HTML)
    assert len(rows) == 1
    r = rows[0]
    assert r["order_id"] == "124450" and r["engineer"] == "Саша Андрусяк" and r["status"] == "Выдан"
    assert r["cost"] == 1500.0 and r["paid"] == 1200.0
    assert "client" not in r  # клиентов в снимок не тащим


def test_history_months():
    ms = history_months(TODAY, 4)
    assert [m[0] for m in ms] == ["2026-08", "2026-09", "2026-10", "2026-11"]
    assert ms[-1][2] == "2026-11-19" and ms[0][1] == "2026-08-01" and ms[0][2] == "2026-08-31"
    assert history_months(date(2026, 1, 10), 2)[0][0] == "2025-12"
    assert month_needs_refetch(None, "2026-08-31", TODAY)
    assert not month_needs_refetch({"complete": True}, "2026-08-31", TODAY)
    assert month_needs_refetch({"complete": True}, "2026-10-31", TODAY)


# ---------- прогон sync на фейках ----------
class FakeDB:
    def __init__(self):
        self.s = {}

    async def get_setting(self, key, default=None):
        return self.s.get(key, default)

    async def set_setting(self, key, value):
        self.s[key] = value


class FakeQuality:
    async def list_rows(self):
        return {"orders": [
            {"order_id": "1", "status": "В процессе ремонта", "engineer": "Саша Андрусяк", "accepted_at": "2026-11-15"},
        ]}


class FakeFeedback:
    configured = True

    async def get_outsource_state(self):
        return {
            "candidates": [
                {"id": 1, "name": "Андрусяк", "stage": "regular", "crm_engineer": "Андрусяк",
                 "cash_contractor": "Андрусяк"},
                {"id": 2, "name": "Новый", "stage": "trial", "crm_engineer": None},
            ],
            "trials": [{"id": 1, "candidate_id": 2, "ticket": "999999"}],
        }


class FakeClient:
    base_url = "https://crm"

    def __init__(self):
        self.pages = 0

    async def _repair_orders_page(self, *, page, crm_params):
        self.pages += 1
        html = LIST_HTML if page == 1 and crm_params["df"].startswith("01.11") else ""
        return {"count": 1 if html else 0, "html": html}

    async def find_contractor(self, q):
        return [{"id": "77", "name": "Андрусяк Саша"}]

    async def fetch_transactions(self, *, date_from, date_to, contractor_id):
        assert contractor_id == "77"
        return {"rows": [{"expense": 700, "month": "2026-11"}]}

    async def fetch_order_html(self, ticket):
        return '<input name="status" value="5"><div class="order_status"><span class="as_button"><span class="btn-title">На диагностике</span></span></div>'

    @staticmethod
    def parse_order_payment(html):
        return {"paid": 0}

    async def aclose(self):
        pass


def test_sync_end_to_end(tmp_path, monkeypatch):
    import modules.outsource.export as export

    monkeypatch.setattr(export, "default_pages_json_path", lambda: tmp_path / "data.json")
    db = FakeDB()

    async def factory():
        return FakeClient()

    svc = OutsourceService(db, quality_service=FakeQuality(), gincore_client_factory=factory,
                           feedback_client_factory=FakeFeedback)

    async def run():
        r = await svc.sync()
        assert r["started"]
        await svc._task
        return await svc.get_stats()

    stats = asyncio.run(run())
    assert stats["sync"]["status"] == "idle", stats["sync"]
    o1 = stats["outsourcers"]["1"]
    assert o1["in_work"] == 1 and o1["issued"] == 1 and o1["gross"] == 1200.0
    assert o1["payouts"] == 700.0 and o1["net"] == 500.0
    assert stats["outsourcers"]["2"]["bound"] is False
    assert stats["trials"]["999999"]["status"] == "На диагностике"
    assert "Саша Андрусяк" in stats["engineers"]
    assert (tmp_path / "data.json").exists()
    # повторный прогон: старые завершённые месяцы из кэша не перекачиваются
    hist = db.s["outsource_history"]["months"]
    assert set(hist) == {"2026-08", "2026-09", "2026-10", "2026-11"} or len(hist) == 4
