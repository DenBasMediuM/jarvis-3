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
from modules.vyrobotka.verify import (
    apply_display_verdicts,
    compare_ticket_with_crm,
    display_verdict,
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
