"""КПД филиалов: приёмки, вал/чист. прибыль, коэффициент возврата из Gincore."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable

from bs4 import BeautifulSoup

from modules.gincore.client import (
    GincoreClient,
    GincoreError,
    month_bounds,
    parse_money,
    to_gincore_date,
)

# Категории транзакций как в сохранённых фильтрах CRM (без ct — достаточно cg).
PNL_CATEGORIES = (
    "1,2,3,4,5,7,8,9,12,14,15,16,17,18,20,21,22,23,24,51,25,26,27,29,"
    "31,32,33,34,35,37,38,39,40,41,42,43,28,44,45,46,47,49,50,"
    "1000,1007,1014,1016"
)

# Отказ от ремонта (статусы из фильтра CRM).
REFUSAL_STATUSES = "15,20,25,56,60,64"

BRANCHES: list[dict[str, Any]] = [
    {
        "id": "karetn",
        "title": "Каретный",
        "crm_branch_id": 1,
        "dep_accept": "1-a",
        "cashboxes": "78-f,78-t",
        "color": "#0f6e56",
    },
    {
        "id": "seged",
        "title": "Сегедская",
        "crm_branch_id": 13,
        "dep_accept": "13-a",
        "cashboxes": "13-f,13-t,42-f,42-t",
        "color": "#1a5f8a",
    },
    {
        "id": "levitan",
        "title": "Левитан",
        "crm_branch_id": 31,
        "dep_accept": "31-a",
        "cashboxes": "67-f,67-t",
        "color": "#8a4b1a",
    },
]

BRANCH_BY_ID = {b["id"]: b for b in BRANCHES}
BRANCH_BY_CRM = {int(b["crm_branch_id"]): b for b in BRANCHES}


def months_ytd(year: int | None = None, *, today: date | None = None) -> list[tuple[int, int]]:
    """(year, month) с января по текущий месяц включительно."""
    today = today or date.today()
    y = year or today.year
    end_m = today.month if y == today.year else 12
    if y > today.year:
        return []
    return [(y, m) for m in range(1, end_m + 1)]


def parse_branch_chart(html: str) -> dict[str, Any]:
    """Достать labels/data из dashboard.branchChart.initChart({...})."""
    m = re.search(
        r"dashboard\.branchChart\.initChart\((\{.*?\})\);",
        html,
        re.S,
    )
    if not m:
        raise GincoreError("На дашборде нет данных графика филиалов (branchChart)")
    try:
        payload = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise GincoreError("Не удалось разобрать JSON графика филиалов") from exc
    labels = [str(x) for x in (payload.get("labels") or [])]
    raw_data = payload.get("data") or {}
    by_crm: dict[int, list[int]] = {}
    for key, series in raw_data.items():
        try:
            bid = int(key)
        except (TypeError, ValueError):
            continue
        by_crm[bid] = [int(v or 0) for v in (series or [])]
    return {"labels": labels, "by_crm": by_crm, "raw": payload}


def label_to_year_month(label: str) -> tuple[int, int] | None:
    """'01.26' → (2026, 1)."""
    m = re.match(r"^(\d{2})\.(\d{2})$", str(label or "").strip())
    if not m:
        return None
    month = int(m.group(1))
    year = 2000 + int(m.group(2))
    if month < 1 or month > 12:
        return None
    return year, month


def acceptances_index(chart: dict[str, Any]) -> dict[tuple[int, int], dict[str, int]]:
    """(year, month) → {branch_id: acceptances}."""
    labels = chart.get("labels") or []
    by_crm: dict[int, list[int]] = chart.get("by_crm") or {}
    out: dict[tuple[int, int], dict[str, int]] = {}
    for i, lab in enumerate(labels):
        ym = label_to_year_month(lab)
        if not ym:
            continue
        row: dict[str, int] = {}
        for crm_id, branch in BRANCH_BY_CRM.items():
            series = by_crm.get(crm_id) or []
            row[branch["id"]] = int(series[i]) if i < len(series) else 0
        out[ym] = row
    return out


def parse_pnl_tfoot(html: str) -> dict[str, float | None]:
    """tfoot/tr[3]: td[2]=чистая, td[3]=валовая (xpath 1-based)."""
    soup = BeautifulSoup(html or "", "lxml")
    tfoot = soup.select_one("tfoot")
    if not tfoot:
        return {"net_profit": None, "gross_profit": None, "expense": None}
    rows = tfoot.select("tr")
    if len(rows) < 3:
        return {"net_profit": None, "gross_profit": None, "expense": None}
    cells = rows[2].select("td")
    net = parse_money(cells[1].get_text(" ", strip=True)) if len(cells) > 1 else None
    gross = parse_money(cells[2].get_text(" ", strip=True)) if len(cells) > 2 else None
    expense = parse_money(cells[3].get_text(" ", strip=True)) if len(cells) > 3 else None
    return {"net_profit": net, "gross_profit": gross, "expense": expense}


def return_rate(refusals: int | None, acceptances: int | None) -> float | None:
    if acceptances is None or refusals is None:
        return None
    if acceptances <= 0:
        return None
    return round(float(refusals) / float(acceptances), 4)


ClientFactory = Callable[[], Awaitable[GincoreClient]]


class BranchKpiService:
    def __init__(
        self,
        db: Any,
        gincore_client_factory: ClientFactory,
    ) -> None:
        self.db = db
        self._client_factory = gincore_client_factory
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    async def get_sync_state(self) -> dict[str, Any]:
        return await self.db.branch_kpi_get_sync_state()

    async def get_stats(self) -> dict[str, Any]:
        rows = await self.db.branch_kpi_list_months()
        sync = await self.get_sync_state()
        return {
            "ok": True,
            "sync": sync,
            "branches": [
                {
                    "id": b["id"],
                    "title": b["title"],
                    "color": b["color"],
                    "crm_branch_id": b["crm_branch_id"],
                }
                for b in BRANCHES
            ],
            "months": rows,
            "charts": build_branch_kpi_charts(rows),
        }

    async def start_sync(self) -> dict[str, Any]:
        async with self._lock:
            state = await self.get_sync_state()
            if state.get("status") == "running":
                return {"ok": True, "sync": state, "started": False}
            await self.db.branch_kpi_set_sync_state(
                status="running",
                message="Старт…",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at=None,
                done=0,
                total=0,
            )
            self._task = asyncio.create_task(self._run_sync())
            return {
                "ok": True,
                "sync": await self.get_sync_state(),
                "started": True,
            }

    async def _run_sync(self) -> None:
        client: GincoreClient | None = None
        started = datetime.now(timezone.utc).isoformat()
        try:
            await self.db.branch_kpi_set_sync_state(
                status="running",
                message="Загрузка приёмок с дашборда…",
                started_at=started,
                finished_at=None,
                total=0,
                done=0,
            )
            client = await self._client_factory()
            today = date.today()
            year = today.year
            months = months_ytd(year, today=today)
            ds = f"{year}-01-01"
            de = today.isoformat()

            dash = await client.request("GET", f"/?ds={ds}&de={de}&month=")
            chart = parse_branch_chart(dash.text)
            acc_map = acceptances_index(chart)

            total = len(months) * len(BRANCHES)
            await self.db.branch_kpi_set_sync_state(total=total, done=0)

            rows: list[dict[str, Any]] = []
            done = 0
            for y, m in months:
                df, dt = month_bounds(y, m)
                if date.fromisoformat(dt) > today:
                    dt = today.isoformat()
                month_acc = acc_map.get((y, m)) or {}
                for branch in BRANCHES:
                    bid = branch["id"]
                    acceptances = int(month_acc.get(bid) or 0)
                    pnl = await self._fetch_pnl(client, branch["cashboxes"], df, dt)
                    refusals = await self._fetch_refusals(
                        client, branch["dep_accept"], df, dt
                    )
                    rate = return_rate(refusals, acceptances)
                    rows.append(
                        {
                            "year": y,
                            "month": m,
                            "branch_id": bid,
                            "acceptances": acceptances,
                            "gross_profit": pnl.get("gross_profit"),
                            "net_profit": pnl.get("net_profit"),
                            "expense": pnl.get("expense"),
                            "refusals": refusals,
                            "return_rate": rate,
                        }
                    )
                    done += 1
                    await self.db.branch_kpi_set_sync_state(
                        done=done,
                        message=f"{branch['title']} · {m:02d}.{y}",
                    )

            await self.db.branch_kpi_replace_months(rows)
            try:
                await self.export_pages_snapshot()
                msg = f"Готово: {len(months)} мес. × {len(BRANCHES)} филиала, pages ок"
            except Exception as exc:  # noqa: BLE001
                msg = f"Готово: {len(months)} мес., экспорт Pages: {exc}"
            await self.db.branch_kpi_set_sync_state(
                status="idle",
                message=msg,
                finished_at=datetime.now(timezone.utc).isoformat(),
                done=done,
                total=total,
            )
        except Exception as exc:  # noqa: BLE001
            await self.db.branch_kpi_set_sync_state(
                status="error",
                message=str(exc),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        finally:
            if client is not None:
                await client.aclose()

    async def _fetch_pnl(
        self,
        client: GincoreClient,
        cashboxes: str,
        date_from: str,
        date_to: str,
    ) -> dict[str, float | None]:
        query = {
            "df": to_gincore_date(date_from),
            "dt": to_gincore_date(date_to),
            "cb": cashboxes,
            "cg": PNL_CATEGORIES,
            "grp": "1",
        }
        html = await client._tab_html(
            "accountings_transactions_cashboxes", query=query
        )
        return parse_pnl_tfoot(html)

    async def _fetch_refusals(
        self,
        client: GincoreClient,
        dep: str,
        date_from: str,
        date_to: str,
    ) -> int:
        meta = await client._repair_orders_count(
            crm_params={
                "df": to_gincore_date(date_from),
                "dt": to_gincore_date(date_to),
                "dep": dep,
                "st": REFUSAL_STATUSES,
            }
        )
        return int(meta.get("count") or 0)

    async def export_pages_snapshot(self) -> dict[str, Any]:
        from modules.gincore.branch_kpi_export import (
            build_branch_kpi_pages_payload,
            write_branch_kpi_pages_json,
        )

        rows = await self.db.branch_kpi_list_months()
        payload = build_branch_kpi_pages_payload(rows)
        path = write_branch_kpi_pages_json(payload)
        return {"ok": True, "path": str(path), "months": len(rows)}


def build_branch_kpi_charts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Chart.js-подобные серии для сравнения филиалов по месяцам."""
    keys = sorted({(int(r["year"]), int(r["month"])) for r in rows})
    labels = [f"{m:02d}.{str(y)[2:]}" for y, m in keys]
    by_key: dict[tuple[int, int, str], dict[str, Any]] = {
        (int(r["year"]), int(r["month"]), str(r["branch_id"])): r for r in rows
    }

    def series(field: str, *, pct: bool = False) -> list[dict[str, Any]]:
        out = []
        for b in BRANCHES:
            data = []
            for y, m in keys:
                cell = by_key.get((y, m, b["id"])) or {}
                val = cell.get(field)
                if val is None:
                    data.append(None)
                elif pct:
                    data.append(round(float(val) * 100, 2))
                else:
                    data.append(val)
            out.append(
                {
                    "label": b["title"],
                    "branch_id": b["id"],
                    "color": b["color"],
                    "data": data,
                }
            )
        return out

    return {
        "labels": labels,
        "acceptances": series("acceptances"),
        "gross_profit": series("gross_profit"),
        "net_profit": series("net_profit"),
        "return_rate_pct": series("return_rate", pct=True),
    }
