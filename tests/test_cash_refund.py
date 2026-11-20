from modules.cash_journal.parser import is_parts_attach_line, is_refund_line
from modules.gincore.client import GincoreClient

REPAY_HTML = """<div class="row"> <div class="col-sm-12"> <div class="col-sm-4">Стоимость ремонта </div>
<div class="col-sm-6">750 грн.</div> </div> <div class="col-sm-12"> <div class="col-sm-4">Оплачено</div>
<div class="col-sm-6">750 грн.</div> </div> <div class="col-sm-12"> <div class="col-sm-12">
<label class="payment_method " > Наличные</label> </div> </div> </div> <hr/>
<form id="repay-order" class="create_transaction_form"> <input type="hidden" value="125267" name="order_id">
<select class="form-control payment_cahboxes" name="cashboxes" >
<option data-cashboxes_type="2" value="13" > Сегедская</option>
<option data-cashboxes_type="2" value="78" > Каретный new</option> </select>
<input type="text" class="form-control js-input-format" value="750" name="amount">
<div class="text-center text-danger"> </div>
<select name="transaction_id"><option value="0">Выберите транзакцию</option><option value="1199">#1199 : 2500 UAH</option></select>
</form>"""


def test_parse_refund_form():
    f = GincoreClient.parse_refund_form(REPAY_HTML, "125267")
    assert f["has_form"] is True
    assert f["repair_cost"] == 750 and f["paid"] == 750
    assert f["payment_method"] == "Наличные"
    assert [c["id"] for c in f["cashboxes"]] == ["13", "78"]
    assert f["cashboxes"][1]["name"] == "Каретный new"
    assert f["max_amount"] == 750
    assert f["warning"] is None


def _line(raw, **kw):
    return {"action": "cash_out", "order_id": "125267", "raw": raw, "amount": -750, **kw}


def test_refund_line_detected_and_not_parts():
    ln = _line("125267 -750 возврат")
    assert is_refund_line(ln)
    assert not is_parts_attach_line(ln)
    assert is_refund_line(_line("125267 -750 вернули деньги", action="card_out"))


def test_refund_manual_overrides():
    assert not is_refund_line(_line("125267 -750 возврат", refund_manual=False))
    assert is_parts_attach_line(_line("125267 -750 возврат", refund_manual=False))
    assert is_refund_line(_line("125267 -750", refund_manual=True))
    assert not is_refund_line(_line("125267 -750 возврат", parts_manual=True))


def test_plain_parts_untouched():
    assert not is_refund_line(_line("123956 -256 елемент пельтье", order_id="123956"))
    assert is_parts_attach_line(_line("123956 -256 елемент пельтье", order_id="123956"))
    assert not is_refund_line({"action": "cash_out", "order_id": None, "raw": "-200 возврат такси"})
