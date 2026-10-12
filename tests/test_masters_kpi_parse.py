from datetime import date

from modules.masters_kpi.parse import (  # noqa: I001
    aggregate_weeks,
    apply_ready_fallback,
    compute_kpi,
    date_from_report_name,
    detect_layout,
    parse_ready_date,
    parse_report_rows,
)


def test_parse_standard_galanchuk_like():
    values = [
        [5, "Что делалось", "Сумма", "Время", "Дата"],
        ["Кв-я", "Диагностика / Ремонт", "Стоимость работ", "Время", "Дата готовности"],
        [20444, "Ремонт", 0, 1, 140520, "ПРИМЕР"],
        [114442, "то", 3280, 3, 45873],
        [114395, "биос", 800, 2, 45873],
        [114395, "рцп", 800, 1, 45874],
        ["", "", "2700 грн", "891 грн (33%)"],
    ]
    rows = parse_report_rows(values, source_name="28 отчет Галанчук от 01.10.26")
    assert len(rows) == 3
    assert rows[0]["ticket"] == "114442"
    assert rows[0]["work_sum"] == 3280
    assert rows[0]["hours"] == 3
    assert rows[0]["ready_day"] is not None
    tickets = {r["ticket"] for r in rows}
    assert "20444" not in tickets  # пример отсечён (или work 0+пример)
    weeks = aggregate_weeks(rows)
    assert weeks
    assert weeks[0]["tickets"] == 2  # 114442 + 114395
    assert weeks[0]["work_sum"] == 4880


def test_parse_znaydenov_layout():
    values = [
        ["", "модель", "номер квитанции", "неисправность", "стоимость", "диаг", "ремонт", "Дата готовности"],
        ["дата приема", "Модель устройства", "Акт", "Заявленная неисправность", "Стоимость работ", "Диагностика", "Ремонт"],
        [],
        ["", "TV", 40920, "синева", 1000, "матрица", "", 44029],
        ["", "Mini", 41215, "звук", 350, "ПО", "", 44032],
    ]
    rows = parse_report_rows(values, source_name="Отчет Знайденов")
    assert len(rows) == 2
    assert rows[0]["ticket"] == "40920"
    assert rows[0]["work_sum"] == 1000
    assert rows[0]["hours"] is None


def test_parse_headerless_dubovoy():
    values = [
        [123977, "диагностика", 1000, None, date(2026, 9, 21)],
        [123985, "гибрид", 1000, None, date(2026, 9, 20)],
        [123595, "пилосос", 2200, None, "почти готов"],
    ]
    rows = parse_report_rows(
        values,
        source_name="78 Отчет Дубовой от 16.09.26.xlsx",
        fallback_ready=date(2026, 9, 16),
    )
    assert len(rows) == 3
    assert rows[2]["ready_day"] == "2026-09-16"  # fallback
    assert rows[0]["ready_day"] == "2026-09-21"


def test_parse_ready_variants():
    assert parse_ready_date(45873) is not None
    assert parse_ready_date("12.08", fallback_year=2025) == date(2025, 8, 12)
    assert parse_ready_date("22 , 09 , 2026") == date(2026, 9, 22)
    assert date_from_report_name("53 отчет Плачковский от01.10.26-08.10.26") == date(
        2026, 10, 8
    )


def test_detect_tarasenko_extra_device_col():
    header = [
        "Кв-я",
        "Устройство",
        "Диагностика / Ремонт",
        "Стоимость работ",
        "Время",
        "Дата готовности",
    ]
    cols = detect_layout(header)
    assert cols is not None
    assert cols["ticket"] == 0
    assert cols["work"] == 3
    assert cols["hours"] == 4
    assert cols["ready"] == 5


def test_compute_kpi_uses_work_and_avg():
    assert compute_kpi(100_000, 50, 2000) == 200_000.0  # 100k * 2
    assert compute_kpi(0, 10) is None


def test_fallback_skipped_for_cumulative_sheet():
    rows = [
        {"ticket": str(1000 + i), "work_sum": 500.0, "ready_day": None}
        for i in range(100)
    ]
    out = apply_ready_fallback(rows, date(2025, 9, 9))
    assert all(r["ready_day"] is None for r in out)


def test_fallback_ok_for_short_week_report():
    rows = [
        {"ticket": "1001", "work_sum": 500.0, "ready_day": None},
        {"ticket": "1002", "work_sum": 600.0, "ready_day": "2025-09-08"},
    ]
    out = apply_ready_fallback(rows, date(2025, 9, 9))
    assert out[0]["ready_day"] == "2025-09-09"
    assert out[1]["ready_day"] == "2025-09-08"
