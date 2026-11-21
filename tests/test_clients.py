from datetime import date

from modules.clients.compute import client_metrics, find_candidates, index_by_phone, split_client


def test_split_client():
    assert split_client("Геннадий Геннадий +380969195362") == ("Геннадий", "0969195362")
    assert split_client("Донченко Александра Донченко А... +380634267701") == ("Донченко Александра", "0634267701")
    assert split_client("ТОВ Ромашка 050 111 22 33") == ("ТОВ Ромашка", "0501112233")
    assert split_client("Без телефона")[1] == ""


def _r(oid, phone, day, status="Выдан", paid=1000, cost=1000, device="ноутбук", name="Іван"):
    return {"order_id": oid, "phone": phone, "accepted_at": day, "status": status, "paid": paid, "cost": cost, "device": device, "name": name}


TODAY = date(2026, 11, 21)


def test_client_metrics():
    rows = [
        _r("1", "0501112233", "2026-05-01"),
        _r("2", "0501112233", "2026-06-01", paid=500, cost=800),
        _r("3", "0671112233", "2026-07-01", status="Выдан без ремонта", paid=200, cost=200),
        _r("4", "0501112233", "2026-11-10", status="На диагностике", paid=0, cost=0),
    ]
    m = client_metrics(["0501112233", "0671112233"], index_by_phone(rows), today=TODAY)
    assert m["orders"] == 4
    assert m["issued"] == 2 and m["refusals"] == 1
    assert m["debt"] == 300 and m["debt_orders"][0]["ticket"] == "2"
    assert m["in_work"][0]["diag"] is True and m["in_work"][0]["days"] == 11
    assert m["last_order_at"] == "2026-11-10"
    assert m["avg_interval"] is not None
    assert m["asleep"] is False  # есть устройство в работе


def test_asleep_and_trend():
    rows = [_r(str(i), "0501112233", d) for i, d in enumerate(["2026-04-01", "2026-04-20", "2026-05-10", "2026-06-01", "2026-06-20"])]
    m = client_metrics(["0501112233"], index_by_phone(rows), today=TODAY)
    assert m["asleep"] is True  # интервал ~20 дн., а не было 150 дней


def test_candidates():
    rows = [
        _r("1", "0501112233", "2026-10-01", device="ноутбук", name="ТОВ Ромашка"),
        _r("2", "0501112233", "2026-10-01", device="принтер", name="ТОВ Ромашка"),
        _r("3", "0501112233", "2026-11-15", device="монітор", name="ТОВ Ромашка"),
        _r("4", "0670000000", "2026-11-01"),
        _r("5", "0670000000", "2026-11-12"),
        _r("6", "0990000000", "2026-09-01"),
        _r("7", "0931111111", "2026-11-01"),
        _r("8", "0931111111", "2026-11-02"),
    ]
    th = {"months": 6, "orders": 3, "recent_days": 60, "recent_orders": 2, "gross": 10000}
    c = find_candidates(index_by_phone(rows), today=TODAY, thresholds=th, skip_phones={"0931111111"})
    phones = [x["phone"] for x in c]
    assert phones[0] == "0501112233"
    assert "0670000000" in phones  # 2 за 60 дней
    assert "0990000000" not in phones  # один заказ
    assert "0931111111" not in phones  # уже в разделе / отклонён
    top = c[0]
    assert top["b2b"] is True and top["visits"] == 2 and len(top["devices"]) == 3
    assert any("нескольку" in r for r in top["reasons"])


def test_service_sync_end_to_end(monkeypatch):
    import asyncio

    import modules.clients.service as svc_mod
    from modules.clients.service import ClientsService

    today = date.today().isoformat()

    class DB:
        def __init__(self):
            self.d = {}

        async def get_setting(self, k, default=None):
            return self.d.get(k, default)

        async def set_setting(self, k, v):
            self.d[k] = v

    class FB:
        configured = True
        sent = None

        async def get_clients_state(self):
            return {
                "clients": [{"id": 1, "name": "ТОВ", "stage": "active", "phones": ["0501112233"]}],
                "decisions": [{"phone": "0990000000", "decision": "dismissed"}],
                "settings": {"thresholds": {"months": 6, "orders": 3, "recent_days": 60, "recent_orders": 2, "gross": 0}},
            }

        async def put_clients_snapshot(self, snap):
            FB.sent = snap
            return {"ok": True}

    rows = [
        {"order_id": "1", "phone": "0501112233", "accepted_at": today, "status": "Выдан", "paid": 1000, "cost": 1000, "device": "ноут", "name": "ТОВ"},
        {"order_id": "2", "phone": "0670000000", "accepted_at": today, "status": "Выдан", "paid": 500, "cost": 500, "device": "тел", "name": "Олег"},
        {"order_id": "3", "phone": "0670000000", "accepted_at": today, "status": "Выдан", "paid": 500, "cost": 500, "device": "тел", "name": "Олег"},
        {"order_id": "4", "phone": "0990000000", "accepted_at": today, "status": "Выдан", "paid": 500, "cost": 500, "device": "тел", "name": "Х"},
        {"order_id": "5", "phone": "0990000000", "accepted_at": today, "status": "Выдан", "paid": 500, "cost": 500, "device": "тел", "name": "Х"},
    ]
    calls = {"n": 0}

    class Client:
        base_url = "https://crm"

        async def _repair_orders_page(self, page, crm_params):
            calls["n"] += 1
            assert "dep" in crm_params
            return {"count": 0, "html": "p1" if page == 1 else ""}

        async def aclose(self):
            pass

    monkeypatch.setattr(svc_mod, "parse_history_rows", lambda html: list(rows) if html == "p1" else [])

    async def factory():
        return Client()

    db = DB()
    s = ClientsService(db, gincore_client_factory=factory, feedback_client_factory=lambda: FB())

    async def run():
        await s.sync()
        await s._task

    asyncio.run(run())
    st = db.d["clients_sync"]
    assert st["status"] == "idle", st
    snap = FB.sent
    assert snap["clients"]["1"]["orders"] == 1
    phones = [c["phone"] for c in snap["candidates"]]
    assert phones == ["0670000000"]  # клиент уже в разделе, 0990… отклонён
    assert snap["totals"]["orders_90"] >= 5
    assert db.d["clients_summary"]["candidates_total"] == 1
