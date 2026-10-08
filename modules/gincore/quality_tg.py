"""Сокращённый анализ качества → блоки для Telegram (≤1 сообщение на блок)."""

from __future__ import annotations

import html
from typing import Any

# Запас к лимиту Telegram 4096
TG_BLOCK_MAX = 3900
TG_URGENT_TOP = 10


def _esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=False)


def _num(v: Any, digits: int = 1) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if digits == 0:
        return str(int(round(n)))
    return f"{n:.{digits}f}"


def _delta(key: str, v: Any) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if n > 0 else ""
    unit = " дн" if "days" in key else ""
    return f"{sign}{n:.1f}{unit}"


def _sev(s: str | None) -> str:
    m = {
        "critical": "крит.",
        "high": "высок.",
        "medium": "средн.",
        "watch": "набл.",
    }
    return m.get(s or "", s or "—")


def _sev_emoji(s: str | None) -> str:
    if s == "critical":
        return "🔴"
    if s == "high":
        return "🟠"
    if s == "medium":
        return "🟡"
    return "⚪"


def _clip(text: str, max_len: int = TG_BLOCK_MAX) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _pack_lines(header: str, lines: list[str], max_len: int = TG_BLOCK_MAX) -> list[str]:
    """Собрать строки в одно или несколько сообщений с одним заголовком."""
    if not lines:
        return [_clip(header)]
    blocks: list[str] = []
    part = 1
    buf = header
    for line in lines:
        candidate = f"{buf}\n{line}" if buf else line
        if len(candidate) <= max_len:
            buf = candidate
            continue
        if buf.strip() and buf.strip() != header.strip():
            blocks.append(_clip(buf))
            part += 1
            h = f"{header} (продолжение {part})"
            buf = f"{h}\n{line}"
            if len(buf) > max_len:
                blocks.append(_clip(buf))
                part += 1
                buf = f"{header} (продолжение {part})"
        else:
            blocks.append(_clip(f"{header}\n{line}"))
            part += 1
            buf = f"{header} (продолжение {part})"
    if buf.strip() and buf.strip() != header.strip():
        blocks.append(_clip(buf))
    elif not blocks:
        blocks.append(_clip(header))
    return blocks


def _order_link(oid: str, url: str | None, base_url: str | None) -> str:
    oid_s = str(oid or "?").strip() or "?"
    href = (url or "").strip()
    if not href and base_url and oid_s != "?":
        href = f"{base_url.rstrip('/')}/orders/{oid_s}"
    label = f"№{_esc(oid_s)}"
    if href:
        return f'<a href="{html.escape(href, quote=True)}">{label}</a>'
    return f"<b>{label}</b>"


def _format_urgent_card(i: int, u: dict[str, Any], *, base_url: str | None) -> str:
    oid = str(u.get("order_id") or "?")
    link = _order_link(oid, u.get("url"), base_url)
    sev = u.get("severity")
    kpi = u.get("order_kpi")
    days = u.get("total_days")
    eng = _esc(u.get("engineer") or "—")
    status = _esc(u.get("status") or "—")
    device = _esc((u.get("device") or "")[:60]) if u.get("device") else ""

    reasons = [str(r).strip() for r in (u.get("reasons") or []) if str(r).strip()][:4]
    actions = [str(a).strip() for a in (u.get("actions") or []) if str(a).strip()][:3]

    lines = [
        f"{_sev_emoji(sev)} <b>{i}.</b> {link} · <b>{_esc(_sev(sev))}</b>",
        f"KPI <b>{_esc(kpi if kpi is not None else '—')}</b> · "
        f"<b>{_esc(days if days is not None else '—')}</b> дн · {eng}",
        f"Статус: <b>{status}</b>" + (f" · {device}" if device else ""),
    ]
    if reasons:
        lines.append("<b>Почему</b>")
        for r in reasons:
            lines.append(f"• {_esc(r)}")
    if actions:
        lines.append("<b>Сейчас</b>")
        for a in actions:
            lines.append(f"→ {_esc(a)}")
    return "\n".join(lines)


def format_quality_analysis_tg_blocks(
    analysis: dict[str, Any],
    *,
    order_base_url: str | None = None,
) -> list[dict[str, str]]:
    """Блоки для TG: [{text, parse_mode}]. Каждый блок ≤ лимита сообщения."""
    if not analysis or not analysis.get("orders_count"):
        return [{"text": "Качество: анализ пуст. Обновите из CRM.", "parse_mode": "HTML"}]

    health = analysis.get("health") or {}
    portfolio = analysis.get("portfolio") or {}
    bands = portfolio.get("kpi_bands") or {}
    dyn = analysis.get("dynamics") or {}
    deltas = dyn.get("deltas") or {}
    masters = analysis.get("masters") or {}
    out: list[dict[str, str]] = []

    def add(text: str, *, html_mode: bool = True) -> None:
        t = _clip(text)
        if t:
            out.append({"text": t, "parse_mode": "HTML" if html_mode else ""})

    gen = str(analysis.get("generated_at") or "")[:19].replace("T", " ")
    urgent_total = analysis.get("urgent_total")
    if urgent_total is None:
        urgent_total = len(analysis.get("urgent") or [])

    add(
        "\n".join(
            [
                "📊 <b>Качество · текущий анализ</b>",
                f"Здоровье: <b>{_esc(health.get('score', '—'))}</b>/100 "
                f"({_esc(health.get('label') or '—')})",
                _esc(analysis.get("headline") or ""),
                _esc(health.get("summary") or ""),
                f"Собран: {_esc(gen or '—')} · заказов {_esc(analysis.get('orders_count'))} · "
                f"срочных {_esc(urgent_total)}",
            ]
        )
    )

    add(
        "\n".join(
            [
                "📦 <b>Портфель сейчас</b>",
                f"KPI <b>{_esc(_num(portfolio.get('avg_order_kpi')))}</b> · "
                f"Звонки <b>{_esc(_num(portfolio.get('avg_calls_kpi')))}</b> · "
                f"Дораб. <b>{_esc(_num(portfolio.get('avg_rework_kpi')))}</b>",
                f"Сроки: всего <b>{_esc(_num(portfolio.get('avg_total_days')))}</b> дн · "
                f"до мастера <b>{_esc(_num(portfolio.get('avg_wait_master_days')))}</b> · "
                f"до диагн. <b>{_esc(_num(portfolio.get('avg_diag_days')))}</b>",
                f"KPI ≥70: {_esc(bands.get('good', 0))} · 40–69: {_esc(bands.get('mid', 0))} · "
                f"&lt;40: {_esc(bands.get('bad', 0))}",
                f"Доработок: {_esc(portfolio.get('rework_orders', 0))} · "
                f"≥45 дн: {_esc(portfolio.get('long_orders_45d', 0))} · "
                f"флаги мен.: {_esc(portfolio.get('manager_flags', 0))} · "
                f"слабые звонки: {_esc(portfolio.get('weak_calls', 0))} · "
                f"без мастера: {_esc(portfolio.get('no_master_count', 0))}",
            ]
        )
    )

    dyn_lines = [
        "📈 <b>Динамика</b>",
        f"Снимков: {_esc(dyn.get('points', 0))}"
        + (f" · текущий {_esc(dyn.get('curr_day'))}" if dyn.get("curr_day") else "")
        + (f" · Δ к {_esc(dyn.get('prev_day'))}" if dyn.get("prev_day") else ""),
    ]
    for key, title in (
        ("avg_order_kpi", "KPI"),
        ("avg_calls_kpi", "Звонки"),
        ("avg_rework_kpi", "Дораб."),
        ("avg_total_days", "Всего дн"),
        ("avg_wait_master_days", "До мастера"),
        ("avg_diag_days", "До диагн."),
    ):
        dyn_lines.append(f"{_esc(title)}: <b>{_esc(_delta(key, deltas.get(key)))}</b>")
    for n in dyn.get("narrative") or []:
        dyn_lines.append(f"• {_esc(n)}")
    add("\n".join(dyn_lines))

    # Все зоны внимания — одно сообщение
    focuses = analysis.get("focus_areas") or []
    focus_lines = ["🎯 <b>Зоны внимания</b>"]
    if not focuses:
        focus_lines.append("Явных зон не выделено.")
    else:
        for f in focuses:
            focus_lines.append("")
            focus_lines.append(
                f"{_sev_emoji(f.get('severity'))} <b>{_esc(f.get('title') or 'Фокус')}</b> "
                f"[{_esc(_sev(f.get('severity')))}]"
            )
            detail = str(f.get("detail") or "").strip()
            if detail:
                focus_lines.append(_esc(detail))
            for a in f.get("actions") or []:
                focus_lines.append(f"→ {_esc(a)}")
    for chunk in _pack_lines(focus_lines[0], focus_lines[1:]):
        add(chunk)

    pos_lines = ["✅ <b>Что хорошо</b>"]
    for p in analysis.get("positives") or []:
        pos_lines.append(f"• {_esc(p)}")
    if not analysis.get("positives"):
        pos_lines.append("• —")
    pos_lines.append("")
    pos_lines.append("👷 <b>Лидеры по KPI</b>")
    best = masters.get("best") or []
    if best:
        for m in best[:5]:
            pos_lines.append(
                f"• <b>{_esc(m.get('name'))}</b>: KPI {_esc(m.get('avg_kpi', '—'))}, "
                f"{_esc(m.get('count', 0))} зак., дораб. {_esc(m.get('rework_orders', 0))}"
            )
    else:
        pos_lines.append("• —")
    pos_lines.append("")
    pos_lines.append("⚠ <b>Слабее (от 3+ зак.)</b>")
    worst = masters.get("worst") or []
    if worst:
        for m in worst[:5]:
            pos_lines.append(
                f"• <b>{_esc(m.get('name'))}</b>: KPI {_esc(m.get('avg_kpi', '—'))}, "
                f"{_esc(m.get('count', 0))} зак., дораб. {_esc(m.get('rework_orders', 0))}"
            )
    else:
        pos_lines.append("• —")
    for chunk in _pack_lines(pos_lines[0], pos_lines[1:]):
        add(chunk)

    urgent_all = list(analysis.get("urgent") or [])
    urgent = urgent_all[:TG_URGENT_TOP]
    if not urgent:
        add("🚨 <b>Срочные квитанции</b>\nСейчас нет.")
    else:
        header = (
            f"🚨 <b>Срочные ({_esc(urgent_total)}), топ {len(urgent)}</b>\n"
            f"<i>Самые критичные квитанции — ссылка открывает CRM</i>"
        )
        cards = [
            _format_urgent_card(i, u, base_url=order_base_url)
            for i, u in enumerate(urgent, 1)
        ]
        # Карточки разделяем пустой строкой; пакуем если не влезает
        lines: list[str] = []
        for card in cards:
            if lines:
                lines.append("")  # spacer between cards
            lines.append(card)
        for chunk in _pack_lines(header, lines):
            add(chunk)

    return out
