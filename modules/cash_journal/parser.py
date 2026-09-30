"""Deterministic cash journal reconciliation from chat paste."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


TELEGRAM_PREFIX = re.compile(
    r"^\[?\d{1,2}[./]\d{1,2}[./]\d{2,4}[^\]]*\]?\s*[^:]{0,80}:\s*",
    re.UNICODE,
)
TELEGRAM_MSG_START = re.compile(
    r"\[\d{1,2}[./]\d{1,2}[./]\d{2,4}[^\]]*\]",
    re.UNICODE,
)

# 5к / 5k = 5000; не цеплять «к» из «касса»
K_THOUSAND = r"[kк](?![a-zA-Zа-яА-ЯёЁ])"
# Пробел только как разделитель тысяч («1 800»), не «1800 3 банки»
MONEY_NUM = (
    rf"(?:\d{{1,3}}(?:[ \u00a0]\d{{3}})+|\d+)"
    rf"(?:[.,]\d{{1,2}})?"
    rf"(?:\s*{K_THOUSAND})?"
)

OPENING_CASH = re.compile(
    rf"касс?[аыу]?\s*[:\-–—]\s*([+-]?{MONEY_NUM})",
    re.IGNORECASE,
)
OPENING_CARD = re.compile(
    rf"карт[аыу]?\s*[:\-–—]\s*([+-]?{MONEY_NUM})",
    re.IGNORECASE,
)
CASH_FACT = re.compile(
    rf"касс?[аыу]?\s+факт\s*:?\s*([+-]?{MONEY_NUM})",
    re.IGNORECASE,
)

ORDER_SIGNED = re.compile(
    rf"(?P<order>\d{{4,}})\s*(?P<sign>[+\-−–])\s*(?P<amount>{MONEY_NUM})"
    r"(?:\s*(?:грн|uah|₴))?",
    re.IGNORECASE,
)

# With or without currency: "-4000 грн ЗП", "-200 смс", "+750 пред", "-5к аренда"
SIGNED_FIRST = re.compile(
    rf"^(?P<sign>[+\-−–])\s*(?P<amount>{MONEY_NUM})"
    r"(?:\s*(?:грн|uah|₴))?\.?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

BREAKDOWN_LINE = re.compile(
    rf"^(?P<order>\d{{4,}})\s*[-–—]\s*(?P<item>.+?)\s*[-–—]\s*(?P<amount>{MONEY_NUM})\s*$",
    re.UNICODE,
)
# «120247 - 2000 - тачскрин , барабан, впз» — сумма в середине
BREAKDOWN_AMT_MID = re.compile(
    rf"^(?P<order>\d{{4,}})\s*[-–—]\s*(?P<amount>{MONEY_NUM})\s*[-–—]\s*(?P<item>.+)\s*$",
    re.UNICODE,
)
# «121985 - Шлейфы , датчики, 2000» — сумма после запятой в конце
BREAKDOWN_COMMA_AMT = re.compile(
    rf"^(?P<order>\d{{4,}})\s*[-–—]\s*(?P<item>.+),\s*(?P<amount>{MONEY_NUM})\s*$",
    re.UNICODE,
)
ZCH_LINE_PREFIX = re.compile(r"^зч\.?\s+", re.IGNORECASE)

ZCH_HINT = re.compile(r"\bзч\b|запчаст", re.IGNORECASE)


def parse_money(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = str(raw).replace("\xa0", " ").replace("₴", "")
    s = s.replace("−", "-").replace("–", "-")
    s = re.sub(r"(?i)грн|uah", "", s).strip()
    m = re.search(
        rf"([+-]?)((?:\d{{1,3}}(?:[ ]\d{{3}})+|\d+))(?:[.,](\d{{1,2}}))?({K_THOUSAND})?",
        s,
        re.IGNORECASE,
    )
    if not m:
        return None
    sign = -1.0 if m.group(1) == "-" else 1.0
    whole = m.group(2).replace(" ", "")
    frac = m.group(3)
    base = float(f"{whole}.{frac}") if frac is not None else float(whole)
    if m.group(4):
        base *= 1000.0
    return sign * base


def _norm_sign(ch: str) -> str:
    return "-" if ch in {"-", "−", "–"} else "+"


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def strip_prefix(line: str) -> str:
    return TELEGRAM_PREFIX.sub("", line.strip()).strip()


def normalize_journal_text(text: str) -> str:
    """Если ИИ/чат склеил сообщения в одну строку — разрезать по меткам [дата]."""
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(
        r"(?<!^)(?<!\n)(\[\d{1,2}[./]\d{1,2}[./]\d{2,4}[^\]]*\])",
        r"\n\1",
        s,
    )
    return s


def _strip_chat_labels(body: str) -> str:
    """Убрать «Прием екат:» / имя автора, если остались после telegram-префикса.

    Иначе «Прием екат: - 2170» не матчится SIGNED_FIRST (^) и уезжает в конец
    списка как unrecognized — ломается порядок строк.
    """
    s = _norm_space(body)
    while True:
        # не трогаем «касса: N» / «карта: N»
        if OPENING_CASH.match(s) or OPENING_CARD.match(s) or CASH_FACT.match(s):
            break
        # уже операция: +/−сумма или номер заказа
        if re.match(rf"^[+\-−–]\s*{MONEY_NUM}", s) or re.match(r"^\d{4,}\b", s):
            break
        m = re.match(r"^([^:\n]{1,60}):\s+", s)
        if not m:
            break
        s = s[m.end() :].strip()
        if not s:
            break
    return s


def detect_bucket(note: str) -> str:
    n = note.lower().replace("ё", "е")
    if re.search(r"на\s+карт", n):
        return "card"
    if re.search(r"фоп|на\s+счет|на\s+счёт|на\s+рахунок", n):
        return "fop"
    return "cash"


_CASH_NEAR = re.compile(r"\bнал(?:\.|ичн|\s|$)|готівк", re.IGNORECASE)
# «и» / укр. «і» / лат. «i»
_AND_SPLIT = re.compile(r"\s+[иіi]\s+", re.IGNORECASE)


def _bucket_for_amount(body: str, amt_start: int, amt_end: int) -> str:
    """Корзина по контексту вокруг одной суммы, а не всей строки."""
    left = max(0, amt_start - 30)
    conj_end = -1
    for m in _AND_SPLIT.finditer(body[:amt_start]):
        conj_end = m.end()
    if conj_end >= 0:
        left = max(left, conj_end)
    tail = body[amt_end : amt_end + 80]
    split_m = _AND_SPLIT.search(tail)
    right = amt_end + (split_m.start() if split_m else min(len(tail), 80))
    snippet = body[left:right]
    if _CASH_NEAR.search(snippet):
        return "cash"
    return detect_bucket(snippet)


def _in_spans(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in spans)


def _extra_amount_ops(
    body: str,
    *,
    skip: tuple[int, int],
    order_id: str | None,
    main_sign: float = 1.0,
) -> list[JournalOp]:
    """Доп. суммы на той же строке: «… -50», «… и 200 грн на карту»."""
    out: list[JournalOp] = []
    paren_spans: list[tuple[int, int]] = [
        (m.start(), m.end()) for m in re.finditer(r"\([^)]*\)", body)
    ]
    seen: set[tuple[int, int]] = set()

    def _append(m: re.Match, *, sign_ch: str | None, conjunction: bool) -> None:
        key = (m.start("amount"), m.end("amount"))
        if key in seen:
            return
        if skip[0] <= m.start() < skip[1]:
            return
        if _in_spans(m.start(), paren_spans):
            return
        if TELEGRAM_MSG_START.search(body[skip[1] : m.start()]):
            return
        val = parse_money(m.group("amount"))
        if val is None or abs(val) < 1e-9:
            return
        if conjunction:
            snippet_end = min(len(body), m.end("amount") + 40)
            snippet = body[m.start() : snippet_end]
            if not (
                re.search(r"(?i)грн|uah|₴", snippet)
                or detect_bucket(snippet) != "cash"
                or _CASH_NEAR.search(snippet)
            ):
                return
        if sign_ch:
            sign = 1.0 if _norm_sign(sign_ch) == "+" else -1.0
        else:
            sign = 1.0 if main_sign >= 0 else -1.0
        bucket = _bucket_for_amount(body, m.start("amount"), m.end("amount"))
        amount = _cash_portion_amount(body, sign * abs(val), bucket)
        left = max(0, m.start() - 24)
        right = min(len(body), m.end() + 40)
        note = _norm_space(body[left:right])
        out.append(
            JournalOp(
                amount=amount,
                bucket=bucket,
                note=note or body,
                order_id=order_id,
                raw=note or body,
            )
        )
        seen.add(key)

    for m in re.finditer(rf"(?<!\d)(?P<sign>[+\-−–])\s*(?P<amount>{MONEY_NUM})", body):
        _append(m, sign_ch=m.group("sign"), conjunction=False)

    for m in re.finditer(
        rf"(?<=\s[иіi]\s)(?:(?P<sign>[+\-−–])\s*)?(?P<amount>{MONEY_NUM})"
        rf"(?:\s*(?:грн|uah|₴))?\.?\s*",
        body,
        re.IGNORECASE,
    ):
        _append(m, sign_ch=m.group("sign"), conjunction=True)

    return out


@dataclass
class JournalOp:
    amount: float
    bucket: str
    note: str = ""
    order_id: str | None = None
    raw: str = ""
    kind: str = "operation"  # operation | breakdown_skip
    breakdown_of: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JournalResult:
    opening_cash: float = 0.0
    opening_card: float = 0.0
    opening_fop: float = 0.0
    closing_cash: float = 0.0
    closing_card: float = 0.0
    closing_fop: float = 0.0
    operations: list[JournalOp] = field(default_factory=list)
    skipped_breakdown: list[JournalOp] = field(default_factory=list)
    unrecognized: list[str] = field(default_factory=list)
    # порядок UI: ("op"|"unrec", index) — как в исходном тексте
    line_order: list[tuple[str, int]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "opening": {
                "cash": self.opening_cash,
                "card": self.opening_card,
                "fop": self.opening_fop,
            },
            "closing": {
                "cash": self.closing_cash,
                "card": self.closing_card,
                "fop": self.closing_fop,
            },
            "operations": [o.to_dict() for o in self.operations],
            "skipped_breakdown": [o.to_dict() for o in self.skipped_breakdown],
            "unrecognized": list(self.unrecognized),
            "warnings": self.warnings,
            "totals": {
                "cash_in": sum(
                    o.amount for o in self.operations if o.bucket == "cash" and o.amount > 0
                ),
                "cash_out": sum(
                    o.amount for o in self.operations if o.bucket == "cash" and o.amount < 0
                ),
                "card_in": sum(
                    o.amount for o in self.operations if o.bucket == "card" and o.amount > 0
                ),
                "card_out": sum(
                    o.amount for o in self.operations if o.bucket == "card" and o.amount < 0
                ),
                "fop_in": sum(
                    o.amount for o in self.operations if o.bucket == "fop" and o.amount > 0
                ),
                "fop_out": sum(
                    o.amount for o in self.operations if o.bucket == "fop" and o.amount < 0
                ),
            },
        }


def _extract_order(text: str) -> str | None:
    m = re.search(r"\b(\d{5,})\b", text)
    return m.group(1) if m else None


def _is_breakdown_line(body: str) -> JournalOp | None:
    body = _norm_space(body)
    if re.search(r"[+]|\bгрн\b|\buah\b|₴", body, re.I):
        return None
    # «зч 122114 - помпа - 1500»
    core = ZCH_LINE_PREFIX.sub("", body).strip()

    def _make(order: str, item: str, amount_raw: str) -> JournalOp | None:
        item = _norm_space(item)
        if not item:
            return None
        val = parse_money(amount_raw)
        if val is None or abs(val) < 1e-9:
            return None
        return JournalOp(
            amount=-abs(val),
            bucket="cash",
            note=f"{order} — {item} — {abs(val):g}",
            order_id=order,
            raw=body,
            kind="breakdown_skip",
        )

    m = BREAKDOWN_LINE.match(core)
    if m:
        item = _norm_space(m.group("item"))
        # «122712 - 775 АКБ …» без второго «- название» — не расшифровка
        if not re.match(r"\d", item):
            return _make(m.group("order"), item, m.group("amount"))

    m = BREAKDOWN_AMT_MID.match(core)
    if m:
        item = _norm_space(m.group("item"))
        # описание должно быть текстом, не ещё одной суммой
        if item and not re.fullmatch(rf"{MONEY_NUM}", item):
            return _make(m.group("order"), item, m.group("amount"))

    m = BREAKDOWN_COMMA_AMT.match(core)
    if m:
        item = _norm_space(m.group("item"))
        # описание текстом (не «123956 -256, что-то»)
        if item and not re.match(r"\d", item):
            return _make(m.group("order"), item, m.group("amount"))
    return None


# «-5500 аренда (500 взял с кассы)» → на кассу влияет только 500
CASH_PORTION = re.compile(
    rf"\((?P<amt>{MONEY_NUM})\s*(?:взял(?:а|и)?\s+)?с\s+касс",
    re.I,
)
CASH_PORTION_ALT = re.compile(
    rf"(?:из\s+них|из\s+которых)\s+(?P<amt>{MONEY_NUM})\s*(?:взял(?:а|и)?\s+)?с\s+касс",
    re.I,
)


def _cash_portion_amount(body: str, signed_amount: float, bucket: str) -> float:
    """If note says only N was taken from cash, use N (same sign) for cash ops."""
    if bucket != "cash" or abs(signed_amount) < 1e-9:
        return signed_amount
    m = CASH_PORTION.search(body) or CASH_PORTION_ALT.search(body)
    if not m:
        return signed_amount
    portion = parse_money(m.group("amt"))
    if portion is None or portion <= 0:
        return signed_amount
    if portion + 1e-9 < abs(signed_amount):
        return (-portion) if signed_amount < 0 else portion
    return signed_amount


def _parse_operation_line(body: str) -> JournalOp | None:
    ops = _parse_operation_lines(body)
    return ops[0] if ops else None


def _extra_signed_ops(
    body: str,
    *,
    skip: tuple[int, int],
    order_id: str | None,
    main_sign: float = 1.0,
) -> list[JournalOp]:
    return _extra_amount_ops(
        body, skip=skip, order_id=order_id, main_sign=main_sign
    )


# «122857 2154 грн детали»
_PAREN_ORDER_AMT = re.compile(
    rf"^(?P<order>\d{{4,}})\s+(?P<amount>{MONEY_NUM})\s*(?:грн|uah|₴)?\.?\s*(?P<rest>.*)$",
    re.I,
)
# «94 грн доставка…» / «+ 50 грн курьер» / «90грн доставка…»
_PAREN_AMT = re.compile(
    rf"^(?P<sign>[+\-−–])?\s*(?P<amount>{MONEY_NUM})\s*(?:грн|uah|₴)?\.?\s*(?P<rest>.*)$",
    re.I,
)
# «122990 акум 463 грн»
_PAREN_ORDER_LABEL_AMT = re.compile(
    rf"^(?P<order>\d{{4,}})\s+(?P<label>.+?)\s+(?P<amount>{MONEY_NUM})\s*(?:грн|uah|₴)\.?\s*$",
    re.I,
)
# «доставка 90 грн» / «сенсор 417 грн» / «…расходка 389 грн»
_PAREN_LABEL_AMT = re.compile(
    rf"^(?P<label>.+?)\s+(?P<sign>[+\-−–])?\s*(?P<amount>{MONEY_NUM})\s*(?:грн|uah|₴)\.?\s*$",
    re.I,
)
_PAREN_HAS_AMT = re.compile(
    rf"(?:^|[+\-−–]\s*|(?<=\s))({MONEY_NUM})\s*(?:грн|uah|₴)\b",
    re.I,
)


def _paren_item_signed(val: float, *, parent_sign: float, sign_ch: str | None) -> float:
    if sign_ch:
        sign = 1.0 if _norm_sign(sign_ch) == "+" else -1.0
        if parent_sign < 0 and sign > 0:
            return -abs(val)
        return sign * abs(val)
    return parent_sign * abs(val)


def _parse_paren_breakdown_item(
    part: str,
    *,
    parent_sign: float,
    parent_bucket: str,
) -> JournalOp | None:
    part = _norm_space(part)
    if not part:
        return None

    def _op(amount: float, *, order_id: str | None = None) -> JournalOp:
        return JournalOp(
            amount=amount,
            bucket=detect_bucket(part) if detect_bucket(part) != "cash" else parent_bucket,
            note=part,
            order_id=order_id,
            raw=part,
        )

    m = _PAREN_ORDER_AMT.match(part)
    if m:
        val = parse_money(m.group("amount"))
        if val is not None and abs(val) >= 1e-9:
            return _op(parent_sign * abs(val), order_id=m.group("order"))

    m = _PAREN_AMT.match(part)
    if m and (m.group("sign") or re.match(rf"^{MONEY_NUM}\s*(?:грн|uah|₴)", part, re.I)):
        val = parse_money(m.group("amount"))
        if val is not None and abs(val) >= 1e-9:
            return _op(
                _paren_item_signed(val, parent_sign=parent_sign, sign_ch=m.group("sign")),
                order_id=None,
            )

    m = _PAREN_ORDER_LABEL_AMT.match(part)
    if m:
        val = parse_money(m.group("amount"))
        if val is not None and abs(val) >= 1e-9:
            return _op(parent_sign * abs(val), order_id=m.group("order"))

    m = _PAREN_LABEL_AMT.match(part)
    if m:
        val = parse_money(m.group("amount"))
        if val is not None and abs(val) >= 1e-9:
            oid = None
            lab = m.group("label") or ""
            om = re.match(r"^(\d{4,})\b", lab)
            if om:
                oid = om.group(1)
            return _op(
                _paren_item_signed(val, parent_sign=parent_sign, sign_ch=m.group("sign")),
                order_id=oid,
            )
    return None


def _merge_paren_parts_without_amount(parts: list[str]) -> list[str]:
    """«123090 подсветка» + «доставка 90 грн» → одна позиция с суммой."""
    merged: list[str] = []
    buf: list[str] = []
    for part in parts:
        if _PAREN_HAS_AMT.search(part) or re.match(
            rf"^[+\-−–]\s*{MONEY_NUM}", part
        ):
            chunk = _norm_space(" ".join([*buf, part])) if buf else part
            merged.append(chunk)
            buf = []
        else:
            buf.append(part)
    if buf and merged:
        merged[-1] = _norm_space(merged[-1] + " " + " ".join(buf))
    elif buf:
        return []
    return merged


def _split_paren_breakdown_parts(inner: str) -> list[str]:
    """Split «a, b, c + d» into items (comma and trailing signed amounts)."""
    out: list[str] = []
    for chunk in re.split(r"\s*,\s*", inner):
        chunk = _norm_space(chunk)
        if not chunk:
            continue
        pieces = re.split(
            rf"(?<=\S)\s+(?=[+\-−–]\s*{MONEY_NUM})",
            chunk,
        )
        for p in pieces:
            p = _norm_space(p)
            if p:
                out.append(p)
    return out


def _try_paren_breakdown(
    body: str,
    *,
    main_sign: float,
    main_abs: float,
    bucket: str,
    after: int = 0,
) -> list[JournalOp] | None:
    """«-2388 грн (94 грн …)» / «-1409 грн (доставка 90 грн, …)» → отдельные операции.

    Если сумма позиций ≈ итогу — вместо одной строки с итогом.
    Не трогаем «(500 взял с кассы)».
    """
    if CASH_PORTION.search(body) or CASH_PORTION_ALT.search(body):
        return None
    m = re.search(r"\(([^)]+)\)", body[after:])
    if not m:
        return None
    inner = _norm_space(m.group(1))
    if not inner:
        return None
    parts = _merge_paren_parts_without_amount(_split_paren_breakdown_parts(inner))
    if len(parts) < 2:
        return None
    ops: list[JournalOp] = []
    for part in parts:
        op = _parse_paren_breakdown_item(
            part,
            parent_sign=main_sign,
            parent_bucket=bucket,
        )
        if op is None:
            return None
        ops.append(op)
    total = sum(abs(o.amount) for o in ops)
    if abs(total - main_abs) > 1.0:
        return None
    return ops


def _parse_operation_lines(body: str) -> list[JournalOp]:
    body = _strip_chat_labels(_norm_space(body))
    if not body:
        return []
    if _is_breakdown_line(body):
        return []

    m = ORDER_SIGNED.search(body)
    if m:
        has_currency = bool(re.search(r"(?i)грн|uah|₴", body))
        val = parse_money(m.group("amount"))
        if val is None:
            return []
        sign_ch = _norm_sign(m.group("sign"))
        # "122955 +750" / "122955 +750 грн" / "122466 +1500 пред на карту"
        if not has_currency and not re.search(
            rf"{m.group('order')}\s*{re.escape(m.group('sign'))}", body
        ):
            return []
        sign = 1.0 if sign_ch == "+" else -1.0
        bucket = _bucket_for_amount(body, m.start("amount"), m.end("amount"))
        amount = _cash_portion_amount(body, sign * abs(val), bucket)
        paren_ops = _try_paren_breakdown(
            body,
            main_sign=sign,
            main_abs=abs(val),
            bucket=bucket,
            after=m.end("amount"),
        )
        if paren_ops:
            return paren_ops
        main = JournalOp(
            amount=amount,
            bucket=bucket,
            note=body,
            order_id=m.group("order"),
            raw=body,
        )
        # span covers «- 775» / «+ 3400»
        skip = (m.start("sign"), m.end("amount"))
        extras = _extra_signed_ops(
            body, skip=skip, order_id=m.group("order"), main_sign=sign
        )
        return [main, *extras]

    m = SIGNED_FIRST.match(body)
    if m:
        val = parse_money(m.group("amount"))
        if val is None:
            return []
        sign = 1.0 if _norm_sign(m.group("sign")) == "+" else -1.0
        bucket = _bucket_for_amount(body, m.start("amount"), m.end("amount"))
        amount = _cash_portion_amount(body, sign * abs(val), bucket)
        paren_ops = _try_paren_breakdown(
            body,
            main_sign=sign,
            main_abs=abs(val),
            bucket=bucket,
            after=m.end("amount"),
        )
        if paren_ops:
            return paren_ops
        main = JournalOp(
            amount=amount,
            bucket=bucket,
            note=body,
            order_id=_extract_order(body),
            raw=body,
        )
        skip = (m.start("sign"), m.end("amount"))
        extras = _extra_signed_ops(
            body, skip=skip, order_id=main.order_id, main_sign=sign
        )
        return [main, *extras]
    return []


def _strip_balance_suffix(rest: str) -> str:
    """«Касса: 18392  грн» → после вырезания метки остаётся только валюта."""
    s = _norm_space(rest)
    return re.sub(r"(?i)(?:грн|uah|₴)\.?\s*$", "", s).strip()


def _parse_balance_markers(body: str) -> tuple[float | None, float | None, str]:
    """«Касса: N», «Каса: N», «касса факт N», «Карта: N» → суммы и хвост."""
    body = _norm_space(body)
    cash_m = OPENING_CASH.search(body)
    card_m = OPENING_CARD.search(body)
    fact_m = None if cash_m else CASH_FACT.search(body)
    rest = body
    if cash_m:
        rest = OPENING_CASH.sub(" ", rest, count=1)
    elif fact_m:
        rest = CASH_FACT.sub(" ", rest, count=1)
    if card_m:
        rest = OPENING_CARD.sub(" ", rest, count=1)
    rest = _strip_balance_suffix(rest)
    written_cash: float | None = None
    if cash_m:
        written_cash = float(parse_money(cash_m.group(1)) or 0)
    elif fact_m:
        written_cash = float(parse_money(fact_m.group(1)) or 0)
    written_card = float(parse_money(card_m.group(1)) or 0) if card_m else None
    return written_cash, written_card, rest


def _is_balance_marker_body(body: str) -> bool:
    s = _norm_space(body)
    return bool(OPENING_CASH.search(s) or OPENING_CARD.search(s) or CASH_FACT.search(s))


def _collect_bodies(text: str) -> tuple[float | None, float | None, list[str]]:
    opening_cash: float | None = None
    opening_card: float | None = None
    bodies: list[str] = []

    for line in normalize_journal_text(text).split("\n"):
        body = _strip_chat_labels(strip_prefix(line))
        if not body:
            continue
        written_cash, written_card, rest = _parse_balance_markers(body)
        has_cash = written_cash is not None
        has_card = written_card is not None

        # первая чистая строка «Касса: N» / «Карта: N» / «касса факт N» — стартовый остаток
        if has_cash and not rest and opening_cash is None and not has_card:
            opening_cash = written_cash
            continue
        if has_card and not rest and opening_card is None and not has_cash:
            opening_card = written_card
            continue
        if has_cash and has_card and not rest:
            if opening_cash is None:
                opening_cash = written_cash
            if opening_card is None:
                opening_card = written_card
            continue

        # повторные сверки — в список строк (checkpoint / ignore)
        if (has_cash or has_card) and not rest:
            bodies.append(body)
            continue

        if rest:
            bodies.append(body if rest == _norm_space(body) else rest)
        else:
            bodies.append(body)

    # fallback: если старты были в одной строке с мусором — search по всему тексту
    if opening_cash is None:
        cm = OPENING_CASH.search(text or "")
        if cm:
            opening_cash = float(parse_money(cm.group(1)) or 0)
    if opening_card is None:
        km = OPENING_CARD.search(text or "")
        if km:
            opening_card = float(parse_money(km.group(1)) or 0)

    return opening_cash, opening_card, bodies


def _recompute(result: JournalResult) -> None:
    result.closing_cash = result.opening_cash + sum(
        o.amount for o in result.operations if o.bucket == "cash"
    )
    result.closing_card = result.opening_card + sum(
        o.amount for o in result.operations if o.bucket == "card"
    )
    result.closing_fop = result.opening_fop + sum(
        o.amount for o in result.operations if o.bucket == "fop"
    )


def _looks_like_balance_remark(body: str) -> bool:
    n = _norm_space(body).lower()
    if re.search(r"\bв\s+касс[еаы]?\b", n) and re.search(r"\d", n):
        # «В кассе 1520 грн» — не операция
        if not re.match(r"^[+\-−–]", n):
            return True
    if re.search(r"\bостат\w*\s+(в\s+)?касс", n):
        return True
    return False


def _is_quote_line(body: str) -> bool:
    """Telegram-цитата в ответе («> 123430 -2060 зч») — не операция."""
    s = _norm_space(body).lstrip("\ufeff")
    return bool(re.match(r"^>\s*", s))


def _parse_balance_checkpoint(body: str) -> dict[str, float] | None:
    """Промежуточная сверка «Касса: 11589» / «КАССА: 132 грн» / «касса факт 5854»."""
    written_cash, written_card, rest = _parse_balance_markers(body)
    if rest or (written_cash is None and written_card is None):
        return None
    out: dict[str, float] = {}
    if written_cash is not None:
        out["written_cash"] = written_cash
    if written_card is not None:
        out["written_card"] = written_card
    return out or None


def parse_journal(
    text: str,
    *,
    opening_cash: float | None = None,
    opening_card: float | None = None,
    opening_fop: float | None = None,
) -> JournalResult:
    scanned_cash, scanned_card, bodies = _collect_bodies(text or "")
    # Текст журнала важнее аргументов модели (часто шлёт opening_*: 0).
    cash0 = float(
        scanned_cash if scanned_cash is not None else (opening_cash if opening_cash is not None else 0)
    )
    card0 = float(
        scanned_card if scanned_card is not None else (opening_card if opening_card is not None else 0)
    )
    fop0 = float(opening_fop or 0)

    result = JournalResult(opening_cash=cash0, opening_card=card0, opening_fop=fop0)
    if not (text or "").strip():
        result.warnings.append("Пустой текст журнала")
        return result

    i = 0
    while i < len(bodies):
        body = bodies[i]
        if _is_quote_line(body):
            result.unrecognized.append(body)
            result.line_order.append(("unrec", len(result.unrecognized) - 1))
            i += 1
            continue
        ops = _parse_operation_lines(body)
        if ops:
            j = i + 1
            items: list[JournalOp] = []
            main = ops[0]
            # Итог «−9600 Влад ЗЧ», но не позиция «123959 -427 зч»
            is_zch_total = (
                main.amount < 0
                and len(ops) == 1
                and ZCH_HINT.search(main.note)
                and not (
                    main.order_id
                    and re.match(
                        rf"^{re.escape(str(main.order_id))}\s*[-−–]\s*\d",
                        (main.raw or main.note or "").strip(),
                    )
                )
            )
            if is_zch_total:
                while j < len(bodies):
                    bd = _is_breakdown_line(bodies[j])
                    if not bd:
                        break
                    items.append(bd)
                    j += 1
                if items:
                    total = sum(abs(x.amount) for x in items)
                    if abs(total - abs(main.amount)) <= 1.0:
                        # Итог «−9600 ЗЧ» — ignore; в расчёт идут позиции расшифровки.
                        main.kind = "breakdown_total"
                        result.skipped_breakdown.append(main)
                        result.line_order.append(
                            ("bd", len(result.skipped_breakdown) - 1)
                        )
                        for it in items:
                            it.kind = "operation"
                            it.breakdown_of = main.raw
                            result.operations.append(it)
                            result.line_order.append(
                                ("op", len(result.operations) - 1)
                            )
                        i = j
                        continue
                    result.warnings.append(
                        f"Расшифровка ЗЧ не сходится с {main.amount:g}: сумма позиций {total:g}"
                    )
                    # детей не оставляем сиротами — иначе задвоим с итогом
                    for it in items:
                        result.skipped_breakdown.append(it)
                        result.line_order.append(
                            ("bd", len(result.skipped_breakdown) - 1)
                        )
                    for op in ops:
                        result.operations.append(op)
                        result.line_order.append(("op", len(result.operations) - 1))
                    i = j
                    continue
            for op in ops:
                result.operations.append(op)
                result.line_order.append(("op", len(result.operations) - 1))
            i += 1
            continue

        bd = _is_breakdown_line(body)
        if bd:
            # Одиночная позиция ЗЧ без итога — всё равно списываем с кассы.
            bd.kind = "spare_item"
            result.operations.append(bd)
            result.line_order.append(("op", len(result.operations) - 1))
            i += 1
            continue

        if _looks_like_balance_remark(body):
            i += 1
            continue

        result.unrecognized.append(body)
        result.line_order.append(("unrec", len(result.unrecognized) - 1))
        result.warnings.append(f"Не распознано: {body}")
        i += 1

    _recompute(result)
    return result


def _fmt(n: float) -> str:
    if abs(n - round(n)) < 1e-9:
        return f"{int(round(n)):,}".replace(",", " ")
    return f"{n:,.2f}".replace(",", " ")


def _guess_action(op: JournalOp) -> str:
    note = (op.note or op.raw or "").lower().replace("ё", "е")
    if re.search(
        r"(из|с)\s+касс\w*\s+(на|в)\s+карт|(касс\w*\s*[→>]\s*карт)",
        note,
    ):
        return "cash_to_card"
    if re.search(
        r"(из|с)\s+карт\w*\s+(на|в)\s+касс|(карт\w*\s*[→>]\s*касс)",
        note,
    ):
        return "card_to_cash"
    if op.bucket == "fop":
        return "ignore"
    if op.bucket == "card":
        return "card_in" if op.amount > 0 else "card_out"
    return "cash_in" if op.amount > 0 else "cash_out"


def is_parts_attach_line(line: dict[str, Any]) -> bool:
    """Привязка запчасти в CRM: «123956 -256 …», «123959 -427 зч», «121985 - Шлейфы…, 2000»."""
    if str(line.get("action") or "") != "cash_out":
        return False
    order_id = line.get("order_id")
    if not order_id:
        return False
    if line.get("is_breakdown_total"):
        return False
    # позиции под итогом ЗЧ уже учтены в кассе; в CRM тоже привязываем каждую
    raw = (line.get("raw") or line.get("note") or "").strip()
    core = ZCH_LINE_PREFIX.sub("", raw).strip()
    oid = re.escape(str(order_id))
    n = core.lower().replace("ё", "е")
    if re.search(r"(^|\s)(зп|зарплат\w*)(\s|$)", n):
        return False
    # «123956 -256 елемент пельтье» / «123959 -427 зч»
    if re.match(rf"^{oid}\s*[-−–]\s*\d+(?:[.,]\d+)?\b", core):
        return True
    # «121985 - Шлейфы , датчики, 2000» / «122114 - помпа - 1500»
    if re.match(
        rf"^{oid}\s*[-−–]\s*.+\s*[-−–]\s*\d+(?:[.,]\d+)?\s*$",
        core,
    ):
        return True
    if re.match(rf"^{oid}\s*[-−–]\s*.+,\s*\d+(?:[.,]\d+)?\s*$", core):
        return True
    return False


def _loose_amount_from_text(text: str) -> float | None:
    """Best-effort amount for unrecognized lines (for the interactive editor)."""
    m = re.search(
        rf"(?<!\d)([+\-−–])\s*({MONEY_NUM})",
        text or "",
    )
    if m:
        val = parse_money(m.group(2))
        if val is None:
            return None
        return (-abs(val)) if _norm_sign(m.group(1)) == "-" else abs(val)
    m = re.search(rf"(?<!\d)({MONEY_NUM})\s*(?:грн|uah|₴)?", text or "", re.I)
    if m:
        return parse_money(m.group(1))
    return None


def _guess_unrecognized_action(raw: str, amount: float | None) -> str:
    """Narrative / explanatory lines stay ignored until the user picks an action."""
    n = (raw or "").lower().replace("ё", "е")
    if (
        OPENING_CASH.search(raw or "")
        or OPENING_CARD.search(raw or "")
        or CASH_FACT.search(raw or "")
    ):
        return "ignore"
    if amount is None or abs(amount) < 1e-9:
        return "ignore"
    if re.search(
        r"спустил\w*\s+сверху|остальное\s+забрал|рассчитается|"
        r"сегодня\s+\w+\s+расчет|пояснен|комментар|"
        r"^>\s*|спілкувал|в\s+лс\b",
        n,
    ):
        return "ignore"
    return "cash_out" if amount < 0 else "cash_in"


def _apply_widget_line(cash: float, card: float, line: dict[str, Any]) -> tuple[float, float]:
    a = abs(float(line.get("amount") or 0))
    action = str(line.get("action") or "ignore")
    if action == "cash_out":
        cash -= a
    elif action == "cash_in":
        cash += a
    elif action == "card_out":
        card -= a
    elif action == "card_in":
        card += a
    elif action == "cash_to_card":
        cash -= a
        card += a
    elif action == "card_to_cash":
        card -= a
        cash += a
    return cash, card


def _enrich_checkpoint_lines(
    lines: list[dict[str, Any]],
    *,
    opening_cash: float,
    opening_card: float,
) -> None:
    cash = float(opening_cash)
    card = float(opening_card)
    for line in lines:
        cp = line.get("checkpoint") or {}
        if line.get("is_checkpoint"):
            line["calc_cash"] = cash
            line["calc_card"] = card
            if "written_cash" in cp:
                wc = float(cp["written_cash"])
                line["cash_match"] = abs(cash - wc) <= 1.0
            if "written_card" in cp:
                wk = float(cp["written_card"])
                line["card_match"] = abs(card - wk) <= 1.0
            continue
        cash, card = _apply_widget_line(cash, card, line)


def _totals_from_widget_lines(
    opening_cash: float,
    opening_card: float,
    lines: list[dict[str, Any]],
) -> tuple[float, float]:
    cash = float(opening_cash)
    card = float(opening_card)
    for line in lines:
        if line.get("is_checkpoint"):
            continue
        cash, card = _apply_widget_line(cash, card, line)
    return cash, card


CJ_ACTIONS = [
    {"id": "cash_in", "label": "в кассу"},
    {"id": "cash_out", "label": "из кассы"},
    {"id": "card_in", "label": "в карту"},
    {"id": "card_out", "label": "из карты"},
    {"id": "cash_to_card", "label": "из кассы в карту"},
    {"id": "card_to_cash", "label": "из карты в кассу"},
    {"id": "ignore", "label": "игнорировать транзакцию"},
]


def _build_cash_journal_widget(result: JournalResult) -> dict[str, Any]:
    lines: list[dict[str, Any]] = []
    order = result.line_order
    if not order:
        # fallback: старое поведение
        order = [("op", i) for i in range(len(result.operations))] + [
            ("unrec", i) for i in range(len(result.unrecognized))
        ]

    for kind, idx in order:
        if kind == "op":
            if idx < 0 or idx >= len(result.operations):
                continue
            op = result.operations[idx]
            line_op: dict[str, Any] = {
                "id": f"op-{idx}",
                "raw": op.raw or op.note,
                "note": op.note,
                "order_id": op.order_id,
                "amount": abs(float(op.amount)),
                "action": _guess_action(op),
                "source": "parser",
            }
            if op.kind == "spare_item" or op.breakdown_of:
                line_op["is_breakdown"] = True
                if op.breakdown_of:
                    line_op["breakdown_of"] = op.breakdown_of
            lines.append(line_op)
        elif kind == "bd":
            if idx < 0 or idx >= len(result.skipped_breakdown):
                continue
            op = result.skipped_breakdown[idx]
            is_total = op.kind == "breakdown_total"
            lines.append(
                {
                    "id": f"bd-{idx}",
                    "raw": op.raw or op.note,
                    "note": op.note,
                    "order_id": op.order_id,
                    "amount": abs(float(op.amount)),
                    "action": "ignore",
                    "source": "breakdown",
                    "is_breakdown": True,
                    "is_breakdown_total": is_total,
                    "breakdown_of": op.breakdown_of,
                }
            )
        elif kind == "unrec":
            if idx < 0 or idx >= len(result.unrecognized):
                continue
            raw = result.unrecognized[idx]
            amt = _loose_amount_from_text(raw)
            cp = _parse_balance_checkpoint(raw)
            line: dict[str, Any] = {
                "id": f"u-{idx}",
                "raw": raw,
                "note": raw,
                "order_id": None if cp else _extract_order(raw),
                "amount": abs(float(amt)) if amt is not None else 0.0,
                "action": _guess_unrecognized_action(raw, amt),
                "source": "unrecognized",
                "is_quote": _is_quote_line(raw),
            }
            if cp:
                line["is_checkpoint"] = True
                line["action"] = "ignore"
                line["checkpoint"] = cp
                if "written_cash" in cp:
                    line["written_cash"] = cp["written_cash"]
                if "written_card" in cp:
                    line["written_card"] = cp["written_card"]
            lines.append(line)

    _enrich_checkpoint_lines(
        lines,
        opening_cash=result.opening_cash,
        opening_card=result.opening_card,
    )
    closing_cash, closing_card = _totals_from_widget_lines(
        result.opening_cash, result.opening_card, lines
    )
    return {
        "title": "Сведение кассы",
        "opening_cash": result.opening_cash,
        "opening_card": result.opening_card,
        "opening_fop": result.opening_fop,
        "closing_cash": closing_cash,
        "closing_card": closing_card,
        "actions": list(CJ_ACTIONS),
        "lines": lines,
    }


def reconcile_cash_journal(
    text: str,
    *,
    opening_cash: float | None = None,
    opening_card: float | None = None,
    opening_fop: float | None = None,
) -> dict[str, Any]:
    """Parse chat journal → interactive cash_journal widget (code-only)."""
    result = parse_journal(
        text,
        opening_cash=opening_cash,
        opening_card=opening_card,
        opening_fop=opening_fop,
    )
    data = result.to_dict()
    widget = _build_cash_journal_widget(result)
    closing_cash = float(widget["closing_cash"])
    closing_card = float(widget["closing_card"])
    result.closing_cash = closing_cash
    result.closing_card = closing_card
    note = (
        "Разбор кодом готов. Итоги: closing_cash / closing_card "
        "(совпадают с блоком UI). В ответе бери ТОЛЬКО эти цифры; "
        "операции не перечисляй — правятся кнопками в UI. "
        "Не путать с gincore_cashbox_balance."
    )

    return {
        "ok": True,
        "method": "cash_journal_reconcile",
        "needs_ai_review": False,
        "note": note,
        **data,
        "closing_cash": closing_cash,
        "closing_card": closing_card,
        "closing_fop": result.closing_fop,
        "cash_journal": widget,
        "table": None,
        "tables": [],
    }
