"""Сверка недоплаченных квитанций таблицы с данными Gincore."""

from __future__ import annotations

from typing import Any

from modules.vyrobotka.parse import underpayment_amount

MONEY_TOL = 1.0  # грн — допустимое расхождение округления


def _money(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _close(a: float | None, b: float | None, tol: float = MONEY_TOL) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def _norm_status(s: Any) -> str:
    t = " ".join(str(s or "").casefold().replace("ё", "е").split())
    # В CRM бывает укорочено: «У курьера БЕЗ РЕМОНТ»
    if t.startswith("у курьера без ремонт"):
        return "у курьера без ремонта"
    return t


# Статусы CRM, при которых работы/долг в отчёте мастера выглядят подозрительно.
ATYPICAL_CRM_STATUSES = frozenset(
    {
        "выдан без ремонта",
        "не подлежит ремонту",
        "клиент отказался",
        "у курьера без ремонта",
        "собираем на возврат",
        "собран на возврат",
    }
)

# Готов к выдаче / выдан — нормальные статусы дебиторки other=pay.
READY_CRM_STATUSES = frozenset({"готов", "выдан"})
WRITE_OFF_CRM_STATUSES = ATYPICAL_CRM_STATUSES


def _max_money(*vals: Any) -> float:
    nums = [_money(v) for v in vals]
    present = [float(v) for v in nums if v is not None]
    return max(present) if present else 0.0


def classify_debt_row(row: dict[str, Any]) -> dict[str, Any]:
    """Классификация строки сводной таблицы дебиторки.

    Возвращает {active, flag, flag_reason}:
    - active=0 — долг в CRM закрыт (убрать из таблицы);
    - red — попытка скрыть дебиторку;
    - yellow — долг совпадает в отчёте и CRM;
    - open — долг только в CRM (нормально);
    - mismatch — обе стороны с долгом, суммы разные.
    """
    sheet_debt = _money(row.get("sheet_debt")) or 0.0
    crm_total = _money(row.get("crm_total"))
    crm_paid = _money(row.get("crm_paid")) or 0.0
    # None от underpayment_amount при полной оплате → 0 через total−paid
    crm_debt = resolve_crm_debt(row)
    on_pay = bool(int(row.get("on_pay_list") or 0))
    st = _norm_status(row.get("crm_status"))
    first_st = _norm_status(row.get("first_crm_status"))

    expected_debt = _max_money(
        row.get("first_sheet_debt"),
        row.get("first_crm_debt"),
        sheet_debt,
    )
    expected_total = _max_money(
        row.get("first_sheet_total"),
        row.get("first_crm_total"),
        row.get("sheet_total"),
    )
    first_on_pay = bool(int(row.get("first_on_pay_list") or 0))
    had_pay_signal = (
        first_on_pay
        or (_money(row.get("first_crm_debt")) or 0) > MONEY_TOL
        or sheet_debt > MONEY_TOL
    )
    unpaid = crm_debt is not None and float(crm_debt) > MONEY_TOL

    # R2 раньше remove: обнулили стоимость без оплаты — это скрытие, не «закрыли долг».
    # Если «к оплате»/долг в CRM ещё виден — это не обнуление, а рассинхрон полей
    # (раньше ловили span «Итого: 0» вместо «Стоимость ремонта»).
    if (
        expected_total > MONEY_TOL
        and crm_total is not None
        and float(crm_total) <= MONEY_TOL
        and crm_paid <= MONEY_TOL
        and not unpaid
    ):
        return {
            "active": 1,
            "flag": "red",
            "flag_reason": "Стоимость в CRM обнулена без оплаты",
        }

    # R1 write-off + деньги не собраны (в т.ч. когда crm_debt уже 0 из-за write-off)
    if st in WRITE_OFF_CRM_STATUSES:
        money_missing = unpaid or (
            expected_debt > MONEY_TOL and crm_paid + MONEY_TOL < expected_debt
        )
        if money_missing:
            return {
                "active": 1,
                "flag": "red",
                "flag_reason": f"Статус «{row.get('crm_status') or st}», оплата не собрана",
            }

    # Убрать: клиент реально закрыл долг в CRM (оплата пришла / долга нет)
    if crm_debt is not None and float(crm_debt) <= MONEY_TOL:
        if row.get("crm_checked_at") or on_pay or row.get("crm_status") is not None:
            return {
                "active": 0,
                "flag": None,
                "flag_reason": "В CRM долг закрыт",
            }

    # R3 снятие с готов/выдан при долге
    was_ready = first_st in READY_CRM_STATUSES
    now_ready = st in READY_CRM_STATUSES if st else False
    if was_ready and expected_debt > MONEY_TOL and st and not now_ready:
        if unpaid or not on_pay:
            return {
                "active": 1,
                "flag": "red",
                "flag_reason": (
                    f"Был «{row.get('first_crm_status')}», сейчас «{row.get('crm_status')}» "
                    f"при ожидаемом долге {expected_debt:g}"
                ),
            }

    # R4 пропал с other=pay при долге
    if had_pay_signal and not on_pay and unpaid and st and st not in READY_CRM_STATUSES:
        return {
            "active": 1,
            "flag": "red",
            "flag_reason": "Пропал из фильтра недоплат CRM при открытом долге",
        }

    # 3) Жёлтый — совпадение долгов
    if sheet_debt > MONEY_TOL and unpaid and _close(sheet_debt, crm_debt):
        return {
            "active": 1,
            "flag": "yellow",
            "flag_reason": "Долг совпадает в отчёте и CRM",
        }

    # 4) open — только CRM
    if unpaid and sheet_debt <= MONEY_TOL:
        return {
            "active": 1,
            "flag": "open",
            "flag_reason": "Дебиторка в CRM, в отчётах мастеров нет",
        }

    # 5) mismatch — обе стороны, суммы разные
    if sheet_debt > MONEY_TOL and unpaid and not _close(sheet_debt, crm_debt):
        return {
            "active": 1,
            "flag": "mismatch",
            "flag_reason": (
                f"Долг: отчёт {_fmt_money(sheet_debt)} ≠ CRM {_fmt_money(crm_debt)}"
            ),
        }

    # sheet-only ещё не сверено с CRM
    if sheet_debt > MONEY_TOL and crm_debt is None:
        return {
            "active": 1,
            "flag": "open",
            "flag_reason": "Есть в отчёте, CRM ещё не проверен",
        }

    return {
        "active": 1,
        "flag": "open",
        "flag_reason": "На контроле",
    }


def is_atypical_debt_case(
    *,
    sheet_total: Any,
    crm_total: Any,
    sheet_debt: Any,
    report_amount: Any,
    crm_status: Any,
    crm_debt: Any = None,
    crm_paid: Any = None,
) -> bool:
    """Нетипичный случай: отказ/без ремонта в CRM, а в отчёте долг клиента и сумма работ.

    Условия:
    - статус CRM из списка отказов / без ремонта / возврат;
    - в отчёте есть стоимость ремонта (> 0);
    - в отчёте клиент должен денег (долг > 0);
    - мастер вписал себе стоимость работ (> 0);
    - в CRM долг ещё не закрыт (иначе это просто устаревшая таблица, как 121399).
    """
    if _norm_status(crm_status) not in ATYPICAL_CRM_STATUSES:
        return False
    # В базе уже оплачено / долга нет — не тащим в нетипичные
    cd = _money(crm_debt)
    if cd is None or cd <= MONEY_TOL:
        return False
    st = _money(sheet_total)
    if st is None or st <= MONEY_TOL:
        return False
    debt = _money(sheet_debt)
    if debt is None or debt <= MONEY_TOL:
        return False
    work = _money(report_amount)
    if work is None or work <= MONEY_TOL:
        return False
    return True


def _fmt_money(v: float | None) -> str:
    if v is None:
        return "—"
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.2f}"


def crm_totals_from_payment(payment: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """(total, paid, debt) из parse_order_payment.

    Стоимость = «Стоимость ремонта» (блок Оплата), не сумма работ/запчастей
    и не span «Итого: 0 грн». «Итого со скидкой» — только запасной вариант.

    Важно: при полной оплате debt=0.0, а не None.
    None у underpayment_amount значит «нет недоплаты» для Sheets;
    в ledger None читается как «CRM ещё не проверен» — путаница.
    """
    total = _money(payment.get("repair_cost"))
    if total is None:
        total = _money(payment.get("total_with_discount"))
    paid = _money(payment.get("paid"))
    if paid is None:
        paid = 0.0 if total is not None else None
    due = _money(payment.get("due"))
    debt = underpayment_amount(total, paid)
    if debt is None and due is not None and due > MONEY_TOL:
        # CRM иногда показывает «к оплате» явно
        debt = round(float(due), 2)
    elif debt is None and total is not None and paid is not None:
        # полная оплата / переплата → явный ноль
        debt = 0.0
    return total, paid, debt


def resolve_crm_debt(row: dict[str, Any]) -> float | None:
    """Долг CRM: явный crm_debt, иначе total−paid если суммы известны."""
    explicit = _money(row.get("crm_debt"))
    if explicit is not None:
        return explicit
    total = _money(row.get("crm_total"))
    paid = _money(row.get("crm_paid"))
    if total is None or paid is None:
        return None
    return max(0.0, round(float(total) - float(paid), 2))


def compare_ticket_with_crm(
    sheet: dict[str, Any],
    *,
    crm_total: float | None = None,
    crm_paid: float | None = None,
    crm_debt: float | None = None,
    crm_status: str | None = None,
    crm_url: str | None = None,
    missing: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    """Сравнить строку таблицы с CRM. verdict: ok | mismatch | missing | error."""
    sheet_total = _money(sheet.get("total_repair"))
    sheet_paid = _money(sheet.get("paid"))
    if sheet_paid is None:
        sheet_paid = 0.0
    sheet_debt = _money(sheet.get("debt"))
    if sheet_debt is None:
        sheet_debt = underpayment_amount(sheet_total, sheet_paid)
    sheet_status = sheet.get("status")

    base: dict[str, Any] = {
        "sheet_title": sheet.get("sheet_title"),
        "master": sheet.get("master"),
        "ticket": str(sheet.get("ticket") or ""),
        "sheet_total": sheet_total,
        "sheet_paid": sheet_paid,
        "sheet_debt": sheet_debt,
        "sheet_status": sheet_status,
        "crm_total": crm_total,
        "crm_paid": crm_paid,
        "crm_debt": crm_debt,
        "crm_status": crm_status,
        "crm_url": crm_url,
        "issues": [],
        "field_diffs": {},
        "summary": "",
    }

    if error:
        base["verdict"] = "error"
        base["issues"] = [error]
        base["summary"] = error
        return base
    if missing:
        base["verdict"] = "missing"
        base["issues"] = ["Заказ не найден / нет доступа в Gincore"]
        base["summary"] = "Нет в CRM"
        # подсветить все денежные поля — в CRM нет опоры
        base["field_diffs"] = {
            "total": {"sheet": sheet_total, "crm": None, "label": "стоимость"},
            "paid": {"sheet": sheet_paid, "crm": None, "label": "оплачено"},
            "debt": {"sheet": sheet_debt, "crm": None, "label": "долг"},
            "status": {"sheet": sheet_status, "crm": None, "label": "статус"},
        }
        return base

    issues: list[str] = []
    field_diffs: dict[str, dict[str, Any]] = {}

    if not _close(sheet_total, crm_total):
        field_diffs["total"] = {
            "sheet": sheet_total,
            "crm": crm_total,
            "label": "стоимость",
        }
        issues.append(
            f"стоимость: таблица {_fmt_money(sheet_total)} ≠ CRM {_fmt_money(crm_total)}"
        )
    if not _close(sheet_paid, crm_paid):
        field_diffs["paid"] = {
            "sheet": sheet_paid,
            "crm": crm_paid,
            "label": "оплачено",
        }
        issues.append(
            f"оплачено: таблица {_fmt_money(sheet_paid)} ≠ CRM {_fmt_money(crm_paid)}"
        )

    debt_mismatch = False
    if sheet_debt is not None and (crm_debt is None or crm_debt <= MONEY_TOL):
        if (sheet_debt or 0) > MONEY_TOL:
            debt_mismatch = True
            issues.append("в таблице долг, в CRM оплаты хватает")
    elif not _close(sheet_debt, crm_debt):
        debt_mismatch = True
        issues.append(
            f"долг: таблица {_fmt_money(sheet_debt)} ≠ CRM {_fmt_money(crm_debt)}"
        )
    if debt_mismatch:
        field_diffs["debt"] = {
            "sheet": sheet_debt,
            "crm": crm_debt,
            "label": "долг",
        }

    st_sheet = _norm_status(sheet_status)
    st_crm = _norm_status(crm_status)
    if st_sheet and st_crm and st_sheet != st_crm:
        field_diffs["status"] = {
            "sheet": sheet_status,
            "crm": crm_status,
            "label": "статус",
        }
        issues.append(f"статус: «{sheet_status}» ≠ «{crm_status}»")

    if issues:
        base["issues"] = issues
        base["field_diffs"] = field_diffs
        base["summary"] = "; ".join(issues)
        # В CRM уже выдан и оплачен — таблица устарела, это не проблема дебиторки.
        if is_crm_settled_issued(base):
            base["verdict"] = "norm"
            base["summary"] = "Норма: в CRM «Выдан», долга нет · " + base["summary"]
        else:
            base["verdict"] = "mismatch"
    else:
        base["verdict"] = "ok"
        base["issues"] = []
        base["field_diffs"] = {}
        base["summary"] = "Совпадает с CRM"
    return base


def is_crm_settled_issued(row: dict[str, Any]) -> bool:
    """CRM: статус «Выдан» и реального долга нет."""
    if _norm_status(row.get("crm_status")) != "выдан":
        return False
    debt = _money(row.get("crm_debt"))
    return debt is None or float(debt) <= MONEY_TOL


def display_verdict(row: dict[str, Any]) -> str:
    """Вердикт для UI без перезаписи БД (старые mismatch → norm)."""
    raw = str(row.get("verdict") or "")
    if raw == "norm":
        return "norm"
    if raw == "mismatch" and is_crm_settled_issued(row):
        return "norm"
    return raw or "error"


def apply_display_verdicts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Копии строк с display-вердиктом; исходные записи в SQLite не меняются."""
    out: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        dv = display_verdict(item)
        item["stored_verdict"] = item.get("verdict")
        item["verdict"] = dv
        if dv == "norm" and item.get("stored_verdict") == "mismatch":
            summary = str(item.get("summary") or "")
            if not summary.casefold().startswith("норма"):
                item["summary"] = "Норма: в CRM «Выдан», долга нет · " + summary
        out.append(item)
    return out


def pack_issues_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Структура для issues_json в БД."""
    return {
        "messages": list(result.get("issues") or []),
        "fields": dict(result.get("field_diffs") or {}),
    }


def unpack_issues_payload(raw: Any) -> tuple[list[str], dict[str, Any]]:
    """Обратная совместимость: старый формат — список строк."""
    if isinstance(raw, list):
        return [str(x) for x in raw], {}
    if isinstance(raw, dict):
        messages = raw.get("messages")
        if not isinstance(messages, list):
            messages = []
        fields = raw.get("fields")
        if not isinstance(fields, dict):
            fields = {}
        return [str(x) for x in messages], fields
    return [], {}


def hydrate_field_diffs(row: dict[str, Any]) -> dict[str, Any]:
    """Если field_diffs пуст (старые записи) — восстановить из сохранённых сумм."""
    existing = row.get("field_diffs")
    if isinstance(existing, dict) and existing:
        return existing
    if str(row.get("verdict") or "") not in {"mismatch", "missing", "norm"}:
        return {}
    rebuilt = compare_ticket_with_crm(
        {
            "sheet_title": row.get("sheet_title"),
            "ticket": row.get("ticket"),
            "master": row.get("master"),
            "total_repair": row.get("sheet_total"),
            "paid": row.get("sheet_paid"),
            "debt": row.get("sheet_debt"),
            "status": row.get("sheet_status"),
        },
        crm_total=row.get("crm_total"),
        crm_paid=row.get("crm_paid"),
        crm_debt=row.get("crm_debt"),
        crm_status=row.get("crm_status"),
        crm_url=row.get("crm_url"),
        missing=str(row.get("verdict") or "") == "missing",
    )
    return rebuilt.get("field_diffs") or {}


def build_verify_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"ok": 0, "norm": 0, "mismatch": 0, "missing": 0, "error": 0}
    for r in results:
        v = str(r.get("verdict") or "error")
        counts[v] = counts.get(v, 0) + 1
    bad = [r for r in results if r.get("verdict") in {"mismatch", "missing", "error"}]
    bad.sort(key=lambda x: (-float(x.get("sheet_debt") or 0), str(x.get("ticket") or "")))
    return {
        "total": len(results),
        "ok": counts.get("ok", 0),
        "norm": counts.get("norm", 0),
        "mismatch": counts.get("mismatch", 0),
        "missing": counts.get("missing", 0),
        "error": counts.get("error", 0),
        "bad_count": len(bad),
        "top_issues": [
            {
                "ticket": r.get("ticket"),
                "sheet_title": r.get("sheet_title"),
                "verdict": r.get("verdict"),
                "summary": r.get("summary"),
                "sheet_debt": r.get("sheet_debt"),
                "crm_debt": r.get("crm_debt"),
                "field_diffs": r.get("field_diffs") or {},
            }
            for r in bad[:40]
        ],
    }
