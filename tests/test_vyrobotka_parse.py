from modules.vyrobotka.parse import (
    aggregate_sheet_upsell,
    is_week_sheet,
    parse_week_rows,
    select_week_sheets,
    sheet_sort_key,
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
