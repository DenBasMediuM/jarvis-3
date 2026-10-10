from modules.gincore.branch_kpi import (
    acceptances_index,
    label_to_year_month,
    months_ytd,
    parse_branch_chart,
    parse_pnl_tfoot,
    return_rate,
)


def test_label_to_year_month():
    assert label_to_year_month("01.26") == (2026, 1)
    assert label_to_year_month("10.26") == (2026, 10)
    assert label_to_year_month("bad") is None


def test_months_ytd():
    from datetime import date

    assert months_ytd(2026, today=date(2026, 3, 15)) == [
        (2026, 1),
        (2026, 2),
        (2026, 3),
    ]


def test_parse_branch_chart_and_index():
    html = """
    <script>
    ModuleImports.onReady('dashboard', function(){
      $(function(){
        dashboard.branchChart.initChart({"labels":["01.26","02.26"],"branches":{"1":{"id":1,"title":"СЦ Каретный"},"13":{"id":13,"title":"СЦ Сегедская"},"31":{"id":31,"title":"СЦ Левитан"}},"data":{"1":[258,217],"13":[197,193],"31":[53,41]},"max_value":258});
      });
    });
    </script>
    """
    chart = parse_branch_chart(html)
    assert chart["labels"] == ["01.26", "02.26"]
    idx = acceptances_index(chart)
    assert idx[(2026, 1)]["karetn"] == 258
    assert idx[(2026, 1)]["seged"] == 197
    assert idx[(2026, 1)]["levitan"] == 53
    assert idx[(2026, 2)]["karetn"] == 217


def test_parse_pnl_tfoot_matches_xpath():
    html = """
    <table><tfoot>
      <tr><td></td></tr>
      <tr><td></td></tr>
      <tr>
        <td></td>
        <td><span class="btn-xs btn-warning">₴ -10930.00</span></td>
        <td><span class="btn-xs btn-success">₴ 44850.00</span></td>
        <td><span class="btn-xs btn-warning">₴ -55780.00</span></td>
      </tr>
    </tfoot></table>
    """
    pnl = parse_pnl_tfoot(html)
    assert pnl["net_profit"] == -10930.0
    assert pnl["gross_profit"] == 44850.0
    assert pnl["expense"] == -55780.0


def test_return_rate():
    assert return_rate(25, 53) == round(25 / 53, 4)
    assert return_rate(0, 0) is None
    assert return_rate(10, None) is None
