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
