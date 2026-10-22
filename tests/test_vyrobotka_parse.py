from modules.vyrobotka.parse import (
    aggregate_sheet_debt,
    aggregate_sheet_upsell,
    collect_underpaid_tickets,
    is_week_sheet,
    parse_week_rows,
    select_week_sheets,
    sheet_sort_key,
    underpayment_amount,
)
from modules.vyrobotka.sheets import GoogleSheetsClient
from modules.vyrobotka.verify import (
    apply_display_verdicts,
    classify_debt_row,
    compare_ticket_with_crm,
    crm_totals_from_payment,
    display_verdict,
    is_atypical_debt_case,
    unpack_issues_payload,
)


def test_week_sheet_detection():
    assert is_week_sheet("202609(16-23)")
    assert is_week_sheet("!20250804(28-03)")
    assert is_week_sheet("202512(09-15)")
    assert is_week_sheet("202607(01-08) ")
    assert not is_week_sheet("dosoglasi")
    assert not is_week_sheet("Сводка")
    assert not is_week_sheet("Затраты")
    assert not is_week_sheet("Прибль с мастеров из отчетов")


def test_sheet_sort_order():
    sheets = [
        {"title": "202609(24-30)", "index": 2},
        {"title": "202609(01-08)", "index": 1},
        {"title": "!20250809(04-10)", "index": 1},
        {"title": "!20250804(28-03)", "index": 0},
    ]
    ordered = select_week_sheets(sheets)
    assert [s["title"] for s in ordered] == [
        "!20250804(28-03)",
        "!20250809(04-10)",
        "202609(01-08)",
        "202609(24-30)",
    ]
    assert sheet_sort_key("202609(16-23)") < sheet_sort_key("202609(24-30)")
    assert sheet_sort_key("!20250804(28-03)") < sheet_sort_key("!20250809(04-10)")


def test_parse_fill_down_and_upsell_agg():
    values = [
        ["Мастер", "кв", "В отчете", "ЗП", "Запчасти", "Общая", "Оплачено", "Досоглас"],
        ["Галанчук", 100, 5000, 2500, 0, 6000, 6000, 1000],
        ["", 101, 3000, 1500, 0, 3000, 3000, ""],
        ["Сатаулов", 102, 2000, 1000, 0, 2500, 2500, 500],
        ["", "", "", "", "", "", "", ""],  # skip
    ]
    rows = parse_week_rows("202609(24-30)", values)
    assert len(rows) == 3
    assert rows[0]["master"] == "Галанчук"
    assert rows[1]["master"] == "Галанчук"
    assert rows[2]["master"] == "Сатаулов"
    assert rows[0]["upsell"] == 1000
    assert rows[1]["upsell"] is None

    stats = aggregate_sheet_upsell("202609(24-30)", rows)
    assert stats["tickets_count"] == 3
    assert stats["upsell_count"] == 2
    assert stats["upsell_sum"] == 1500
    assert stats["avg_upsell"] == 750
    assert abs(stats["upsell_ratio"] - 2 / 3) < 1e-9
    assert stats["report_sum"] == 10000


def test_underpayment_and_debt_agg():
    assert underpayment_amount(6000, 5000) == 1000
    assert underpayment_amount(6000, 6000) is None
    assert underpayment_amount(6000, None) == 6000
    assert underpayment_amount(None, 100) is None

    values = [
        ["Мастер", "кв", "В отчете", "ЗП", "Запчасти", "Общая", "Оплачено", "Досоглас"],
        ["Галанчук", 100, 5000, 2500, 0, 6000, 5000, 1000],  # долг 1000
        ["", 101, 3000, 1500, 0, 3000, 3000, ""],  # ок
        ["Сатаулов", 102, 2000, 1000, 0, 4000, 1000, 500],  # долг 3000
    ]
    rows = parse_week_rows("202609(24-30)", values)
    debt = aggregate_sheet_debt("202609(24-30)", rows)
    assert debt["debt_count"] == 2
    assert debt["debt_sum"] == 4000
    assert debt["avg_debt"] == 2000

    tickets = collect_underpaid_tickets(rows)
    assert len(tickets) == 2
    assert tickets[0]["ticket"] == "102"
    assert tickets[0]["debt"] == 3000
    assert tickets[1]["ticket"] == "100"
    assert tickets[1]["debt"] == 1000


def test_compare_ticket_field_diffs():
    sheet = {
        "sheet_title": "202609(24-30)",
        "ticket": "100",
        "total_repair": 6000,
        "paid": 1000,
        "debt": 5000,
        "status": "Выдан",
    }
    r = compare_ticket_with_crm(
        sheet,
        crm_total=5500,
        crm_paid=5500,
        crm_debt=None,
        crm_status="Готов",
    )
    assert r["verdict"] == "mismatch"
    assert "total" in r["field_diffs"]
    assert "paid" in r["field_diffs"]
    assert "debt" in r["field_diffs"]
    assert "status" in r["field_diffs"]
    assert r["field_diffs"]["total"]["crm"] == 5500
    msgs, fields = unpack_issues_payload(
        {"messages": r["issues"], "fields": r["field_diffs"]}
    )
    assert msgs
    assert fields["paid"]["crm"] == 5500


def test_display_verdict_norm_for_issued_paid():
    row = {
        "verdict": "mismatch",
        "crm_status": "Выдан",
        "crm_debt": 0,
        "crm_paid": 6000,
        "sheet_debt": 6000,
        "summary": "оплачено: таблица 0 ≠ CRM 6000",
    }
    assert display_verdict(row) == "norm"
    shown = apply_display_verdicts([row])[0]
    assert shown["verdict"] == "norm"
    assert shown["stored_verdict"] == "mismatch"

    settled = compare_ticket_with_crm(
        {
            "sheet_title": "202609(24-30)",
            "ticket": "101",
            "total_repair": 6000,
            "paid": 0,
            "debt": 6000,
            "status": "Передан курьеру",
        },
        crm_total=6000,
        crm_paid=6000,
        crm_debt=None,
        crm_status="Выдан",
    )
    assert settled["verdict"] == "norm"


def test_atypical_debt_case_rules():
    # Отказ в CRM + долг в CRM ещё есть + работы в отчёте
    assert is_atypical_debt_case(
        sheet_total=5000,
        crm_total=0,
        sheet_debt=5000,
        report_amount=3000,
        crm_status="Выдан без ремонта",
        crm_debt=5000,
        crm_paid=0,
    )
    assert is_atypical_debt_case(
        sheet_total=4000,
        crm_total=1000,
        sheet_debt=4000,
        report_amount=2000,
        crm_status="У курьера БЕЗ РЕМОНТ",
        crm_debt=4000,
    )
    # 116077: в CRM долг остался
    assert is_atypical_debt_case(
        sheet_total=1700,
        crm_total=1700,
        sheet_debt=1700,
        report_amount=350,
        crm_status="Выдан без ремонта",
        crm_debt=1700,
        crm_paid=0,
    )
    # 121399: в CRM уже оплачено — не нетипичный (устаревшая таблица)
    assert not is_atypical_debt_case(
        sheet_total=750,
        crm_total=750,
        sheet_debt=750,
        report_amount=750,
        crm_status="Выдан без ремонта",
        crm_debt=None,
        crm_paid=750,
    )
    # 123849: обычный «у курьера готов» — не нетипичный
    assert not is_atypical_debt_case(
        sheet_total=6600,
        crm_total=6600,
        sheet_debt=6600,
        report_amount=5500,
        crm_status="У курьера ГОТОВ",
        crm_debt=6600,
    )
    # нет работ мастера
    assert not is_atypical_debt_case(
        sheet_total=5000,
        crm_total=0,
        sheet_debt=5000,
        report_amount=0,
        crm_status="Не подлежит ремонту",
        crm_debt=5000,
    )


def test_sheet_tab_url_includes_gid():
    url = GoogleSheetsClient.sheet_tab_url("abc", 42, row_index=22)
    assert "gid=42" in url
    assert url.count("gid=42") >= 2
    assert "range=A22" in url
    assert GoogleSheetsClient.sheet_tab_url("abc", None) == (
        "https://docs.google.com/spreadsheets/d/abc/edit"
    )


def test_classify_yellow_match():
    r = classify_debt_row(
        {
            "sheet_debt": 1000,
            "crm_debt": 1000,
            "crm_total": 3000,
            "crm_paid": 2000,
            "crm_status": "Готов",
            "on_pay_list": 1,
            "crm_checked_at": "x",
        }
    )
    assert r["active"] == 1 and r["flag"] == "yellow"


def test_classify_remove_when_crm_settled():
    r = classify_debt_row(
        {
            "sheet_debt": 1000,
            "crm_debt": 0,
            "crm_status": "Выдан",
            "on_pay_list": 0,
            "crm_checked_at": "x",
        }
    )
    assert r["active"] == 0


def test_classify_red_write_off():
    r = classify_debt_row(
        {
            "first_crm_debt": 1000,
            "first_crm_total": 1000,
            "first_crm_status": "Готов",
            "crm_debt": 1000,
            "crm_paid": 0,
            "crm_total": 1000,
            "crm_status": "Не подлежит ремонту",
            "on_pay_list": 0,
            "crm_checked_at": "x",
        }
    )
    assert r["flag"] == "red"


def test_classify_red_zero_total():
    r = classify_debt_row(
        {
            "first_crm_total": 1000,
            "first_crm_debt": 1000,
            "first_crm_status": "Готов",
            "crm_total": 0,
            "crm_paid": 0,
            "crm_debt": 0,
            "crm_status": "Готов",
            "on_pay_list": 0,
            "crm_checked_at": "x",
        }
    )
    assert r["active"] == 1 and r["flag"] == "red"
    assert "обнулена" in (r["flag_reason"] or "").casefold()


def test_classify_red_demote_from_ready():
    r = classify_debt_row(
        {
            "first_crm_status": "Готов",
            "first_crm_debt": 1000,
            "sheet_debt": 1000,
            "crm_status": "В процессе ремонта",
            "crm_debt": 1000,
            "crm_paid": 0,
            "crm_total": 1000,
            "on_pay_list": 0,
            "crm_checked_at": "x",
        }
    )
    assert r["flag"] == "red"


def test_classify_red_left_pay_list():
    r = classify_debt_row(
        {
            "first_on_pay_list": 1,
            "first_crm_debt": 800,
            "crm_debt": 800,
            "crm_status": "Диагностика",
            "crm_total": 800,
            "crm_paid": 0,
            "on_pay_list": 0,
            "crm_checked_at": "x",
        }
    )
    assert r["flag"] == "red"


def test_classify_open_crm_only():
    r = classify_debt_row(
        {
            "sheet_debt": 0,
            "crm_debt": 500,
            "crm_status": "Готов",
            "crm_total": 500,
            "crm_paid": 0,
            "on_pay_list": 1,
            "crm_checked_at": "x",
        }
    )
    assert r["flag"] == "open"


def test_classify_mismatch_amounts():
    r = classify_debt_row(
        {
            "sheet_debt": 1000,
            "crm_debt": 400,
            "crm_status": "Готов",
            "crm_total": 1000,
            "crm_paid": 600,
            "on_pay_list": 1,
            "crm_checked_at": "x",
        }
    )
    assert r["flag"] == "mismatch"


def test_crm_totals_full_pay_debt_is_zero_not_none():
    total, paid, debt = crm_totals_from_payment(
        {"total_with_discount": 11500, "paid": 11500}
    )
    assert total == 11500 and paid == 11500 and debt == 0.0


def test_classify_121059_style_paid_in_full_null_debt():
    """paid=total, crm_debt=None (баг underpayment) → убрать, не «CRM не проверен»."""
    r = classify_debt_row(
        {
            "sheet_debt": 11500,
            "crm_total": 11500,
            "crm_paid": 11500,
            "crm_debt": None,
            "crm_status": "Выдан",
            "on_pay_list": 0,
            "crm_checked_at": "x",
        }
    )
    assert r["active"] == 0
    assert "закрыт" in (r["flag_reason"] or "").casefold()
