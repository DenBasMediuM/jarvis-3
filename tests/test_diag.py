from datetime import date

from modules.diag.compute import categorize, category_stats, find_candidates, ticket_info

TODAY = date(2026, 11, 23)


def test_categorize():
    assert categorize("ноутбук microsoft 1950")[0] == "laptop"
    assert categorize("зар. станция PECRON E1000")[0] == "power_station"
    assert categorize("Ресанта АСН-2000/1")[0] == "inverter_ups"
    assert categorize("картридж HP 85A") == ("cartridge", 0)
    assert categorize("принтер Canon")[0] == "printer"
    assert categorize("фен Rowenta")[0] == "other"


def test_category_stats():
    hist = [
        {"device": "ноутбук HP", "status": "Выдан", "paid": 2000},
        {"device": "ноутбук Asus", "status": "Выдан без ремонта", "paid": 0},
        {"device": "ноутбук Acer", "status": "В процессе ремонта", "paid": 0},
    ]
    st = category_stats(hist)["laptop"]
    assert st["closed"] == 2 and st["refusal_share"] == 0.5 and st["avg_check"] == 2000


def _o(oid, device, status="Принят в ремонт", engineer="", agreement=None, feed=None, accepted="2026-11-20"):
    return {"order_id": oid, "device": device, "status": status, "engineer": engineer, "agreement_at": agreement,
            "accepted_at": accepted, "feed": feed or []}


def test_candidates():
    working = [
        _o("1", "ноутбук Lenovo"),  # буфер, сложный
        _o("2", "фен", engineer="Галанчук Вадим"),
        _o("3", "картридж HP"),  # исключён
        _o("4", "ИБП APC", status="В процессе ремонта", engineer="X", agreement="2026-11-21"),  # уже согласован
        _o("5", "телевизор LG", feed=[{"text": "погодити платну діагностику 1000 грн"}]),  # уже обсуждали
        _o("6", "кофемашина Delonghi", status="На диагностике", engineer="Садоян Дмитрий"),
        _o("7", "ноутбук HP"),  # уже взят
    ]
    stats = {"laptop": {"refusal_share": 0.4, "closed": 50}}
    c = find_candidates(working, today=TODAY, stats=stats, taken={"7"})
    tickets = [x["ticket"] for x in c]
    assert tickets[0] == "1"
    assert set(tickets) == {"1", "2", "6"}
    top = c[0]
    assert top["source"] == "buffer" and top["complexity"] == 3
    assert any("40%" in r for r in top["reasons"])
    assert next(x for x in c if x["ticket"] == "6")["source"] == "undiagnosed"


def test_ticket_info():
    i = ticket_info({"status": "Выдан без ремонта", "paid": 1000, "cost": 1000})
    assert i["closed"] and i["kind"] == "refusal" and i["paid"] == 1000
    assert ticket_info(None) is None


def test_service_sync(monkeypatch):
    import asyncio

    from modules.diag.service import DiagService

    class DB:
        def __init__(self):
            self.d = {"clients_history_v2": {"months": {"2026-10": {"rows": [
                {"order_id": "9", "device": "ноутбук HP", "status": "Выдан без ремонта", "paid": 0},
                {"order_id": "100", "device": "стабилизатор", "status": "Выдан без ремонта", "paid": 1000, "cost": 1000},
            ]}}}}

        async def get_setting(self, k, default=None):
            return self.d.get(k, default)

        async def set_setting(self, k, v):
            self.d[k] = v

        async def quality_list_orders(self):
            return [{"order_id": "2", "feed_json": '[{"text": "погодити платну діагностику 1000"}]'}]

    class Q:
        async def list_rows(self):
            return {"orders": [
                {"order_id": "1", "device": "ноутбук Lenovo", "status": "Принят в ремонт", "engineer": "", "accepted_at": "2026-11-20"},
                {"order_id": "2", "device": "телевизор", "status": "Принят в ремонт", "engineer": "", "accepted_at": "2026-11-20"},
                {"order_id": "3", "device": "ИБП", "status": "На диагностике", "engineer": "Садоян", "accepted_at": "2026-11-21"},
            ]}

    class FB:
        configured = True
        sent = None

        async def get_diag_state(self):
            return {"cases": [{"ticket": "3", "updated_at": "2026-11-23"}, {"ticket": "100", "updated_at": "2026-11-23"}, {"ticket": "555", "updated_at": "2026-11-23"}]}

        async def put_diag_snapshot(self, snap):
            FB.sent = snap

    fetched = []

    class Client:
        base_url = "https://crm"

        async def fetch_order_html(self, t):
            fetched.append(t)
            return "x"

        def parse_order_status(self, html):
            return {"status_name": "Выдан"}

        def parse_order_payment(self, html):
            return {"paid": 750, "repair_cost": 750}

        async def aclose(self):
            pass

    async def factory():
        return Client()

    db = DB()
    s = DiagService(db, quality_service=Q(), gincore_client_factory=factory, feedback_client_factory=lambda: FB())

    async def run():
        await s.sync()
        await s._task

    asyncio.run(run())
    assert db.d["diag_sync"]["status"] == "idle", db.d["diag_sync"]
    snap = FB.sent
    assert [c["ticket"] for c in snap["candidates"]] == ["1"]  # 2 — уже обсуждали, 3 — взят
    assert snap["tickets"]["3"]["status"] == "На диагностике"
    assert snap["tickets"]["100"]["paid"] == 1000 and snap["tickets"]["100"]["closed"]
    assert fetched == ["555"] and snap["tickets"]["555"]["paid"] == 750
    assert snap["categories"]["laptop"]["refusal_share"] == 1.0


def test_fresh_first():
    working = [_o("old", "ноутбук A", accepted="2026-09-01"), _o("new", "ноутбук B", accepted="2026-11-22")]
    c = find_candidates(working, today=TODAY, stats={}, taken=set())
    assert [x["ticket"] for x in c] == ["new", "old"]
    assert any("не продиагностирован ли" in r for r in c[1]["reasons"])
