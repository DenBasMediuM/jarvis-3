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
    return " ".join(str(s or "").casefold().split())


def _fmt_money(v: float | None) -> str:
    if v is None:
        return "—"
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.2f}"


def crm_totals_from_payment(payment: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """(total, paid, debt) из parse_order_payment."""
    total = _money(payment.get("total_with_discount"))
    if total is None:
        total = _money(payment.get("repair_cost"))
    paid = _money(payment.get("paid"))
    if paid is None:
        paid = 0.0 if total is not None else None
    due = _money(payment.get("due"))
    debt = underpayment_amount(total, paid)
    if debt is None and due is not None and due > MONEY_TOL:
        # CRM иногда показывает «к оплате» явно
        debt = round(float(due), 2)
    return total, paid, debt


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
