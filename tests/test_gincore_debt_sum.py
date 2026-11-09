from modules.gincore.client import GincoreClient
from modules.vyrobotka.verify import crm_totals_from_payment

SAMPLE_LIST_HTML = """
<table class="table-of-repair-orders">
  <thead><tr>
    <td></td><td>№</td><td></td><td>П</td><td>М</td><td>Маст</td><td>Ст</td>
    <td></td><td></td><td>У</td><td>К</td>
    <td>Стоимость</td>
    <td><div class="td-relative"><div class="js-repair-orders-debits-sum"></div>Оплачено</div></td>
    <td>Клиент</td>
  </tr></thead>
  <tbody>
    <tr>
      <td></td><td>1001</td><td></td><td>a</td><td>b</td><td>c</td><td>Готов</td>
      <td></td><td></td><td>dev</td><td>kit</td>
      <td><span>2000</span></td><td>0</td><td>Клиент</td>
    </tr>
    <tr>
      <td></td><td>1002</td><td></td><td>a</td><td>b</td><td>c</td><td>Выдан</td>
      <td></td><td></td><td>dev</td><td>kit</td>
      <td><span>1000</span></td><td>250</td><td>Клиент</td>
    </tr>
  </tbody>
</table>
"""


def test_parse_repair_orders_expected_payment_sum():
    totals = GincoreClient.parse_repair_orders_payment_totals(SAMPLE_LIST_HTML)
    assert totals["orders"] == 2
    assert totals["cost_sum"] == 3000
    assert totals["paid_sum"] == 250
    assert totals["expected_payment_sum"] == 2750  # 2000 + 750


def test_parse_repair_orders_debt_rows():
    rows = GincoreClient.parse_repair_orders_debt_rows(SAMPLE_LIST_HTML)
    assert len(rows) == 2
    by_id = {r["ticket"]: r for r in rows}
    assert by_id["1001"]["status"] == "Готов"
    assert by_id["1001"]["cost"] == 2000
    assert by_id["1001"]["paid"] == 0
    assert by_id["1001"]["debt"] == 2000
    assert by_id["1002"]["status"] == "Выдан"
    assert by_id["1002"]["debt"] == 750


# Как в CRM: «Итого со скидкой» без name (только id), span.total-sum = 0 из работ.
SAMPLE_ORDER_PAYMENT_HTML = """
<div class="panel-body">
  <div class="row">Форма оплаты: Наличные</div>
  <input name="sum" id="order-total" value="1500"/>
  <input name="discount" value="0"/>
  <input id="order_sum" value="1500"/>
  <input id="order-sum-paid" value="0"/>
  <input name="prepay" value="0"/>
  <input name="order_sum_pay_current" value="1500"/>
  <input name="order_sum_pay" id="order_sum_pay" value="1500"/>
  <span class="total-sum">0</span>
  <label><input id="total-sum-checkbox" type="checkbox"/> "Итого" = "Стоимость ремонта"</label>
</div>
"""


def test_parse_order_payment_ignores_works_total_span():
    pay = GincoreClient.parse_order_payment(SAMPLE_ORDER_PAYMENT_HTML)
    assert pay["repair_cost"] == 1500
    assert pay["total_with_discount"] == 1500  # #order_sum, не span.total-sum
    assert pay["paid"] == 0
    assert pay["due"] == 1500
    total, paid, debt = crm_totals_from_payment(pay)
    assert total == 1500 and paid == 0 and debt == 1500


def _list_html(tickets, footer: int | None = None) -> str:
    rows = "".join(
        f"<tr><td></td><td>{t}</td><td></td><td>a</td><td>b</td><td>c</td>"
        f"<td>Готов</td><td></td><td></td><td>dev</td><td>kit</td>"
        f"<td><span>1000</span></td><td>0</td><td>Клиент</td></tr>"
        for t in tickets
    )
    foot = f"<div>Всего: {footer}</div>" if footer is not None else ""
    return f'<table class="table-of-repair-orders"><tbody>{rows}</tbody></table>{foot}'


class _FakePagesClient(GincoreClient):
    def __init__(self, pages, footer):  # noqa: D401 — без сети
        self._pages = pages
        self._footer = footer

    async def _repair_orders_page(self, *, crm_params=None, page=1, **_):
        import re

        tickets = self._pages[page - 1] if page <= len(self._pages) else []
        html = _list_html(tickets, self._footer)
        m = re.search(r"Всего:\s*([\d\s]+)", html)
        return {"page": page, "count": int(m.group(1)) if m else 0, "html": html}


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_pay_list_paginates_without_footer():
    pages = [list(range(10000, 10030)), list(range(10030, 10060)), list(range(10060, 10081))]
    client = _FakePagesClient(pages, footer=None)
    data = _run(client.fetch_orders_expected_payment_list(page_pause_s=0))
    assert data["orders"] == 81
    assert data["expected_payment_sum"] == 81000
    assert data["complete"] is True


def test_pay_list_paginates_with_footer():
    pages = [list(range(10000, 10030)), list(range(10030, 10060)), list(range(10060, 10081))]
    client = _FakePagesClient(pages, footer=81)
    data = _run(client.fetch_orders_expected_payment_list(page_pause_s=0))
    assert data["orders"] == 81
    assert data["complete"] is True


def test_pay_list_incomplete_when_pages_missing():
    # подвал говорит 81, а страница 2 пустая → complete=False
    client = _FakePagesClient([list(range(10000, 10030))], footer=81)
    data = _run(client.fetch_orders_expected_payment_list(page_pause_s=0))
    assert data["orders"] == 30
    assert data["complete"] is False
    assert data["stop_reason"] == "empty_page"


def test_pay_list_stops_when_page_param_ignored():
    same = list(range(10000, 10030))
    client = _FakePagesClient([same, same, same], footer=None)
    data = _run(client.fetch_orders_expected_payment_list(page_pause_s=0))
    assert data["orders"] == 30
    assert data["stop_reason"] == "no_new_rows"
