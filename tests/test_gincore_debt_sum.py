from modules.gincore.client import GincoreClient

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
