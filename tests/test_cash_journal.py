"""Cash journal reconcile — fixture from 06.08.2026 Segedskaya chat."""

from __future__ import annotations

from modules.cash_journal.parser import parse_journal, reconcile_cash_journal

SAMPLE_06_08 = """
[06.08.2026 07:51] Денис Исаев: Касса: 6012
Карта: 3896
[06.08.2026 09:15] Vikki: -4000 грн Зч ssd 122870
[06.08.2026 09:15] Vikki: 122955 +750 грн
[06.08.2026 10:27] Vikki: -1000 грн Вика ЗП
[06.08.2026 11:13] Vikki: 122414 +1750 грн
[06.08.2026 11:37] Vikki: 122315 +750 грн на карту
[06.08.2026 11:41] Vikki: 122558 +4031 грн.  на счет ФОПа  (23,07)
[06.08.2026 12:08] Vikki: 122960 +1200 грн
[06.08.2026 14:25] Vikki: 122507  +2100 грн на карту
[06.08.2026 15:01] Vikki: 122713 +1100 грн
[06.08.2026 15:54] Vikki: -5000 грн Вадим ЗП
[06.08.2026 16:39] Vikki: 122935 +7000 грн пред.
[06.08.2026 17:30] Vikki: 122844 +1200 грн на карту
[06.08.2026 17:46] Vikki: 122797 +750 грн
[06.08.2026 18:04] Vikki: -7000 грн Влад ЗЧ
[06.08.2026 18:04] Vikki: 121464 - Барабан - 1100
121190 - ролики - 300
121391 - абсорбер - 400
121668 - тонер - 600
121563- уплотнители - 200
119274 - плата - 2500
121692 - провод - 600
121700 - уплотнители - 200
121773 - шестерня - 300
121721 - клапан - 800
[06.08.2026 18:28] Vikki: 122955 +4500 грн
[06.08.2026 18:55] Vikki: -4000 грн Влад ЗП
"""


def test_parse_openings():
    r = parse_journal(SAMPLE_06_08)
    assert r.opening_cash == 6012
    assert r.opening_card == 3896


def test_zch_breakdown_not_double_counted():
    r = parse_journal(SAMPLE_06_08)
    # Итог «−7000 Влад ЗЧ» — в skipped; позиции — в operations
    totals = [o for o in r.skipped_breakdown if o.kind == "breakdown_total"]
    assert len(totals) == 1
    assert abs(totals[0].amount + 7000) < 0.01
    items = [o for o in r.operations if o.breakdown_of]
    assert len(items) == 10
    assert abs(sum(abs(x.amount) for x in items) - 7000) < 0.01
    # Only one -7000 ZCH summary (ignored), not 10 extra on top of it
    zch_ops = [
        o
        for o in r.operations
        if ("ЗЧ" in o.note.upper() or "зч" in o.note.lower()) and not o.breakdown_of
    ]
    assert len(zch_ops) == 1  # ssd Зч без расшифровки
    assert abs(sum(o.amount for o in items) + 7000) < 0.01
    assert totals[0].amount == -7000


def test_buckets_card_and_fop():
    r = parse_journal(SAMPLE_06_08)
    card = [o for o in r.operations if o.bucket == "card"]
    fop = [o for o in r.operations if o.bucket == "fop"]
    assert sum(o.amount for o in card) == 750 + 2100 + 1200
    assert sum(o.amount for o in fop) == 4031


def test_closing_balances_06_08():
    r = parse_journal(SAMPLE_06_08)
    assert r.closing_cash == 2062
    assert r.closing_card == 7946
    assert r.closing_fop == 4031


def test_reconcile_tables():
    out = reconcile_cash_journal(SAMPLE_06_08)
    assert out["ok"] is True
    assert out["closing_cash"] == 2062
    assert out["closing_card"] == 7946
    assert out["closing_fop"] == 4031
    assert out["cash_journal"]["title"] == "Сведение кассы"
    assert out["tables"] == []
    assert len(out["cash_journal"]["lines"]) >= 10
    assert any(l["action"] == "card_in" for l in out["cash_journal"]["lines"])


def test_breakdown_line_with_missing_space():
    """121563- уплотнители - 200 (no space before first dash)."""
    from modules.cash_journal.parser import _is_breakdown_line

    assert _is_breakdown_line("121563- уплотнители - 200") is not None


def test_signed_without_currency():
    text = """
Касса: 10000
Карта: 0
-200 смс
-1500 зп Аля
-615 оплатила росходку на карету
+500 вернули
"""
    r = parse_journal(text)
    assert r.unrecognized == []
    assert r.closing_cash == 10000 - 200 - 1500 - 615 + 500
    assert any(o.amount == -200 and "смс" in o.note for o in r.operations)


def test_unrecognized_lines_stay_for_manual_fix():
    text = """
Касса: 1000
Карта: 0
списала смс двести
логистика Андрусяк левитан сто пятьдесят
"""
    out = reconcile_cash_journal(text)
    assert out["needs_ai_review"] is False
    assert len(out["unrecognized"]) == 2
    assert out["closing_cash"] == 1000
    unrec_lines = [l for l in out["cash_journal"]["lines"] if l["source"] == "unrecognized"]
    assert len(unrec_lines) == 2
    assert all(l["action"] == "ignore" for l in unrec_lines)


def test_partial_cash_rent_no_ai():
    text = """
Касса: 2020
Карта: 3422
-5500 аренда (500 взял с кассы)
-90 з/ч
В кассе 1520 грн.
"""
    out = reconcile_cash_journal(text)
    assert out["closing_cash"] == 2020 - 500 - 90
    assert out["closing_card"] == 3422
    assert out["needs_ai_review"] is False
    assert all(o["kind"] != "ai_proposed" for o in out["operations"])


def test_rent_partial_cash_and_narrative_lines():
    text = """
Касса: 2020
Карта: 3422
-90 з/ч
-5500 аренда (500 взял с кассы)
спустил сверху 5000 на аренду (сегодня Юра рассчитается)
остальное забрал
"""
    out = reconcile_cash_journal(text)
    assert out["closing_cash"] == 1430
    assert out["closing_card"] == 3422
    assert out["cash_journal"]["closing_cash"] == 1430
    rent = next(l for l in out["cash_journal"]["lines"] if "аренда" in l["raw"])
    assert rent["amount"] == 500
    assert rent["action"] == "cash_out"
    narrative = [
        l for l in out["cash_journal"]["lines"] if l["source"] == "unrecognized"
    ]
    assert all(l["action"] == "ignore" for l in narrative)
    assert [a["id"] for a in out["cash_journal"]["actions"]] == [
        "cash_in",
        "cash_out",
        "card_in",
        "card_out",
        "cash_to_card",
        "card_to_cash",
        "ignore",
    ]


def test_parse_money_thousands_suffix():
    from modules.cash_journal.parser import parse_money, _loose_amount_from_text

    assert parse_money("5к") == 5000
    assert parse_money("5к") == parse_money("5k")
    assert parse_money("-5к") == -5000
    assert parse_money("1.5к") == 1500
    assert parse_money("500") == 500
    # не путать с «касса»
    assert parse_money("5") == 5
    assert _loose_amount_from_text("спустил сверху 5к на аренду") == 5000
    assert _loose_amount_from_text("-5к ЗП") == -5000
    out = reconcile_cash_journal(
        "Касса: 10к\nКарта: 0\n-5к аренда\n+2к пред"
    )
    assert out["opening"]["cash"] == 10000 or out["cash_journal"]["opening_cash"] == 10000
    assert out["closing_cash"] == 10000 - 5000 + 2000


def test_compound_order_line_and_negative_card_opening():
    """122712 - 775 АКБ , доставка -50 — обе суммы; Карта: -154 сохраняет знак."""
    text = """
[10.08.2026 08:57] Денис Исаев: Касса: 3656
Карта: -154
[10.08.2026 11:09] Прием екат: 122782 + 3400
[10.08.2026 12:35] Прием екат: - 2170 бензин, такси
[10.08.2026 12:39] Прием екат: -2000 ЗП Вовчук
[10.08.2026 14:19] Прием екат: 122342 + 3500
[10.08.2026 14:20] Прием екат: -3500 ЗП Сатаулов
[10.08.2026 15:16] Прием екат: 122649 + 1950
[10.08.2026 15:41] Прием екат: 122804 + 750
[10.08.2026 16:44] Прием екат: 122712 - 775 АКБ , доставка -50
[10.08.2026 16:46] Прием екат: 122489 - 755 АКБ
[10.08.2026 16:49] Прием екат: -2000 ЗП Садоян
[10.08.2026 17:38] Прием екат: -2000 ЗП Руднев
[10.08.2026 18:43] Прием екат: 123027 + 400
[10.08.2026 18:44] Прием екат: касса: 406
"""
    out = reconcile_cash_journal(text)
    assert out["cash_journal"]["opening_cash"] == 3656
    assert out["cash_journal"]["opening_card"] == -154
    amts = [l["amount"] for l in out["cash_journal"]["lines"] if l["source"] == "parser"]
    assert 775 in amts and 50 in amts
    assert out["closing_cash"] == 406
    assert out["closing_card"] == -154
    assert any(l["raw"].lower().startswith("касса:") for l in out["cash_journal"]["lines"])


def test_line_order_preserved_with_chat_labels():
    """Порядок как в тексте: не группировать заказы отдельно от расходов."""
    text = """
Касса: 3656
Карта: -154
Прием екат: 122782 + 3400
Прием екат: - 2170 бензин, такси
Прием екат: -2000 ЗП Вовчук
Прием екат: 122342 + 3500
Прием екат: -3500 ЗП Сатаулов
Прием екат: 122649 + 1950
Прием екат: 122804 + 750
Прием екат: 122712 - 775 АКБ , доставка -50
Прием екат: 122489 - 755 АКБ
Прием екат: -2000 ЗП Садоян
Прием екат: -2000 ЗП Руднев
Прием екат: 123027 + 400
Прием екат: касса: 406
"""
    out = reconcile_cash_journal(text)
    lines = [l for l in out["cash_journal"]["lines"] if l["action"] != "ignore"]
    expected = [3400, 2170, 2000, 3500, 3500, 1950, 750, 775, 50, 755, 2000, 2000, 400]
    assert [l["amount"] for l in lines] == expected
    assert out["closing_cash"] == 406


def test_paren_breakdown_expense_line():
    """-2388 грн (94…, 122857 2154…, 90…, + 50…) → 4 операции, без итога 2388."""
    text = """
Касса: 10000
Карта: 0
[12.08.2026 17:26] Vikki: -2388 грн (94 грн доставка пластик на сервис, 122857 2154 грн детали, 90грн доставка шим-контроллеры расходка + 50 грн курьер)
"""
    out = reconcile_cash_journal(text)
    lines = [l for l in out["cash_journal"]["lines"] if l["source"] == "parser"]
    amts = [l["amount"] for l in lines]
    assert amts == [94, 2154, 90, 50]
    assert all(l["action"] == "cash_out" for l in lines)
    details = next(l for l in lines if l["amount"] == 2154)
    assert details["order_id"] == "122857"
    assert "детали" in details["raw"]
    assert out["closing_cash"] == 10000 - 2388
    # аренда с долей из кассы не должна разбиваться по скобкам
    rent = reconcile_cash_journal("Касса: 6000\n-5500 аренда (500 взял с кассы)")
    rent_lines = [l for l in rent["cash_journal"]["lines"] if l["source"] == "parser"]
    assert len(rent_lines) == 1
    assert rent_lines[0]["amount"] == 500


def test_collapsed_telegram_messages_still_split():
    """Если переносы строк потерялись — режем по [дата] и не дублируем весь блок."""
    collapsed = (
        "Касса: 10000 Карта: 0 "
        "[12.08.2026 11:50] Vikki: 122860 +1700 грн "
        "[12.08.2026 11:56] Vikki: -1000 грн Вика ЗП "
        "[12.08.2026 17:26] Vikki: -2388 грн (94 грн доставка пластик на сервис, "
        "122857 2154 грн детали, 90грн доставка шим-контроллеры расходка + 50 грн курьер) "
        "[12.08.2026 17:45] Vikki: 122452 +1500 грн"
    )
    out = reconcile_cash_journal(collapsed)
    lines = [l for l in out["cash_journal"]["lines"] if l["source"] == "parser"]
    amts = [l["amount"] for l in lines]
    assert amts == [1700, 1000, 94, 2154, 90, 50, 1500]
    for l in lines:
        assert "[12.08.2026" not in (l["raw"] or "")
        assert "Vikki:" not in (l["raw"] or "")


def test_paren_breakdown_amount_at_end():
    """-1409 грн (… доставка 90 грн, сенсор 417 грн, … +50 курьер) — суммы в конце фраз."""
    body = (
        "-1409 грн (123090 подсветка, доставка 90 грн, 122782 мастило, сенсор 417 грн, "
        "122990 акум 463 грн, арм. лента усиленная 5шт, армированная лента Mercury 5 шт. "
        "маляр. скотч 2шт расходка 389 грн +50 грн курьер)"
    )
    out = reconcile_cash_journal(f"Касса: 5000\nКарта: 0\n{body}")
    lines = [l for l in out["cash_journal"]["lines"] if l["source"] == "parser"]
    amts = [l["amount"] for l in lines]
    assert amts == [90, 417, 463, 389, 50]
    assert all(l["action"] == "cash_out" for l in lines)
    assert any(l["order_id"] == "123090" and l["amount"] == 90 for l in lines)
    assert any(l["order_id"] == "122782" and l["amount"] == 417 for l in lines)
    assert any(l["order_id"] == "122990" and l["amount"] == 463 for l in lines)
    assert sum(l["amount"] for l in lines) == 1409
    assert out["closing_cash"] == 5000 - 1409


SAMPLE_27_08 = """
[27.08.2026 07:05] Денис Исаев: Касса: 6769 Карта: 4496
[27.08.2026 09:14] Інна Балта: Касса: 6769
[27.08.2026 09:14] Інна Балта: -120 бітотримач
[27.08.2026 09:22] Аля: 122352 +1000 на карту 14.07
[27.08.2026 09:27] Аля: -700 зп Инна
[27.08.2026 09:27] Аля: -2000 зп Галанчук
"""


def test_opening_not_overridden_by_llm_zeros():
    """Модель часто передаёт opening_cash/card: 0 — не затирать «Касса:/Карта:» из текста."""
    out = reconcile_cash_journal(SAMPLE_27_08, opening_cash=0, opening_card=0)
    cj = out["cash_journal"]
    assert cj["opening_cash"] == 6769
    assert cj["opening_card"] == 4496
    assert cj["lines"][0]["raw"] == "Касса: 6769"
    assert cj["lines"][0]["action"] == "ignore"


def test_cash_and_card_split_on_same_line():
    """«122865 +1000 грн нал. и 200 грн на карту» → касса +1000, карта +200."""
    body = "122865 +1000 грн нал. и 200 грн на карту"
    out = reconcile_cash_journal(f"Касса: 0\nКарта: 0\n{body}")
    lines = [l for l in out["cash_journal"]["lines"] if l["source"] == "parser"]
    assert len(lines) == 2
    assert lines[0]["amount"] == 1000
    assert lines[0]["action"] == "cash_in"
    assert lines[0]["order_id"] == "122865"
    assert lines[1]["amount"] == 200
    assert lines[1]["action"] == "card_in"
    assert lines[1]["order_id"] == "122865"
    assert out["closing_cash"] == 1000
    assert out["closing_card"] == 200


def test_cash_and_card_split_ukrainian_i():
    """«123516 +1500 нал і 400 на карту» — укр. «і» как союз."""
    body = "123516 +1500 нал і 400 на карту"
    out = reconcile_cash_journal(f"Касса: 0\nКарта: 0\n{body}")
    lines = [l for l in out["cash_journal"]["lines"] if l["source"] == "parser"]
    assert [(l["amount"], l["action"]) for l in lines] == [
        (1500, "cash_in"),
        (400, "card_in"),
    ]
    assert out["closing_cash"] == 1500
    assert out["closing_card"] == 400


def test_telegram_quotes_not_counted_as_ops():
    """Цитаты «> …» в ответах — ignore + is_quote, без дубля операции."""
    text = """
Касса: 1049
Карта: 5496
123430 -2060 зч
[28.08.2026 18:43] Аля в ответ Інна Балта:
> ‎⁨123430 -2060 зч⁩
квитанція?
123441 +3000 пред
"""
    out = reconcile_cash_journal(text)
    cj = out["cash_journal"]
    parser_lines = [l for l in cj["lines"] if l["source"] == "parser"]
    zch_ops = [l for l in parser_lines if l.get("order_id") == "123430"]
    assert len(zch_ops) == 1
    assert zch_ops[0]["amount"] == 2060
    assert zch_ops[0]["action"] == "cash_out"
    assert out["closing_cash"] == 1049 - 2060 + 3000

    quote_lines = [l for l in cj["lines"] if l.get("is_quote")]
    assert len(quote_lines) == 1
    assert quote_lines[0]["action"] == "ignore"
    assert "123430" in (quote_lines[0]["raw"] or "")


def test_balance_checkpoints_show_calc_vs_written():
    text = """
Касса: 1000
Карта: 500
-300 расход
123302 +5000 пред
Касса: 5700
123520 +750 на карту
Карта: 1250
"""
    out = reconcile_cash_journal(text)
    cj = out["cash_journal"]
    checkpoints = [l for l in cj["lines"] if l.get("is_checkpoint")]
    assert len(checkpoints) == 2

    cp_cash = next(l for l in checkpoints if l.get("written_cash") == 5700)
    assert cp_cash["calc_cash"] == 5700
    assert cp_cash["cash_match"] is True

    cp_card = next(l for l in checkpoints if l.get("written_card") == 1250)
    assert cp_card["calc_card"] == 1250
    assert cp_card["card_match"] is True

    assert out["closing_cash"] == 5700
    assert out["closing_card"] == 1250


def test_kassa_with_trailing_grn_not_truncated():
    text = """
Касса: 1049
[29.08.2026 19:10] Vikki: КАССА: 18392  грн
"""
    out = reconcile_cash_journal(text)
    cj = out["cash_journal"]
    assert not any((l.get("raw") or "").strip() == "грн" for l in cj["lines"])
    cp = next(l for l in cj["lines"] if l.get("written_cash") == 18392)
    assert cp["is_checkpoint"] is True
    assert "КАССА" in (cp["raw"] or "").upper()


def test_kasa_ukrainian_spelling_checkpoint():
    """«Каса: 4790» (укр., одна «с») — не обрезать до «4790»."""
    text = """
[31.08.2026 08:24] Денис: Касса: 4790
Карта: 1717
[31.08.2026 09:13] Аля: Каса: 4790
-1500 зп Аля
"""
    out = reconcile_cash_journal(text)
    cj = out["cash_journal"]
    assert cj["opening_cash"] == 4790
    assert cj["opening_card"] == 1717
    assert not any((l.get("raw") or "").strip() == "4790" for l in cj["lines"])
    cp = next(l for l in cj["lines"] if l.get("is_checkpoint") and l.get("written_cash") == 4790)
    assert "Каса" in (cp["raw"] or "") or "каса" in (cp["raw"] or "").lower()
    assert cp["action"] == "ignore"
    assert out["closing_cash"] == 4790 - 1500


def test_kassa_fact_checkpoint():
    text = """
Касса: 1000
-500 расход
[01.09.2026 18:51] Kosher: касса факт 5854
-2500 грн Ефимов ЗП
"""
    out = reconcile_cash_journal(text)
    cj = out["cash_journal"]
    cp = next(l for l in cj["lines"] if l.get("is_checkpoint") and l.get("written_cash") == 5854)
    assert "факт" in (cp["raw"] or "").lower()
    assert cp["action"] == "ignore"
    assert out["closing_cash"] == 1000 - 500 - 2500


def test_zch_breakdown_all_lines_visible_no_double_count():
    """Большой список ЗЧ: позиции в расчёте, итог −9600 — ignore."""
    text = """
Касса: 20000
-9600 грн Влад ЗЧ
121763 - переходник - 300
122115 - Барабан, лезвие - 200
122258 - абсорбер - 350
121853 - БП - 1500
122020 - Пленка , барабан - 500
122313 - Транзисторы - 250
122102 - головы - 1000
122283 - барабан - 200
121954 - Конденсатор - 300
122150 - уплотнители - 500
121997 - помпа - 1000
121863 - термодатчики - 500
122197 - тумблер - 300
120247 - 2000 - тачскрин , барабан, впз
122223 - механизм - 500
122221 - барабан - 200
123701 +3200
"""
    out = reconcile_cash_journal(text)
    cj = out["cash_journal"]
    total_line = next(l for l in cj["lines"] if l.get("is_breakdown_total"))
    assert total_line["action"] == "ignore"
    assert total_line["amount"] == 9600
    zch_parts = [
        l
        for l in cj["lines"]
        if l["action"] == "cash_out"
        and l.get("order_id")
        and "ЗЧ" not in (l.get("raw") or "").upper()
    ]
    assert len(zch_parts) == 16
    assert sum(l["amount"] for l in zch_parts) == 9600
    assert any("тачскрин" in (l["raw"] or "") for l in zch_parts)
    assert out["closing_cash"] == 20000 - 9600 + 3200


def test_amount_not_glued_to_quantity():
    """«-1800 3 банки тонера» → 1800, не 18003."""
    from modules.cash_journal.parser import parse_money, _parse_operation_lines

    assert parse_money("1 800") == 1800
    assert parse_money("1800 3") == 1800
    ops = _parse_operation_lines("-1800 3 банки тонера")
    assert len(ops) == 1
    assert ops[0].amount == -1800
    assert ops[0].bucket == "cash"

    text = """
Касса: 7112
-1800 3 банки тонера
+2800 на карту
+2000 на карту
+400
+300
+1300
+1500
-1000
-2500
-1000
-3000
Касса: 1312
"""
    out = reconcile_cash_journal(text)
    assert out["closing_cash"] == 1312
    assert out["closing_card"] == 4800
    cp = next(l for l in out["cash_journal"]["lines"] if l.get("written_cash") == 1312)
    assert cp["cash_match"] is True


def test_parts_attach_journal_line():
    from modules.cash_journal.parser import is_parts_attach_line

    out = reconcile_cash_journal(
        "Касса: 1000\nКарта: 0\n123956 -256 елемент пельтье\n"
        "123959 -427 зч\n"
        "121985 - Шлейфы , датчики, 2000\n"
        "зч 122114 - помпа - 1500\n"
        "-4000 грн Зч ssd 122870\n123122 -505 на зп\n"
    )
    lines = out["cash_journal"]["lines"]
    parts = next(l for l in lines if "пельтье" in (l.get("raw") or ""))
    assert parts["action"] == "cash_out"
    assert parts["order_id"] == "123956"
    assert parts["amount"] == 256
    assert is_parts_attach_line(parts) is True
    zch = next(l for l in lines if (l.get("raw") or "").endswith("зч"))
    assert zch["order_id"] == "123959"
    assert zch["action"] == "cash_out"
    assert is_parts_attach_line(zch) is True
    comma = next(l for l in lines if "Шлейфы" in (l.get("raw") or ""))
    assert comma["amount"] == 2000
    assert comma["order_id"] == "121985"
    assert comma["action"] == "cash_out"
    assert is_parts_attach_line(comma) is True
    pump = next(l for l in lines if "помпа" in (l.get("raw") or ""))
    assert pump["amount"] == 1500
    assert pump["action"] == "cash_out"
    assert is_parts_attach_line(pump) is True
    assert out["cash_journal"]["closing_cash"] == 1000 - 256 - 427 - 2000 - 1500 - 4000 - 505
    bulk = next(l for l in lines if "Зч ssd" in (l.get("raw") or ""))
    assert bulk["action"] == "cash_out"
    assert is_parts_attach_line(bulk) is False
    zp = next(l for l in lines if "на зп" in (l.get("raw") or "").lower())
    assert zp["action"] == "cash_out"
    assert is_parts_attach_line(zp) is False


SAMPLE_05_10 = """
[05.10.2026 08:01] Денис Исаев: Касса: 925 (-75 получается по записям в ТГ)
Карта: 1121
[05.10.2026 08:59] Марго в ответ Денис Исаев:
> ‎⁨Касса: 925 (-75 получается по записям в ТГ) Карта: 1121⁩
налом 925
[05.10.2026 10:00] Марго: 123973 +2500
[05.10.2026 10:41] Марго: 124417 срочная 750
[05.10.2026 11:42] Марго: 124388 +400
[05.10.2026 11:50] Марго: 123600 +3900
[05.10.2026 12:40] Марго: 124424 предоплата 500
[05.10.2026 13:08] Марго: 124417 +1500
[05.10.2026 13:16] Марго: Касса: 10475
[05.10.2026 15:28] Марго: 124170 -270 на зч (прокладка)
[05.10.2026 15:29] Марго: 124348 -200 зч (пачкорд)
[05.10.2026 15:29] Марго: 124268 -300 зч (термодатчики)
[05.10.2026 15:31] Марго: -2575 ЗП Вовчук остаток за 16.09
[05.10.2026 15:31] Марго: -655 ЗП Вовчук за 24.09
[05.10.2026 15:40] Марго: -1000 ЗП Марго
[05.10.2026 15:42] Марго: Касса: 5475
[05.10.2026 16:09] Марго: -1000 ЗП Садоян (аванс)
[05.10.2026 16:40] Марго: 122866 -1400 зч (материнка)
[05.10.2026 17:28] Марго: 124405 +400
[05.10.2026 18:38] Марго: Касса: 3475
"""


def test_order_label_amount_and_nalom_opening():
    """«124417 срочная 750», «налом 925», цитата и сверки 10475/5475/3475."""
    out = reconcile_cash_journal(SAMPLE_05_10)
    cj = out["cash_journal"]
    assert cj["opening_cash"] == 925
    assert cj["opening_card"] == 1121
    assert cj["closing_cash"] == 3475
    assert cj["closing_card"] == 1121

    rush = next(l for l in cj["lines"] if "срочная" in (l.get("raw") or ""))
    assert rush["amount"] == 750
    assert rush["order_id"] == "124417"
    assert rush["action"] == "cash_in"

    prepay = next(l for l in cj["lines"] if "предоплата" in (l.get("raw") or ""))
    assert prepay["amount"] == 500
    assert prepay["order_id"] == "124424"
    assert prepay["action"] == "cash_in"

    assert not any(l.get("amount") == 124417 and "срочная" in (l.get("raw") or "") for l in cj["lines"])
    assert not any((l.get("raw") or "").strip() in ("1121", "1121\u2069") for l in cj["lines"])
    nalom = [l for l in cj["lines"] if "налом" in (l.get("raw") or "")]
    assert all(l["action"] == "ignore" for l in nalom)

    cps = [l["written_cash"] for l in cj["lines"] if l.get("is_checkpoint") and l.get("written_cash")]
    assert cps == [10475, 5475, 3475]
    assert all(l.get("cash_match") is True for l in cj["lines"] if l.get("is_checkpoint"))
    quotes = [l for l in cj["lines"] if l.get("is_quote")]
    assert quotes and all(l["action"] == "ignore" for l in quotes)


def test_breakdown_comma_amount_line():
    from modules.cash_journal.parser import _is_breakdown_line

    bd = _is_breakdown_line("121985 - Шлейфы , датчики, 2000")
    assert bd is not None
    assert bd.order_id == "121985"
    assert abs(bd.amount) == 2000


def test_find_supplier_order_id_helper():
    from modules.gincore.client import GincoreClient

    html = (
        '<div class="goods-item goods-item-441614">'
        '<a onclick="SupplierOrder.showEdit(this, \'128552\', false, 124130, 441614);">'
        "</a></div>"
    )
    assert GincoreClient.find_supplier_order_id_for_product(html, 441614) == "128552"
    form = (
        '<select name="warehouse-supplier">'
        '<option value="0">Не выбрано</option>'
        '<option value="95">prom.ua</option>'
        "</select>"
        '<input name="amount[128552]" value=""/>'
    )
    assert GincoreClient.resolve_supplier_id_from_form(form, "Prom.ua") == "95"

