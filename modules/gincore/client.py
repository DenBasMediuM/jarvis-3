from __future__ import annotations

import asyncio
import re
from calendar import monthrange
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Jarvis/0.1"
)

# Safety limits: keep CRM crawling bounded and LLM payloads small.
MAX_PAGES = 40  # 40 * ~30 rows ≈ 1200 transactions per query
PAGE_CONCURRENCY = 4
SAMPLE_ROWS = 15

# Spare-parts attach from cash journal («123956 -256 …»).
PARTS_ATTACH_PRODUCT_TITLE = "Запчасти."
PARTS_ATTACH_SUPPLIER_NAME = "prom.ua"
PARTS_ATTACH_STATUS_ID = 5  # «В процессе ремонта»
PARTS_ATTACH_STATUS_NAME = "В процессе ремонта"
PARTS_ATTACH_WAREHOUSE_LOCAL = 1


class GincoreError(Exception):
    pass


def month_bounds(year: int, month: int) -> tuple[str, str]:
    last = monthrange(year, month)[1]
    return date(year, month, 1).isoformat(), date(year, month, last).isoformat()


def year_bounds(year: int, *, clip_to_today: bool = False) -> tuple[str, str]:
    start, end = f"{year}-01-01", f"{year}-12-31"
    if clip_to_today:
        today = date.today()
        if year == today.year:
            end = today.isoformat()
        elif year > today.year:
            end = today.isoformat()
    return start, end


def months_in_range(date_from: str, date_to: str) -> list[tuple[int, int, str, str]]:
    """List (year, month, clipped_from, clipped_to) for each month overlapping the range."""
    start = datetime.strptime(date_from, "%Y-%m-%d").date()
    end = datetime.strptime(date_to, "%Y-%m-%d").date()
    if end < start:
        start, end = end, start
    today = date.today()
    if end > today:
        end = today
    out: list[tuple[int, int, str, str]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        first, last = month_bounds(y, m)
        df = max(start, datetime.strptime(first, "%Y-%m-%d").date())
        dt = min(end, datetime.strptime(last, "%Y-%m-%d").date())
        out.append((y, m, df.isoformat(), dt.isoformat()))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return out


def to_gincore_date(iso: str) -> str:
    """YYYY-MM-DD -> DD.MM.YYYY"""
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d.%m.%Y")


def parse_money(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).replace("\xa0", " ").replace(" ", "")
    s = s.replace("₴", "").replace("UAH", "").replace("грн", "")
    m = re.search(r"-?\d+(?:[.,]\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


RU_MONTHS = {
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "май": 5,
    "мая": 5,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
}


def parse_gincore_date(raw: str, *, default_year: int | None = None) -> date | None:
    """Parse CRM dates: 'Сегодня', '4 Авг.', '18 Фев.', '01.08.2026'."""
    if not raw:
        return None
    text = str(raw).replace("\xa0", " ").strip()
    low = text.lower()
    if low in {"сегодня", "today"}:
        return date.today()
    if low in {"вчера", "yesterday"}:
        return date.fromordinal(date.today().toordinal() - 1)

    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None

    m = re.match(r"^(\d{1,2})\s+([А-Яа-яA-Za-z]+)\.?(?:\s+(\d{4}))?$", text)
    if m:
        day = int(m.group(1))
        mon_raw = m.group(2).lower()[:3]
        year = int(m.group(3)) if m.group(3) else (default_year or date.today().year)
        month = RU_MONTHS.get(mon_raw)
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                return None
    return None


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


class GincoreClient:
    """Session client for Gincore CRM via login + tab-load/filter APIs."""

    def __init__(self, base_url: str, login: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.login_name = login
        self.password = password
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ru-RU,ru;q=0.9"},
            follow_redirects=True,
            timeout=60.0,
            trust_env=False,
        )
        self._logged_in = False
        self._categories: list[dict[str, str]] | None = None
        self._contractors: list[dict[str, str]] | None = None
        self._login_lock = asyncio.Lock()
        self._repair_staff: dict[str, list[dict[str, str]]] | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "GincoreClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    def _extract_csrf(self, html: str) -> str | None:
        soup = BeautifulSoup(html, "lxml")
        token = soup.find("input", {"name": "_token"})
        if token and token.get("value"):
            return str(token["value"])
        meta = soup.find("meta", {"name": "csrf-token"})
        if meta and meta.get("content"):
            return str(meta["content"])
        return None

    async def login(self) -> dict[str, Any]:
        form_resp = await self._client.get("/auth/login_form")
        form_resp.raise_for_status()
        token = self._extract_csrf(form_resp.text)
        if not token:
            raise GincoreError("Не удалось получить CSRF-токен формы входа Gincore")

        resp = await self._client.post(
            "/auth/login",
            data={"_token": token, "login": self.login_name, "password": self.password},
            headers={"Referer": urljoin(self.base_url + "/", "auth/login_form")},
        )
        if "login_form" in str(resp.url):
            raise GincoreError("Неверный логин или пароль")
        self._logged_in = True
        title = BeautifulSoup(resp.text, "lxml").title
        return {
            "ok": True,
            "url": str(resp.url),
            "title": title.get_text(strip=True) if title else None,
        }

    async def ensure_login(self) -> None:
        if self._logged_in:
            return
        async with self._login_lock:
            if not self._logged_in:
                await self.login()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | list[tuple[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        await self.ensure_login()
        resp = await self._client.request(
            method.upper(), path, params=params, data=data, headers=headers
        )
        if "login_form" in str(resp.url):
            async with self._login_lock:
                self._logged_in = False
                await self.login()
            resp = await self._client.request(
                method.upper(), path, params=params, data=data, headers=headers
            )
        return resp

    async def _tab_html(self, tab: str, *, query: dict[str, Any] | None = None) -> str:
        q = {"act": "tab-load", **(query or {})}
        # Flatten list values for categories etc. handled by caller via urlencode
        qs = urlencode(q, doseq=True)
        hash_name = {
            "accountings_cashboxes": "#cashboxes",
            "accountings_transactions": "#transactions",
            "accountings_transactions_cashboxes": "#transactions-cashboxes",
        }.get(tab, "#")
        resp = await self.request(
            "POST",
            f"/accountings/ajax?{qs}",
            data={"tab": tab, "hashs": hash_name},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": f"{self.base_url}/accountings?{qs}{hash_name}",
            },
        )
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype:
            payload = resp.json()
            if payload.get("state") is False:
                raise GincoreError(payload.get("message") or "Ошибка tab-load")
            return str(payload.get("html") or "")
        return resp.text

    async def list_cashboxes(self) -> list[dict[str, Any]]:
        html = await self._tab_html("accountings_cashboxes")
        soup = BeautifulSoup(html, "lxml")
        result: list[dict[str, Any]] = []
        for table in soup.select(".cashboxes-table"):
            cid = table.get("data-id")
            title_el = table.select_one(".cashbox-title-td, .js-title")
            title = title_el.get_text(" ", strip=True) if title_el else ""
            balances: list[dict[str, Any]] = []
            # Prefer explicit balance cells
            text = table.get_text("\n", strip=True)
            for m in re.finditer(
                r"([-+]?\d[\d\s]*(?:[.,]\d+)?)\s*(UAH|USD|EUR|грн)?",
                text,
                re.I,
            ):
                amount = parse_money(m.group(1))
                if amount is None:
                    continue
                currency = (m.group(2) or "UAH").upper().replace("ГРН", "UAH")
                balances.append({"amount": amount, "currency": currency})
                if len(balances) >= 3:
                    break
            # Fallback: first money-looking lines after title
            if not balances:
                for line in text.split("\n"):
                    amount = parse_money(line)
                    if amount is not None and any(ch.isdigit() for ch in line):
                        balances.append({"amount": amount, "currency": "UAH"})
                        break
            result.append(
                {
                    "id": cid,
                    "name": title,
                    "balances": balances,
                    "total_uah": next(
                        (b["amount"] for b in balances if b["currency"] == "UAH"),
                        balances[0]["amount"] if balances else None,
                    ),
                }
            )
        return result

    async def cashbox_balance(self, name_query: str) -> dict[str, Any]:
        boxes = await self.list_cashboxes()
        q = name_query.lower().strip()
        matched = [b for b in boxes if q in (b.get("name") or "").lower()]
        return {
            "query": name_query,
            "matched": matched,
            "all_names": [b["name"] for b in boxes],
        }

    def _ajax_headers(self, referer: str) -> dict[str, str]:
        return {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": referer,
        }

    async def fetch_order_html(self, order_id: str | int) -> str:
        oid = str(order_id).strip()
        resp = await self.request("GET", f"/orders/{oid}")
        resp.raise_for_status()
        if "login_form" in str(resp.url):
            raise GincoreError("Сессия Gincore истекла")
        return resp.text

    @staticmethod
    def parse_order_payment(html: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        lab = soup.find(string=re.compile(r"Форма оплаты", re.I))
        panel = lab.find_parent("div", class_="panel-body") if lab else None
        if panel is None:
            btn = soup.select_one("button.js-pay-button")
            panel = btn.find_parent("div", class_="panel-body") if btn else None
        root = panel or soup

        def _val(*selectors: str) -> float | None:
            for sel in selectors:
                el = root.select_one(sel)
                if el is None:
                    continue
                amount = parse_money(el.get("value") if el.name == "input" else el.get_text())
                if amount is not None:
                    return amount
            return None

        payment_method = None
        if panel is not None:
            for r in panel.select(".row"):
                if "форма оплаты" in r.get_text(" ", strip=True).lower():
                    text = r.get_text(" ", strip=True)
                    payment_method = re.sub(
                        r"форма оплаты\s*:?\s*", "", text, flags=re.I
                    ).strip() or None
                    break

        return {
            "payment_method": payment_method,
            "repair_cost": _val('input[name="sum"]', "#order-total"),
            "discount": _val('input[name="discount"]'),
            "total_with_discount": _val('input[name="order_sum"]', 'span.total-sum'),
            "paid": _val("#order-sum-paid", 'input[name="order-sum-paid"]'),
            "prepay": _val('input[name="prepay"]'),
            "due": _val(
                'input[name="order_sum_pay_current"]',
                'input[name="order_sum_pay"]',
                "#order_sum_pay",
            ),
        }

    @staticmethod
    def parse_order_live_feed(html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        out: list[dict[str, Any]] = []
        rows = [
            tr
            for tr in soup.select(".js-comments-table tr")
            if tr.select_one(".order-comments__body")
        ]
        for row in rows:
            date_el = row.select_one(".order-comments__date")
            author_el = row.select_one(".order-comments__author")
            body_el = row.select_one(".order-comments__body")
            date_s = date_el.get_text(" ", strip=True) if date_el else ""
            author = author_el.get_text(" ", strip=True) if author_el else ""
            body = body_el.get_text(" ", strip=True) if body_el else ""
            if not (date_s or author or body):
                continue
            out.append({"date": date_s, "author": author, "text": body})
        return out

    async def get_order_payment_preview(self, order_id: str | int) -> dict[str, Any]:
        oid = str(order_id).strip()
        html = await self.fetch_order_html(oid)
        payment = self.parse_order_payment(html)
        feed = self.parse_order_live_feed(html)
        title = BeautifulSoup(html, "lxml").title
        return {
            "ok": True,
            "order_id": oid,
            "url": f"{self.base_url}/orders/{oid}",
            "title": title.get_text(strip=True) if title else None,
            "payment": payment,
            "live_feed": feed,
        }

    async def begin_client_order_payment(
        self,
        order_id: str | int,
        amount: float,
        *,
        order_kind: str = "repair",
    ) -> dict[str, Any]:
        """Open CRM payment dialog HTML and extract cashboxes + defaults."""
        oid = str(order_id).strip()
        act = f"begin-transaction-{order_kind}-co"
        resp = await self.request(
            "POST",
            f"/accountings/ajax?act={act}",
            data={
                "client_order_id": oid,
                "b_id": "0",
                "pay_sum": f"{float(amount):g}",
            },
            headers=self._ajax_headers(f"{self.base_url}/orders/{oid}"),
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("state"):
            raise GincoreError(payload.get("message") or payload.get("msg") or "Не удалось открыть оплату")
        content = str(payload.get("content") or "")
        soup = BeautifulSoup(content, "lxml")
        cashboxes: list[dict[str, str]] = []
        selected_id = None
        for opt in soup.select('select[name="cashbox_to"] option'):
            cid = str(opt.get("value") or "").strip()
            if not cid:
                continue
            name = opt.get_text(" ", strip=True)
            item = {"id": cid, "name": name}
            cashboxes.append(item)
            if opt.has_attr("selected"):
                selected_id = cid
        if not cashboxes:
            # fallback to accounting cashboxes list
            for box in await self.list_cashboxes():
                if box.get("id") and box.get("name"):
                    cashboxes.append({"id": str(box["id"]), "name": str(box["name"])})
        currency_el = soup.select_one('input[name="cashbox_currencies_to"]')
        amount_el = soup.select_one('input[name="amount_to"]')
        return {
            "ok": True,
            "order_id": oid,
            "order_kind": order_kind,
            "cashboxes": cashboxes,
            "selected_cashbox_id": selected_id or (cashboxes[0]["id"] if cashboxes else None),
            "currency_id": (currency_el.get("value") if currency_el else None) or "3",
            "amount": parse_money(amount_el.get("value") if amount_el else None) or float(amount),
            "form_act": (
                soup.select_one('input[name="act"]').get("value")
                if soup.select_one('input[name="act"]')
                else "pay_for_repair_form"
            ),
            "transaction_type": (
                soup.select_one('input[name="transaction_type"]').get("value")
                if soup.select_one('input[name="transaction_type"]')
                else "2"
            ),
        }

    async def get_cashbox_currency_id(
        self,
        cashbox_id: str | int,
        *,
        transaction_act: str = "pay_for_repair_form",
    ) -> str:
        resp = await self.request(
            "POST",
            "/accountings/ajax?act=get-cashbox-currencies",
            data={
                "cashbox_id": str(cashbox_id),
                "transaction_act": transaction_act,
            },
            headers=self._ajax_headers(f"{self.base_url}/accountings#cashboxes"),
        )
        resp.raise_for_status()
        payload = resp.json()
        raw = payload.get("currencies") or ""
        # CRM sometimes returns HTML snippet as a JSON string
        html = str(raw)
        soup = BeautifulSoup(html, "lxml")
        selected = soup.select_one("option[selected]")
        if selected and selected.get("value"):
            return str(selected.get("value"))
        opt = soup.select_one("option[value]")
        if opt and opt.get("value"):
            return str(opt.get("value"))
        return "3"

    async def accept_client_order_payment(
        self,
        order_id: str | int,
        *,
        cashbox_id: str | int,
        amount: float,
        currency_id: str | int = "3",
        order_kind: str = "repair",
        form_act: str = "pay_for_repair_form",
        transaction_type: str = "2",
        issued: bool = False,
    ) -> dict[str, Any]:
        """POST create-transaction-repair — внести оплату клиента в выбранную кассу."""
        oid = str(order_id).strip()
        amt = f"{float(amount):.2f}".rstrip("0").rstrip(".")
        try:
            currency_id = await self.get_cashbox_currency_id(
                cashbox_id, transaction_act=str(form_act)
            )
        except Exception:
            currency_id = str(currency_id or "3")
        # httpx AsyncClient: data must be a mapping (list[tuple] → sync stream → RuntimeError)
        data = {
            "act": str(form_act),
            "transaction_type": str(transaction_type),
            "client_order_id": oid,
            "transaction_extra": "",
            "cashbox_currencies_to": str(currency_id),
            "cashbox_to": str(cashbox_id),
            "amount_without_discount": amt,
            "amount_to": amt,
        }
        if issued:
            data["issued"] = "1"
        create_act = f"create-transaction-{order_kind}"
        resp = await self.request(
            "POST",
            f"/accountings/ajax?act={create_act}",
            data=data,
            headers=self._ajax_headers(f"{self.base_url}/orders/{oid}"),
        )
        resp.raise_for_status()
        try:
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise GincoreError(f"Неожиданный ответ CRM: {resp.text[:300]}") from exc
        ok = bool(payload.get("state")) or payload.get("status_code") == 200
        if not ok:
            raise GincoreError(
                payload.get("msg") or payload.get("message") or "Ошибка внесения оплаты"
            )
        return {
            "ok": True,
            "order_id": oid,
            "cashbox_id": str(cashbox_id),
            "amount": float(amount),
            "currency_id": str(currency_id),
            "issued": issued,
            "crm": {
                "state": payload.get("state"),
                "msg": payload.get("msg") or payload.get("message"),
            },
        }

    @staticmethod
    def parse_order_status(html: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        status_input = soup.select_one('input[name="status"]')
        status_id = None
        if status_input and status_input.get("value") not in (None, ""):
            try:
                status_id = int(str(status_input.get("value")).strip())
            except ValueError:
                status_id = None
        name = None
        btn = soup.select_one(".order_status .as_button .btn-title, .order-status-cart .btn-title")
        if btn:
            name = btn.get_text(" ", strip=True) or None
        if not name and status_id is not None:
            link = soup.select_one(f'a[data-status_id="{status_id}"]')
            if link:
                name = link.get_text(" ", strip=True) or None
        return {"status_id": status_id, "status_name": name}

    async def change_order_status(
        self, order_id: str | int, status_id: int | str
    ) -> dict[str, Any]:
        oid = str(order_id).strip()
        sid = str(status_id).strip()
        resp = await self.request(
            "POST",
            f"/orders/{oid}/change-status",
            data={"status": sid},
            headers=self._ajax_headers(f"{self.base_url}/orders/{oid}"),
        )
        resp.raise_for_status()
        payload = resp.json() if resp.content else {}
        if not payload.get("state"):
            raise GincoreError(
                payload.get("message")
                or payload.get("msg")
                or f"Не удалось сменить статус заказа {oid}"
            )
        status = payload.get("status") or {}
        return {
            "ok": True,
            "order_id": oid,
            "status_id": int(status.get("status_id") or sid),
            "status_name": status.get("name"),
            "crm": payload,
        }

    async def resolve_goods_id_by_title(self, title: str) -> int:
        q = (title or "").strip()
        if not q:
            raise GincoreError("Пустое название товара")
        resp = await self.request(
            "POST",
            "/messages",
            data={"act": "global-typeahead", "table": "goods-goods", "query": q},
            headers=self._ajax_headers(f"{self.base_url}/orders"),
        )
        resp.raise_for_status()
        try:
            rows = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise GincoreError(f"Typeahead товаров: {resp.text[:200]}") from exc
        if not isinstance(rows, list) or not rows:
            raise GincoreError(f"Товар «{q}» не найден в CRM")
        exact = next(
            (r for r in rows if str(r.get("title") or "").strip() == q),
            None,
        )
        row = exact or rows[0]
        gid = row.get("id")
        if gid is None:
            raise GincoreError(f"У товара «{q}» нет id")
        return int(gid)

    async def add_order_product(
        self,
        order_id: str | int,
        product_id: int | str,
        *,
        make_order_button: bool = True,
    ) -> dict[str, Any]:
        oid = str(order_id).strip()
        data = {
            "product_id": str(product_id),
            "type": "name",
            "price_type": "1",
        }
        if make_order_button:
            data["make_order_button"] = "1"
        resp = await self.request(
            "POST",
            f"/orders/{oid}/products/add",
            data=data,
            headers=self._ajax_headers(f"{self.base_url}/orders/{oid}"),
        )
        resp.raise_for_status()
        payload = resp.json() if resp.content else {}
        if not payload.get("state"):
            raise GincoreError(
                payload.get("message")
                or payload.get("msg")
                or f"Не удалось добавить товар в заказ {oid}"
            )
        og_id = payload.get("og_id")
        if og_id is None:
            raise GincoreError("CRM не вернул og_id после добавления товара")
        return {
            "ok": True,
            "order_id": oid,
            "og_id": int(og_id),
            "goods_id": int(payload.get("goods_id") or product_id),
            "crm": payload,
        }

    async def remove_order_product(
        self, order_id: str | int, order_product_id: int | str
    ) -> dict[str, Any]:
        oid = str(order_id).strip()
        resp = await self.request(
            "POST",
            f"/orders/{oid}/products/remove",
            data={"order_product_id": str(order_product_id)},
            headers=self._ajax_headers(f"{self.base_url}/orders/{oid}"),
        )
        resp.raise_for_status()
        payload = resp.json() if resp.content else {}
        return {"ok": bool(payload.get("state")), "crm": payload}

    async def order_item_request(
        self,
        order_id: str | int,
        order_product_id: int | str,
        *,
        count: int | float = 1,
        warehouse_type: int | None = None,
    ) -> dict[str, Any]:
        oid = str(order_id).strip()
        data: dict[str, Any] = {
            "order_product_id": str(order_product_id),
            "count": str(count),
        }
        if warehouse_type is not None:
            data["warehouse_type"] = str(warehouse_type)
        resp = await self.request(
            "POST",
            f"/orders/{oid}/order-item",
            data=data,
            headers=self._ajax_headers(f"{self.base_url}/orders/{oid}"),
        )
        resp.raise_for_status()
        payload = resp.json() if resp.content else {}
        return payload

    @staticmethod
    def find_supplier_order_id_for_product(html: str, order_product_id: int | str) -> str | None:
        og = str(order_product_id).strip()
        patterns = [
            rf"SupplierOrder\.showEdit\([^,]+,\s*'?(?P<so>\d+)'?\s*,[^)]*?,\s*{re.escape(og)}\s*\)",
            rf"edit_supplier_order&order_id=(?P<so>\d+)[^>]{{0,200}}{re.escape(og)}",
            rf"goods-item-{re.escape(og)}[\s\S]{{0,2500}}?"
            rf"edit_supplier_order&order_id=(?P<so>\d+)",
        ]
        for pat in patterns:
            m = re.search(pat, html or "", re.I)
            if m:
                return m.group("so")
        return None

    @staticmethod
    def resolve_supplier_id_from_form(html: str, supplier_name: str) -> str | None:
        soup = BeautifulSoup(html or "", "lxml")
        sel = soup.select_one('select[name="warehouse-supplier"]')
        if not sel:
            return None
        want = (supplier_name or "").strip().lower().replace(" ", "")
        best = None
        for opt in sel.find_all("option"):
            val = str(opt.get("value") or "").strip()
            if not val or val == "0":
                continue
            label = opt.get_text(" ", strip=True).lower().replace(" ", "")
            if label == want:
                return val
            if want in label and best is None:
                best = val
        return best

    @staticmethod
    def _supplier_order_form_fields(html: str) -> dict[str, str]:
        soup = BeautifulSoup(html or "", "lxml")
        fields: dict[str, str] = {}
        for el in soup.select("input[name], select[name], textarea[name]"):
            name = el.get("name")
            if not name:
                continue
            if el.name == "select":
                selected = el.find("option", selected=True) or el.find("option")
                fields[name] = str(selected.get("value") if selected else "") or ""
            elif el.get("type") == "checkbox":
                if el.has_attr("checked"):
                    fields[name] = el.get("value") or "1"
            elif el.get("type") == "radio":
                if el.has_attr("checked"):
                    fields[name] = el.get("value") or ""
            elif el.name == "textarea":
                fields[name] = el.get_text() or ""
            else:
                fields[name] = el.get("value") or ""
        return fields

    async def edit_supplier_order_form(
        self,
        supplier_order_id: str | int,
        *,
        client_order_id: str | int | None = None,
        order_product_id: str | int | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": str(supplier_order_id),
            "without_info_block": "1",
        }
        if client_order_id:
            data["client_order_id"] = str(client_order_id)
        if order_product_id:
            data["order_product_id"] = str(order_product_id)
        resp = await self.request(
            "POST",
            "/supplier_orders/ajax?act=edit_supplier_order",
            data=data,
            headers=self._ajax_headers(f"{self.base_url}/supplier_orders"),
        )
        resp.raise_for_status()
        payload = resp.json() if resp.content else {}
        if not payload.get("state"):
            raise GincoreError(
                payload.get("msg")
                or payload.get("message")
                or f"Не удалось открыть запрос поставщику {supplier_order_id}"
            )
        form = payload.get("form") or {}
        html = form.get("html") if isinstance(form, dict) else ""
        return {
            "ok": True,
            "supplier_order_id": str(supplier_order_id),
            "title": payload.get("title"),
            "html": html or "",
            "buttons": (form.get("buttons") if isinstance(form, dict) else "") or "",
            "fields": self._supplier_order_form_fields(html or ""),
            "crm": payload,
        }

    async def fast_debit_supplier_order(
        self,
        fields: dict[str, Any],
        *,
        price: float,
        supplier_id: str | int,
        fast_debit: int = 1,
    ) -> dict[str, Any]:
        data = {str(k): "" if v is None else str(v) for k, v in (fields or {}).items()}
        data["warehouse-supplier"] = str(supplier_id)
        price_s = (
            str(int(price))
            if abs(price - round(price)) < 1e-9
            else f"{price:.2f}".rstrip("0").rstrip(".")
        )
        amount_keys = [k for k in data if k.startswith("amount[")]
        if not amount_keys:
            raise GincoreError("В форме запроса поставщику нет поля цены (amount[…])")
        for key in amount_keys:
            data[key] = price_s
            item_id = key[len("amount[") : -1]
            sum_key = f"sum[{item_id}]"
            if sum_key in data:
                data[sum_key] = price_s
            qty_key = f"quantity[{item_id}]"
            if qty_key not in data or not str(data.get(qty_key) or "").strip():
                data[qty_key] = "1"
        data["fast_debit"] = str(fast_debit)
        data["for_manufacture"] = "0"
        resp = await self.request(
            "POST",
            "/supplier_orders/ajax?act=edit-supplier-order",
            data=data,
            headers=self._ajax_headers(f"{self.base_url}/supplier_orders"),
        )
        resp.raise_for_status()
        payload = resp.json() if resp.content else {}
        if not (payload.get("state") or payload.get("fast_debit")):
            raise GincoreError(
                payload.get("msg")
                or payload.get("message")
                or "Не удалось оприходовать запчасть"
            )
        return {"ok": True, "crm": payload}

    async def preview_parts_attach(
        self,
        order_id: str | int,
        amount: float,
        *,
        note: str = "",
    ) -> dict[str, Any]:
        oid = str(order_id).strip()
        price = abs(float(amount))
        html = await self.fetch_order_html(oid)
        status = self.parse_order_status(html)
        payment = self.parse_order_payment(html)
        title = BeautifulSoup(html, "lxml").title
        cur_id = status.get("status_id")
        return {
            "ok": True,
            "kind": "parts_attach",
            "order_id": oid,
            "amount": price,
            "note": note or "",
            "product_title": PARTS_ATTACH_PRODUCT_TITLE,
            "supplier_name": PARTS_ATTACH_SUPPLIER_NAME,
            "target_status_id": PARTS_ATTACH_STATUS_ID,
            "target_status_name": PARTS_ATTACH_STATUS_NAME,
            "current_status_id": cur_id,
            "current_status_name": status.get("status_name"),
            "will_change_status": cur_id != PARTS_ATTACH_STATUS_ID,
            "order": {
                "order_id": oid,
                "url": f"{self.base_url}/orders/{oid}",
                "title": title.get_text(strip=True) if title else None,
                "payment": payment,
                "status": status,
            },
        }

    async def attach_spare_part(
        self,
        order_id: str | int,
        amount: float,
        *,
        note: str = "",
        product_title: str = PARTS_ATTACH_PRODUCT_TITLE,
        supplier_name: str = PARTS_ATTACH_SUPPLIER_NAME,
        target_status_id: int = PARTS_ATTACH_STATUS_ID,
        restore_status: bool = True,
    ) -> dict[str, Any]:
        """Bind «Запчасти.», order locally from Prom.ua, fast-debit, restore status."""
        oid = str(order_id).strip()
        price = abs(float(amount))
        if price <= 0:
            raise GincoreError("Цена запчасти должна быть > 0")

        html = await self.fetch_order_html(oid)
        original_status = self.parse_order_status(html)
        original_id = original_status.get("status_id")
        status_changed = False
        og_id: int | None = None
        supplier_order_id: str | None = None

        try:
            if original_id != target_status_id:
                await self.change_order_status(oid, target_status_id)
                status_changed = True

            goods_id = await self.resolve_goods_id_by_title(product_title)
            added = await self.add_order_product(oid, goods_id, make_order_button=True)
            og_id = int(added["og_id"])

            first = await self.order_item_request(oid, og_id, count=1)
            if first.get("confirm"):
                local = await self.order_item_request(
                    oid,
                    og_id,
                    count=1,
                    warehouse_type=PARTS_ATTACH_WAREHOUSE_LOCAL,
                )
                if not local.get("state"):
                    raise GincoreError(
                        local.get("msg")
                        or local.get("message")
                        or "Не удалось «заказать локально»"
                    )
            elif not first.get("state"):
                raise GincoreError(
                    first.get("msg")
                    or first.get("message")
                    or "Не удалось нажать «Заказать»"
                )

            html2 = await self.fetch_order_html(oid)
            supplier_order_id = self.find_supplier_order_id_for_product(html2, og_id)
            if not supplier_order_id:
                raise GincoreError(
                    "После «заказать локально» не найден запрос поставщику на запчасть"
                )

            form = await self.edit_supplier_order_form(
                supplier_order_id,
                client_order_id=oid,
                order_product_id=og_id,
            )
            supplier_id = self.resolve_supplier_id_from_form(
                form["html"], supplier_name
            )
            if not supplier_id:
                raise GincoreError(f"Поставщик «{supplier_name}» не найден в форме закупки")

            debit = await self.fast_debit_supplier_order(
                form["fields"],
                price=price,
                supplier_id=supplier_id,
                fast_debit=1,
            )

            restored = None
            if restore_status and status_changed and original_id is not None:
                restored = await self.change_order_status(oid, original_id)

            return {
                "ok": True,
                "kind": "parts_attach",
                "order_id": oid,
                "amount": price,
                "note": note or "",
                "product_title": product_title,
                "product_id": goods_id,
                "order_product_id": og_id,
                "supplier_order_id": supplier_order_id,
                "supplier_id": supplier_id,
                "supplier_name": supplier_name,
                "original_status_id": original_id,
                "original_status_name": original_status.get("status_name"),
                "restored_status": bool(restored),
                "crm": debit.get("crm"),
            }
        except Exception:
            if status_changed and restore_status and original_id is not None:
                try:
                    await self.change_order_status(oid, original_id)
                except Exception:  # noqa: BLE001
                    pass
            if og_id is not None and supplier_order_id is None:
                try:
                    await self.remove_order_product(oid, og_id)
                except Exception:  # noqa: BLE001
                    pass
            raise

    async def begin_cashbox_expense(
        self,
        cashbox_id: str | int | None = None,
    ) -> dict[str, Any]:
        """Open CRM «Выдача» dialog (begin-transaction-1)."""
        data: dict[str, Any] = {}
        if cashbox_id:
            data["object_id"] = str(cashbox_id)
        resp = await self.request(
            "POST",
            "/accountings/ajax?act=begin-transaction-1&show=modal",
            data=data or None,
            headers=self._ajax_headers(f"{self.base_url}/accountings#cashboxes"),
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("state"):
            raise GincoreError(
                payload.get("message") or payload.get("msg") or "Не удалось открыть выдачу"
            )
        content = str(payload.get("content") or "")
        soup = BeautifulSoup(content, "lxml")

        def _opts(select_name: str) -> list[dict[str, str]]:
            out: list[dict[str, str]] = []
            for opt in soup.select(f'select[name="{select_name}"] option'):
                cid = str(opt.get("value") or "").strip()
                if not cid:
                    continue
                out.append({"id": cid, "name": opt.get_text(" ", strip=True)})
            return out

        cashboxes = _opts("cashbox_from")
        categories = _opts("contractor_category_id_to")
        selected = None
        sel = soup.select_one('select[name="cashbox_from"] option[selected]')
        if sel and sel.get("value"):
            selected = str(sel.get("value"))
        hidden = soup.select_one('input[name="cashbox_from"][type="hidden"]')
        if not selected and hidden and hidden.get("value"):
            selected = str(hidden.get("value"))
        cur = soup.select_one('select[name="cashbox_currencies_from"] option[selected]')
        currency_id = (
            str(cur.get("value"))
            if cur and cur.get("value")
            else "3"
        )
        return {
            "ok": True,
            "kind": "cashbox_expense",
            "cashboxes": cashboxes,
            "categories": categories,
            "selected_cashbox_id": selected or (cashboxes[0]["id"] if cashboxes else None),
            "currency_id": currency_id,
            "transaction_type": "1",
            "form_act": "transaction_form",
            "date_transaction": (
                str(soup.select_one('input[name="date_transaction"]').get("value") or "")
                if soup.select_one('input[name="date_transaction"]')
                else ""
            ),
        }

    async def list_contractors_by_category(
        self, category_id: str | int
    ) -> list[dict[str, str]]:
        resp = await self.request(
            "GET",
            "/accountings/ajax",
            params={
                "act": "get-contractors-by-category_id",
                "contractor_category_id": str(category_id),
            },
            headers=self._ajax_headers(f"{self.base_url}/accountings#cashboxes"),
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("state"):
            raise GincoreError(
                payload.get("message") or payload.get("msg") or "Не удалось загрузить контрагентов"
            )
        html = str(payload.get("contractors") or "")
        soup = BeautifulSoup(html, "lxml")
        out: list[dict[str, str]] = []
        for opt in soup.select("option"):
            cid = str(opt.get("value") or "").strip()
            if not cid:
                continue
            out.append({"id": cid, "name": opt.get_text(" ", strip=True)})
        return out

    async def create_cashbox_expense(
        self,
        *,
        cashbox_id: str | int,
        amount: float,
        category_id: str | int,
        contractor_id: str | int | None = None,
        comment: str = "",
        currency_id: str | int = "3",
        without_contractor: bool = False,
    ) -> dict[str, Any]:
        """POST create-transaction — расход (Выдать) из кассы."""
        amt = f"{float(amount):.2f}".rstrip("0").rstrip(".")
        date_transaction = ""
        try:
            begin = await self.begin_cashbox_expense(cashbox_id)
            currency_id = str(begin.get("currency_id") or currency_id or "3")
            date_transaction = str(begin.get("date_transaction") or "").strip()
        except Exception:
            try:
                currency_id = await self.get_cashbox_currency_id(
                    cashbox_id, transaction_act="begin-transaction-1"
                )
            except Exception:
                currency_id = str(currency_id or "3")
        if not date_transaction:
            date_transaction = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        # Mapping fields must be a dict for AsyncClient.
        data: dict[str, Any] = {
            "act": "transaction_form",
            "transaction_type": "1",
            "supplier_order_id": "0",
            "client_order_id": "0",
            "transaction_extra": "0",
            "cashbox_from": str(cashbox_id),
            "amount_from": amt,
            "cashbox_currencies_from": str(currency_id),
            "cashbox_course_from": "1",
            # CRM form still posts to-side fields; mirror cashbox/zero amount
            "cashbox_to": str(cashbox_id),
            "amount_to": "0",
            "cashbox_currencies_to": str(currency_id),
            "cashbox_course_to": "1",
            "contractor_category_id_to": str(category_id),
            "contractor_category_id_from": "",
            "comment": comment or "",
            "date_transaction": date_transaction,
        }
        if contractor_id and not without_contractor:
            data["contractors_id[]"] = str(contractor_id)
        else:
            data["without_contractor"] = "1"

        resp = await self.request(
            "POST",
            "/accountings/ajax?act=create-transaction",
            data=data,
            headers=self._ajax_headers(f"{self.base_url}/accountings#cashboxes"),
        )
        resp.raise_for_status()
        try:
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise GincoreError(f"Неожиданный ответ CRM: {resp.text[:300]}") from exc
        ok = bool(payload.get("state")) or payload.get("status_code") == 200
        if not ok:
            # CRM may ask confirm=1
            if payload.get("confirm"):
                data["confirm"] = "1"
                resp2 = await self.request(
                    "POST",
                    "/accountings/ajax?act=create-transaction",
                    data=data,
                    headers=self._ajax_headers(f"{self.base_url}/accountings#cashboxes"),
                )
                resp2.raise_for_status()
                payload = resp2.json()
                ok = bool(payload.get("state")) or payload.get("status_code") == 200
            if not ok:
                msg = (
                    payload.get("msg")
                    or payload.get("message")
                    or "Ошибка выдачи из кассы"
                )
                if "нет прав" in str(msg).lower():
                    raise GincoreError(
                        f"{msg} (логин CRM «{self.login}»: в Gincore включите "
                        "право выдачи денег из кассы / доступ к кассе для этого пользователя)"
                    )
                raise GincoreError(msg)
        return {
            "ok": True,
            "kind": "cashbox_expense",
            "cashbox_id": str(cashbox_id),
            "amount": float(amount),
            "category_id": str(category_id),
            "contractor_id": str(contractor_id) if contractor_id else None,
            "comment": comment,
            "crm": {
                "state": payload.get("state"),
                "msg": payload.get("msg") or payload.get("message"),
                "transaction_id": payload.get("transaction_id"),
            },
        }

    async def _meta_from_transactions_tab(self) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        html = await self._tab_html("accountings_transactions_cashboxes")
        soup = BeautifulSoup(html, "lxml")
        categories = [
            {"id": str(o.get("value")), "name": o.get_text(" ", strip=True)}
            for o in soup.select('select[name="categories[]"] option')
            if o.get("value")
        ]
        contractors = [
            {"id": str(o.get("value")), "name": o.get_text(" ", strip=True)}
            for o in soup.select('select[name="contractors[]"] option')
            if o.get("value")
        ]
        self._categories = categories
        self._contractors = contractors
        return categories, contractors

    async def list_categories(self) -> list[dict[str, str]]:
        if self._categories is None:
            await self._meta_from_transactions_tab()
        return list(self._categories or [])

    async def list_contractors(self) -> list[dict[str, str]]:
        if self._contractors is None:
            await self._meta_from_transactions_tab()
        return list(self._contractors or [])

    async def find_category(self, query: str) -> list[dict[str, str]]:
        cats = await self.list_categories()
        q = query.lower().strip()
        # Stem: «аренда» ↔ «аренду», «зарплаты» ↔ «зарплат»
        stem = re.sub(r"(ы|и|у|ю|е|а|я|ов|ей|ами|ах)$", "", q)
        if len(stem) < 4:
            stem = q

        scored: list[tuple[int, dict[str, str]]] = []
        for cat in cats:
            name = cat["name"].lower()
            bare = name.lstrip("↓↑- ").strip()
            hit = q in name or (stem and stem in name)
            if not hit:
                continue
            score = 0
            if bare.startswith(q) or q == bare or stem and bare.startswith(stem):
                score -= 10
            if q in bare:
                score -= 5
            if "↓" in cat["name"] or "расход" in name:
                score -= 1
            # Prefer shorter names when equally matched
            score += min(len(bare), 80) // 20
            scored.append((score, cat))
        scored.sort(key=lambda x: (x[0], x[1]["name"]))
        return [c for _, c in scored]

    async def find_contractor(self, query: str) -> list[dict[str, str]]:
        contractors = await self.list_contractors()
        q = query.lower().strip()
        parts = [p for p in re.split(r"\s+", q) if p]
        matched = []
        for c in contractors:
            name = c["name"].lower()
            if q in name or all(p in name for p in parts):
                matched.append(c)
        # Prefer shorter/exact-ish names
        matched.sort(key=lambda c: (0 if q == c["name"].lower() else 1, len(c["name"])))
        return matched

    def _parse_transaction_rows(
        self, html: str, *, default_year: int | None = None
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        rows: list[dict[str, Any]] = []
        for tr in soup.select("table tbody tr"):
            tds = tr.select("td")
            if not tds:
                continue
            cells = [td.get_text(" ", strip=True) for td in tds]
            blob = " ".join(cells).lower()
            if "нет транзакций" in blob:
                continue
            movement = cells[2] if len(cells) > 2 else ""
            category = ""
            m = re.search(r"[←→]\s*(.+?)(?:\s+Заказ:|\s+Зак\.|$)", movement)
            if m:
                category = m.group(1).strip()
            date_raw = cells[1] if len(cells) > 1 else ""
            # Prefer full datetime from title tooltip if present (any cell in the row).
            title = ""
            for td in tds:
                if td.get("title"):
                    title = str(td.get("title"))
                    break
                el = td.find(attrs={"title": True})
                if el and el.get("title"):
                    title = str(el.get("title"))
                    break
            parsed = None
            if title:
                tm = re.search(r"(\d{4}-\d{2}-\d{2})", title.replace("\xa0", " "))
                if tm:
                    try:
                        parsed = datetime.strptime(tm.group(1), "%Y-%m-%d").date()
                    except ValueError:
                        parsed = None
            if parsed is None:
                parsed = parse_gincore_date(date_raw, default_year=default_year)
            # Fallback: date embedded in movement ("563131, 4 Авг. Левитан → ...")
            if parsed is None and movement:
                mm = re.search(
                    r",\s*(\d{1,2}\s+[А-Яа-яA-Za-z]+\.?|Сегодня|Вчера|\d{2}\.\d{2}\.\d{4})",
                    movement,
                )
                if mm:
                    parsed = parse_gincore_date(mm.group(1), default_year=default_year)

            income = parse_money(cells[6]) if len(cells) > 6 else None
            expense = parse_money(cells[7]) if len(cells) > 7 else None
            rows.append(
                {
                    "id": cells[0] if cells else "",
                    "date": date_raw,
                    "date_iso": parsed.isoformat() if parsed else None,
                    "month": month_key(parsed) if parsed else None,
                    "movement": movement,
                    "category": category,
                    "contractor": cells[3] if len(cells) > 3 else "",
                    "income": income,
                    "expense": abs(expense) if expense is not None else None,
                    "expense_raw": expense,
                    "responsible": cells[8] if len(cells) > 8 else "",
                    "note": cells[9] if len(cells) > 9 else "",
                }
            )

        # Pagination links use &amp;p=N in HTML — match p= anywhere.
        pages = [int(x) for x in re.findall(r"[?&](?:amp;)?p=(\d+)", html)]
        pages += [int(x) for x in re.findall(r"p=(\d+)", html)]
        max_page = max(pages) if pages else (1 if rows else 1)

        meta: dict[str, Any] = {
            "record_total": None,
            "footer_expense_total": None,
            "footer_income_total": None,
        }
        text = soup.get_text(" ", strip=True)
        m_count = re.search(r"Всего:\s*(\d+)\s*записей", text, re.I)
        if m_count:
            meta["record_total"] = int(m_count.group(1))

        tfoot = soup.select_one("tfoot")
        if tfoot:
            incomes = [
                parse_money(el.get_text(" ", strip=True))
                for el in tfoot.select(".btn-success")
            ]
            expenses = [
                parse_money(el.get_text(" ", strip=True))
                for el in tfoot.select(".btn-warning")
            ]
            incomes = [a for a in incomes if a is not None]
            expenses = [a for a in expenses if a is not None]
            if incomes:
                meta["footer_income_total"] = abs(max(incomes, key=abs))
            if expenses:
                # Expense cells are negative; take the largest absolute value.
                meta["footer_expense_total"] = abs(min(expenses))
        else:
            m_total = re.search(r"Итого:\s*(.+?)(?:История|$)", text, re.I)
            if m_total:
                amounts = [
                    parse_money(a)
                    for a in re.findall(
                        r"-?\d[\d\s]*(?:[.,]\d+)?",
                        m_total.group(1).replace("\xa0", " "),
                    )
                ]
                amounts = [a for a in amounts if a is not None]
                neg = [a for a in amounts if a < 0]
                pos = [a for a in amounts if a > 0]
                if neg:
                    meta["footer_expense_total"] = abs(min(neg))
                if pos:
                    meta["footer_income_total"] = max(pos)

        return rows, max_page, meta

    async def fetch_transactions_page(
        self,
        *,
        date_from: str,
        date_to: str,
        category_id: str | None = None,
        contractor_id: str | None = None,
        page: int = 1,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        query: dict[str, Any] = {
            "df": to_gincore_date(date_from),
            "dt": to_gincore_date(date_to),
            "p": page,
        }
        if category_id:
            query["cg"] = category_id
        if contractor_id:
            query["ct"] = contractor_id
        html = await self._tab_html(
            "accountings_transactions_cashboxes", query=query
        )
        year = int(date_from[:4])
        return self._parse_transaction_rows(html, default_year=year)

    async def fetch_transactions(
        self,
        *,
        date_from: str,
        date_to: str,
        category_id: str | None = None,
        contractor_id: str | None = None,
        max_pages: int = MAX_PAGES,
    ) -> dict[str, Any]:
        first_rows, total_pages, meta = await self.fetch_transactions_page(
            date_from=date_from,
            date_to=date_to,
            category_id=category_id,
            contractor_id=contractor_id,
            page=1,
        )
        # Prefer CRM "Всего: N записей" to infer pages if link parse failed.
        if meta.get("record_total") and total_pages <= 1 and len(first_rows) > 0:
            inferred = max(1, (int(meta["record_total"]) + len(first_rows) - 1) // len(first_rows))
            total_pages = max(total_pages, inferred)

        pages_to_fetch = min(total_pages, max_pages)
        all_rows = list(first_rows)
        if pages_to_fetch > 1:
            sem = asyncio.Semaphore(PAGE_CONCURRENCY)

            async def one(p: int) -> list[dict[str, Any]]:
                async with sem:
                    rows, _, _ = await self.fetch_transactions_page(
                        date_from=date_from,
                        date_to=date_to,
                        category_id=category_id,
                        contractor_id=contractor_id,
                        page=p,
                    )
                    return rows

            parts = await asyncio.gather(*[one(p) for p in range(2, pages_to_fetch + 1)])
            for part in parts:
                all_rows.extend(part)

        income_total = round(sum(r["income"] or 0 for r in all_rows), 2)
        expense_total = round(sum(r["expense"] or 0 for r in all_rows), 2)
        # Trust CRM footer total when present (more accurate / avoids partial page bugs).
        if meta.get("footer_expense_total") is not None and not (total_pages > max_pages):
            # Only prefer footer if we fetched all pages OR footer matches denser truth.
            if pages_to_fetch >= total_pages or len(all_rows) < (meta.get("record_total") or 0):
                expense_total = float(meta["footer_expense_total"])

        # If still truncated vs record_total, mark truncated
        truncated = total_pages > max_pages or (
            meta.get("record_total") is not None and len(all_rows) < int(meta["record_total"])
            and pages_to_fetch >= total_pages
        )
        # After fetching all declared pages, clear truncated if counts match
        if meta.get("record_total") is not None and len(all_rows) >= int(meta["record_total"]):
            truncated = False
            if meta.get("footer_expense_total") is not None:
                expense_total = float(meta["footer_expense_total"])

        return {
            "date_from": date_from,
            "date_to": date_to,
            "category_id": category_id,
            "contractor_id": contractor_id,
            "pages_total": total_pages,
            "pages_fetched": pages_to_fetch,
            "truncated": truncated,
            "crm_record_total": meta.get("record_total"),
            "crm_footer_expense_total": meta.get("footer_expense_total"),
            "count": len(all_rows),
            "income_total": income_total,
            "expense_total": expense_total,
            "net": round(income_total - expense_total, 2),
            "sample": all_rows[:SAMPLE_ROWS],
            "rows": all_rows,
        }

    async def sum_by_category(
        self,
        category_query: str,
        *,
        date_from: str,
        date_to: str,
        contractor_query: str | None = None,
    ) -> dict[str, Any]:
        cats = await self.find_category(category_query)
        if not cats:
            return {
                "error": f"Категория не найдена: {category_query}",
                "hint": "Вызовите gincore_list_categories",
            }
        cat = cats[0]
        contractor_id = None
        contractor_matched = None
        if contractor_query:
            found = await self.find_contractor(contractor_query)
            if not found:
                return {
                    "error": f"Контрагент не найден: {contractor_query}",
                    "category": cat,
                }
            contractor_matched = found[0]
            contractor_id = contractor_matched["id"]

        data = await self.fetch_transactions(
            date_from=date_from,
            date_to=date_to,
            category_id=cat["id"],
            contractor_id=contractor_id,
        )
        return {
            "category": cat,
            "category_candidates": cats[:5],
            "contractor": contractor_matched,
            "date_from": date_from,
            "date_to": date_to,
            "count": data["count"],
            "crm_record_total": data.get("crm_record_total"),
            "expense_total": data["expense_total"],
            "income_total": data["income_total"],
            "pages_total": data["pages_total"],
            "pages_fetched": data["pages_fetched"],
            "truncated": data["truncated"],
            "sample": data["sample"],
            "by_month": self._monthly_breakdown(data["rows"]),
            "chart": self._monthly_chart(data["rows"], cat["name"].lstrip("↓↑- ").strip()),
        }

    def _monthly_breakdown(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buckets: dict[str, float] = {}
        for row in rows:
            key = row.get("month") or "unknown"
            buckets[key] = buckets.get(key, 0.0) + float(row.get("expense") or 0)
        return [
            {"month": k, "expense_total": round(v, 2)}
            for k, v in sorted(buckets.items(), key=lambda x: x[0])
        ]

    def _monthly_chart(self, rows: list[dict[str, Any]], title: str) -> dict[str, Any]:
        series = self._monthly_breakdown(rows)
        # Drop lonely unknown if we have real months
        real = [s for s in series if s["month"] != "unknown"]
        if real:
            series = real
        return {
            "type": "bar",
            "title": title,
            "labels": [s["month"] for s in series],
            "datasets": [
                {"label": "Расход", "data": [s["expense_total"] for s in series]}
            ],
        }

    async def category_period_total(
        self,
        *,
        category_id: str,
        date_from: str,
        date_to: str,
    ) -> dict[str, Any]:
        """Accurate period total for one article via CRM footer (page 1 only)."""
        _rows, _pages, meta = await self.fetch_transactions_page(
            date_from=date_from,
            date_to=date_to,
            category_id=category_id,
            page=1,
        )
        return {
            "category_id": category_id,
            "record_total": meta.get("record_total") or 0,
            "expense_total": float(meta.get("footer_expense_total") or 0),
            "income_total": float(meta.get("footer_income_total") or 0),
        }

    async def analytics_by_month(
        self,
        *,
        year: int | None = None,
        category_id: str | None = None,
        category_name: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """Income/expense (and optional one article) per month via CRM footer."""
        today = date.today()
        if date_from and date_to:
            df, dt = date_from, date_to
        else:
            year = year or today.year
            df = f"{year:04d}-01-01"
            dt = today.isoformat() if year == today.year else f"{year:04d}-12-31"
        return await self._aggregate_by_month(
            date_from=df,
            date_to=dt,
            category_id=category_id,
            category_name=category_name,
        )

    async def _aggregate_by_month(
        self,
        *,
        date_from: str,
        date_to: str,
        category_id: str | None = None,
        category_name: str | None = None,
        contractor_id: str | None = None,
    ) -> dict[str, Any]:
        months_spec = months_in_range(date_from, date_to)
        sem = asyncio.Semaphore(PAGE_CONCURRENCY)
        ru_labels = [
            "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
            "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
        ]

        async def one(y: int, month_idx: int, df: str, dt: str) -> dict[str, Any]:
            async with sem:
                _rows, _pages, meta = await self.fetch_transactions_page(
                    date_from=df,
                    date_to=dt,
                    category_id=category_id,
                    contractor_id=contractor_id,
                    page=1,
                )
                income = float(meta.get("footer_income_total") or 0)
                expense = float(meta.get("footer_expense_total") or 0)
                return {
                    "month": month_idx,
                    "year": y,
                    "label": f"{ru_labels[month_idx - 1]} {y}",
                    "key": f"{y:04d}-{month_idx:02d}",
                    "date_from": df,
                    "date_to": dt,
                    "income": income,
                    "expense": expense,
                    "net": round(income - expense, 2),
                    "record_total": meta.get("record_total") or 0,
                }

        parts = await asyncio.gather(
            *[one(y, m, df, dt) for y, m, df, dt in months_spec]
        )

        labels = [p["label"] for p in parts]
        incomes = [p["income"] for p in parts]
        expenses = [p["expense"] for p in parts]
        nets = [p["net"] for p in parts]

        title_suffix = f" · {category_name}" if category_name else ""
        # Expense-focused chart when filtered to an expense article
        if category_id and sum(incomes) < sum(expenses) * 0.05:
            charts = [
                {
                    "type": "bar",
                    "title": f"Расходы по месяцам{title_suffix}",
                    "labels": labels,
                    "datasets": [
                        {
                            "label": "Расход",
                            "data": expenses,
                            "backgroundColor": "rgba(198, 40, 40, 0.7)",
                            "borderColor": "#c62828",
                        }
                    ],
                }
            ]
        else:
            charts = [
                {
                    "type": "bar",
                    "title": f"Доходы и расходы по месяцам{title_suffix}",
                    "labels": labels,
                    "datasets": [
                        {
                            "label": "Доход",
                            "data": incomes,
                            "backgroundColor": "rgba(46, 125, 50, 0.75)",
                            "borderColor": "#2e7d32",
                        },
                        {
                            "label": "Расход",
                            "data": expenses,
                            "backgroundColor": "rgba(198, 40, 40, 0.65)",
                            "borderColor": "#c62828",
                        },
                    ],
                },
                {
                    "type": "line",
                    "title": f"Прибыль (доход − расход){title_suffix}",
                    "labels": labels,
                    "datasets": [
                        {
                            "label": "Прибыль",
                            "data": nets,
                            "borderColor": "#1565c0",
                            "backgroundColor": "rgba(21, 101, 192, 0.15)",
                            "fill": True,
                            "tension": 0.25,
                        }
                    ],
                },
            ]

        return {
            "date_from": date_from,
            "date_to": date_to,
            "year": months_spec[0][0] if months_spec else None,
            "category": category_name,
            "category_id": category_id,
            "contractor_id": contractor_id,
            "complete": True,
            "method": "crm_footer_per_month",
            "group_by": "month",
            "months": parts,
            "series": parts,
            "totals": {
                "income": round(sum(incomes), 2),
                "expense": round(sum(expenses), 2),
                "net": round(sum(nets), 2),
                "record_total": sum(p["record_total"] for p in parts),
            },
            "income_total": round(sum(incomes), 2),
            "expense_total": round(sum(expenses), 2),
            "net": round(sum(nets), 2),
            "chart": charts[0],
            "charts": charts,
        }

    async def query(
        self,
        *,
        ranges: list[dict[str, str]] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        category_query: str | None = None,
        contractor_query: str | None = None,
        group_by: str = "auto",
        include_list: bool = False,
    ) -> dict[str, Any]:
        """Universal finance query: filters + 1..N period ranges → matching charts/tables."""
        from modules.gincore.charts import month_comparison_chart, month_comparison_table, month_series_table

        today = date.today()
        if not ranges:
            if not date_from or not date_to:
                raise GincoreError("Нужен период: ranges или date_from/date_to")
            ranges = [{"date_from": date_from, "date_to": date_to, "label": date_from[:4]}]

        norm_ranges: list[dict[str, str]] = []
        for r in ranges:
            df = r["date_from"]
            dt = r["date_to"]
            end = datetime.strptime(dt, "%Y-%m-%d").date()
            if end > today:
                dt = today.isoformat()
            label = str(r.get("label") or df[:4])
            norm_ranges.append({"date_from": df, "date_to": dt, "label": label})
        ranges = norm_ranges

        date_from = ranges[0]["date_from"]
        date_to = ranges[0]["date_to"]
        start = datetime.strptime(date_from, "%Y-%m-%d").date()
        end = datetime.strptime(date_to, "%Y-%m-%d").date()
        span_days = (end - start).days + 1

        category = None
        category_id = None
        if category_query:
            cats = await self.find_category(category_query)
            if not cats:
                return {
                    "error": f"Статья не найдена: {category_query}",
                    "hint": "Вызови gincore_list_categories или уточни название",
                }
            category = {
                "id": cats[0]["id"],
                "name": cats[0]["name"].lstrip("↓↑- ").strip(),
                "raw": cats[0]["name"],
            }
            category_id = category["id"]

        contractor = None
        contractor_id = None
        if contractor_query:
            found = await self.find_contractor(contractor_query)
            if not found:
                return {
                    "error": f"Контрагент не найден: {contractor_query}",
                    "category": category,
                }
            contractor = found[0]
            contractor_id = contractor["id"]

        gb = (group_by or "auto").lower()
        if len(ranges) > 1 and gb in {"auto", "month"}:
            gb = "month"
        if gb == "auto":
            if include_list or span_days <= 1:
                gb = "list"
            elif span_days >= 45 or start.month != end.month or start.year != end.year:
                gb = "month" if category_id or span_days >= 60 else "category"
            else:
                gb = "total"

        filters = {
            "ranges": ranges,
            "category": category,
            "contractor": contractor,
            "group_by": gb,
        }

        if gb == "month":
            parts: list[dict[str, Any]] = []
            for r in ranges:
                agg = await self._aggregate_by_month(
                    date_from=r["date_from"],
                    date_to=r["date_to"],
                    category_id=category_id,
                    category_name=category["name"] if category else None,
                    contractor_id=contractor_id,
                )
                agg["label"] = r["label"]
                agg["year"] = agg.get("year") or r["label"]
                parts.append(agg)

            topic = category["name"] if category else "доходы/расходы"
            metric = "expense"
            if not category_id:
                # Prefer the metric that dominates the first series
                if (parts[0].get("income_total") or 0) > (parts[0].get("expense_total") or 0):
                    metric = "income"

            series_out = [
                {
                    "label": p.get("label"),
                    "date_from": p.get("date_from"),
                    "date_to": p.get("date_to"),
                    "year": p.get("year"),
                    "months": p["months"],
                    "totals": p["totals"],
                    "expense_total": p["expense_total"],
                    "income_total": p["income_total"],
                }
                for p in parts
            ]

            if len(parts) == 1:
                primary = parts[0]
                table = month_series_table(
                    primary,
                    title=f"По месяцам · {topic}",
                    metric=metric,
                )
                primary["filters"] = filters
                primary["table"] = table
                primary["tables"] = [table]
                primary["series"] = series_out
                primary["note"] = (
                    f"Помесячно"
                    + (f" · статья «{category['name']}»" if category else "")
                    + (f" · {contractor['name']}" if contractor else "")
                )
                return primary

            chart = month_comparison_chart(
                parts,
                title=f"Сравнение по месяцам · {topic}",
                metric=metric,
            )
            table = month_comparison_table(
                parts,
                title=f"Сравнение по месяцам · {topic}",
                metric=metric,
            )
            return {
                "filters": filters,
                "group_by": "month",
                "complete": True,
                "method": "crm_footer_per_month_series",
                "category": category["name"] if category else None,
                "series": series_out,
                "expense_total": parts[0]["expense_total"],
                "income_total": parts[0]["income_total"],
                "totals_by_series": [
                    {
                        "label": p.get("label"),
                        "expense_total": p["expense_total"],
                        "income_total": p["income_total"],
                        "net": p.get("net"),
                    }
                    for p in parts
                ],
                "chart": chart,
                "charts": [chart],
                "table": table,
                "tables": [table],
                "note": f"Сравнение {len(parts)} периодов · {topic}",
            }

        # Non-month modes use the first range (multi-range only meaningful for month compare)
        if gb == "list":
            data = await self.fetch_transactions(
                date_from=date_from,
                date_to=date_to,
                category_id=category_id,
                contractor_id=contractor_id,
                max_pages=5,
            )
            _rows, _p, meta = await self.fetch_transactions_page(
                date_from=date_from,
                date_to=date_to,
                category_id=category_id,
                contractor_id=contractor_id,
                page=1,
            )
            income = float(meta.get("footer_income_total") or data.get("income_total") or 0)
            expense = float(meta.get("footer_expense_total") or data.get("expense_total") or 0)
            by_cat: dict[str, float] = {}
            for row in data["rows"]:
                cat = (row.get("category") or "Прочее").strip()
                by_cat[cat] = by_cat.get(cat, 0.0) + float(row.get("expense") or 0)
            top = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)[:10]
            palette = [
                "rgba(198, 40, 40, 0.7)",
                "rgba(245, 124, 0, 0.75)",
                "rgba(123, 31, 162, 0.7)",
                "rgba(21, 101, 192, 0.7)",
                "rgba(15, 110, 86, 0.75)",
                "rgba(69, 90, 100, 0.7)",
                "rgba(183, 28, 28, 0.65)",
                "rgba(0, 121, 107, 0.7)",
                "rgba(239, 108, 0, 0.7)",
                "rgba(84, 110, 122, 0.7)",
            ]
            transactions = [
                {
                    "id": r.get("id"),
                    "time_or_date": r.get("date"),
                    "category": r.get("category"),
                    "contractor": r.get("contractor"),
                    "income": r.get("income"),
                    "expense": r.get("expense"),
                    "movement": (r.get("movement") or "")[:120],
                    "note": r.get("note") or "",
                }
                for r in data["rows"][:40]
            ]
            chart = {
                "type": "bar",
                "title": f"Расходы {date_from} — {date_to}"
                + (f" · {category['name']}" if category else " по статьям"),
                "labels": [k[:32] for k, _ in top],
                "datasets": [
                    {
                        "label": "Расход",
                        "data": [round(v, 2) for _, v in top],
                        "backgroundColor": palette[: len(top)],
                        "borderColor": palette[: len(top)],
                    }
                ],
            }
            return {
                **filters,
                "date_from": date_from,
                "date_to": date_to,
                "income_total": income,
                "expense_total": expense,
                "net": round(income - expense, 2),
                "crm_record_total": meta.get("record_total") or data.get("crm_record_total"),
                "listed": len(transactions),
                "truncated": bool(data.get("truncated")),
                "top_expense_categories": [
                    {"category": k, "expense_total": round(v, 2)} for k, v in top
                ],
                "transactions": transactions,
                "chart": chart,
                "charts": [chart],
                "complete": True,
                "method": "list_plus_footer",
            }

        if gb == "category":
            summary = await self.analytics_summary(date_from=date_from, date_to=date_to)
            summary["filters"] = {**filters, "group_by": "category"}
            charts = [
                c
                for c in (summary.get("charts") or [])
                if "Топ статей" in (c.get("title") or "") or "статей" in (c.get("title") or "").lower()
            ]
            if not charts and summary.get("chart"):
                charts = [summary["chart"]]
            summary["charts"] = charts or summary.get("charts") or []
            summary["chart"] = summary["charts"][0] if summary["charts"] else summary.get("chart")
            return summary

        _rows, _pages, meta = await self.fetch_transactions_page(
            date_from=date_from,
            date_to=date_to,
            category_id=category_id,
            contractor_id=contractor_id,
            page=1,
        )
        income = float(meta.get("footer_income_total") or 0)
        expense = float(meta.get("footer_expense_total") or 0)
        sample = None
        if category_id or contractor_id:
            data = await self.fetch_transactions(
                date_from=date_from,
                date_to=date_to,
                category_id=category_id,
                contractor_id=contractor_id,
                max_pages=2,
            )
            sample = data.get("sample")
        chart = {
            "type": "bar",
            "title": (
                f"{category['name'] if category else 'Итог'} "
                f"{date_from} — {date_to}"
                + (f" · {contractor['name']}" if contractor else "")
            ),
            "labels": ["Доход", "Расход"],
            "datasets": [
                {
                    "label": "Сумма",
                    "data": [income, expense],
                    "backgroundColor": [
                        "rgba(46, 125, 50, 0.75)",
                        "rgba(198, 40, 40, 0.7)",
                    ],
                }
            ],
        }
        return {
            **filters,
            "date_from": date_from,
            "date_to": date_to,
            "income_total": income,
            "expense_total": expense,
            "net": round(income - expense, 2),
            "crm_record_total": meta.get("record_total"),
            "sample": sample,
            "complete": True,
            "method": "crm_footer_totals",
            "chart": chart,
            "charts": [chart],
        }

    async def load_repair_staff_options(self) -> dict[str, list[dict[str, str]]]:
        """Staff lists from CRM repair filter form (engineers/managers/accepters)."""
        if self._repair_staff is not None:
            return self._repair_staff
        await self.ensure_login()
        resp = await self.request(
            "POST",
            "/orders/ajax?act=load-filter&tab=show_repair_orders",
            data={"get": ""},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.base_url}/orders#show_repair_orders",
            },
        )
        resp.raise_for_status()
        content = (resp.json() or {}).get("content") or ""
        soup = BeautifulSoup(content, "lxml")

        def opts(name: str) -> list[dict[str, str]]:
            out: list[dict[str, str]] = []
            for o in soup.select(f'select[name="{name}"] option'):
                vid = (o.get("value") or "").strip()
                label = o.get_text(" ", strip=True)
                if not vid or not label:
                    continue
                out.append({"id": vid, "name": label})
            return out

        self._repair_staff = {
            "engineers": opts("engineers[]"),
            "managers": opts("managers[]"),
            "accepters": opts("accepter[]"),
        }
        return self._repair_staff

    async def _repair_orders_page(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        crm_params: dict[str, Any] | None = None,
        page: int = 1,
    ) -> dict[str, Any]:
        """One page of /orders#show_repair_orders (+ CRM short-filter query params)."""
        await self.ensure_login()
        params: dict[str, Any] = dict(crm_params or {})
        # Dates from args win unless already set via crm_params (df/dt).
        if date_from and date_to:
            params.setdefault("df", to_gincore_date(date_from))
            params.setdefault("dt", to_gincore_date(date_to))
        if page and page > 1:
            params["p"] = page
        qs = urlencode(params, doseq=True)
        resp = await self.request(
            "POST",
            f"/orders/ajax?act=tab-load&{qs}",
            data={"tab": "show_repair_orders", "hashs": "#show_repair_orders"},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.base_url}/orders#show_repair_orders",
            },
        )
        resp.raise_for_status()
        html = (resp.json() or {}).get("html") or ""
        total_m = re.search(r"Всего:\s*([\d\s]+)", html)
        record_total = int(re.sub(r"\s+", "", total_m.group(1))) if total_m else 0
        return {
            "date_from": date_from,
            "date_to": date_to,
            "crm_params": params,
            "page": page,
            "count": record_total,
            "html": html,
        }

    async def _repair_orders_count(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        crm_params: dict[str, Any] | None = None,
        include_html: bool = False,
    ) -> dict[str, Any]:
        """CRM footer total for repair orders (page 1)."""
        meta = await self._repair_orders_page(
            date_from=date_from,
            date_to=date_to,
            crm_params=crm_params,
            page=1,
        )
        if not include_html:
            meta.pop("html", None)
        return meta

    @staticmethod
    def parse_repair_orders_payment_totals(html: str) -> dict[str, Any]:
        """Суммы «Стоимость»/«Оплачено» со страницы списка ремонтов.

        «Ожидаемая сумма оплаты» в шапке колонки «Оплачено» =
        Σ max(0, стоимость − оплачено) по всем строкам фильтра.
        """
        soup = BeautifulSoup(html, "lxml")
        cost_sum = 0.0
        paid_sum = 0.0
        debt_sum = 0.0
        orders = 0

        def _money(td: Any) -> float | None:
            raw = td.get_text(" ", strip=True).replace("\xa0", " ").replace(" ", "")
            raw = raw.replace(",", ".")
            m = re.search(r"-?\d+(?:\.\d+)?", raw)
            if not m:
                return None
            try:
                return float(m.group())
            except ValueError:
                return None

        for tr in soup.select("table.table-of-repair-orders tbody tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 13:
                continue
            cost = _money(tds[11])
            if cost is None:
                continue
            paid = _money(tds[12])
            if paid is None:
                paid = 0.0
            cost_sum += cost
            paid_sum += paid
            debt_sum += max(0.0, cost - paid)
            orders += 1
        return {
            "orders": orders,
            "cost_sum": round(cost_sum, 2),
            "paid_sum": round(paid_sum, 2),
            "expected_payment_sum": round(debt_sum, 2),
        }

    async def fetch_orders_expected_payment_sum(
        self,
        *,
        crm_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Итог «Ожидаемая сумма оплаты» по фильтру списка ремонтов (все страницы)."""
        params = dict(crm_params or {})
        meta = await self._repair_orders_page(crm_params=params, page=1)
        footer_total = int(meta.get("count") or 0)
        totals = self.parse_repair_orders_payment_totals(meta.get("html") or "")
        page = 1
        seen = totals["orders"]
        while seen < footer_total and page < MAX_PAGES:
            page += 1
            more = await self._repair_orders_page(crm_params=params, page=page)
            chunk = self.parse_repair_orders_payment_totals(more.get("html") or "")
            if not chunk["orders"]:
                break
            totals["orders"] += chunk["orders"]
            totals["cost_sum"] = round(totals["cost_sum"] + chunk["cost_sum"], 2)
            totals["paid_sum"] = round(totals["paid_sum"] + chunk["paid_sum"], 2)
            totals["expected_payment_sum"] = round(
                totals["expected_payment_sum"] + chunk["expected_payment_sum"], 2
            )
            seen = totals["orders"]
        return {
            **totals,
            "listed_total": footer_total,
            "crm_params": params,
        }

    @staticmethod
    def _parse_repair_order_rows(html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        orders: list[dict[str, Any]] = []
        for tr in soup.select("table.table-of-repair-orders tbody tr"):
            tds = tr.select("td")
            if not tds:
                continue

            def cell_text(i: int) -> str:
                if i >= len(tds):
                    return ""
                return tds[i].get_text(" ", strip=True)

            blob = " ".join(td.get_text(" ", strip=True) for td in tds).lower()
            if "нет заказ" in blob or "нет запис" in blob:
                continue

            id_raw = cell_text(1)
            order_id = id_raw if re.fullmatch(r"\d{4,}", id_raw or "") else next(
                (
                    td.get_text(" ", strip=True)
                    for td in tds
                    if re.fullmatch(r"\d{4,}", td.get_text(" ", strip=True) or "")
                ),
                "",
            )

            status = ""
            if len(tds) > 6:
                btn = tds[6].select_one(".btn-title") or tds[6].select_one(
                    "button.as_button"
                )
                if btn:
                    status = btn.get_text(" ", strip=True)
                if not status:
                    status = cell_text(6)[:80]

            def visible_lg(i: int) -> str:
                if i >= len(tds):
                    return ""
                span = tds[i].select_one(".visible-lg")
                if span:
                    return span.get_text(" ", strip=True)
                return re.sub(r"\s+", " ", cell_text(i)).strip()

            orders.append(
                {
                    "id": order_id,
                    "accepter": cell_text(3)[:60],
                    "accepted_by": cell_text(3)[:60],
                    "manager": cell_text(4)[:60],
                    "accepted_at": cell_text(3)[:60],
                    "engineer": cell_text(5)[:60],
                    "status": status[:80],
                    "device": visible_lg(9)[:80],
                    "client": cell_text(13)[:60],
                    "location": visible_lg(15)[:60],
                    "repair_type": cell_text(18)[:40],
                    "channel": cell_text(21)[:60],
                }
            )
        return orders

    async def _collect_repair_orders(
        self,
        *,
        date_from: str | None,
        date_to: str | None,
        crm_params: dict[str, Any],
        limit: int,
    ) -> tuple[int, list[dict[str, Any]]]:
        meta = await self._repair_orders_count(
            date_from=date_from,
            date_to=date_to,
            crm_params=crm_params,
            include_html=True,
        )
        count = meta["count"]
        orders = self._parse_repair_order_rows(meta.get("html") or "")
        page = 1
        seen_ids = {o["id"] for o in orders if o.get("id")}
        while len(orders) < min(count, limit) and page < MAX_PAGES:
            page += 1
            more = await self._repair_orders_page(
                date_from=date_from,
                date_to=date_to,
                crm_params=crm_params,
                page=page,
            )
            chunk = self._parse_repair_order_rows(more.get("html") or "")
            if not chunk:
                break
            new = 0
            for o in chunk:
                oid = o.get("id")
                if oid and oid in seen_ids:
                    continue
                if oid:
                    seen_ids.add(oid)
                orders.append(o)
                new += 1
            if new == 0:
                break
        return count, orders[:limit]

    def _repair_list_result(
        self,
        *,
        orders: list[dict[str, Any]],
        count: int,
        crm_count: int,
        resolved: dict[str, Any],
        crm_params: dict[str, Any],
        title: str,
        note: str,
        date_from: str | None = None,
        date_to: str | None = None,
        complete: bool = True,
    ) -> dict[str, Any]:
        table = {
            "title": title,
            "columns": ["ID", "Устройство", "Мастер", "Статус", "Точка", "Канал"],
            "rows": [
                [
                    o["id"],
                    o["device"][:36],
                    o["engineer"][:20],
                    o["status"][:28],
                    o["location"][:22],
                    (o.get("channel") or "")[:18],
                ]
                for o in orders
            ],
            "footer": ["Всего", str(count), "", "", "", ""],
        }
        out: dict[str, Any] = {
            "source": "orders#show_repair_orders",
            "group_by": "list",
            "count": count,
            "crm_record_total": crm_count,
            "listed": len(orders),
            "orders": orders,
            "filters": resolved,
            "crm_params": crm_params,
            "complete": complete,
            "method": "crm_filtered_list",
            "note": note,
            "table": table,
            "tables": [table],
        }
        if date_from:
            out["date_from"] = date_from
        if date_to:
            out["date_to"] = date_to
        return out

    async def repair_orders(
        self,
        *,
        ranges: list[dict[str, str]] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        group_by: str = "auto",
        filters: dict[str, Any] | None = None,
        max_sample: int = 20,
    ) -> dict[str, Any]:
        """Repair orders from /orders#show_repair_orders (not cashboxes)."""
        from modules.gincore.charts import month_comparison_chart, month_comparison_table
        from modules.gincore.repair_filters import build_crm_params, filter_orders_local

        today = date.today()
        filters = dict(filters or {})
        staff = await self.load_repair_staff_options()
        crm_params, resolved, post_filters = build_crm_params(
            filters=filters, staff=staff
        )
        has_crm_filters = bool(crm_params) or bool(post_filters)
        snapshot = bool(
            filters.get("current")
            or filters.get("status")
            or post_filters
            or any(
                filters.get(k)
                for k in (
                    "engineer",
                    "manager",
                    "accepter",
                    "location",
                    "department",
                    "branch",
                    "repair_type",
                    "repair",
                    "person",
                    "other",
                    "client",
                    "order_id",
                    "device",
                    "defect",
                    "channel",
                )
            )
        )

        gb = (group_by or "auto").lower()

        # Filtered snapshot (no period required): current / status / staff / location / …
        if snapshot and not ranges and not (date_from and date_to):
            if gb == "auto":
                gb = "list" if post_filters or filters.get("current") or filters.get(
                    "status"
                ) else "total"
            if gb == "month":
                raise GincoreError(
                    "Для snapshot-фильтров (current/status/…) group_by=month не подходит — "
                    "используй total или list, либо задай period."
                )

            need_rows = gb == "list" or bool(post_filters)
            limit = max(max_sample, 250 if post_filters else max_sample)
            if need_rows:
                crm_count, orders = await self._collect_repair_orders(
                    date_from=None,
                    date_to=None,
                    crm_params=crm_params,
                    limit=limit,
                )
                if post_filters:
                    orders = filter_orders_local(orders, post_filters)
                    # If CRM returned more than we scanned, say so.
                    complete = crm_count <= limit or len(orders) < limit
                    count = len(orders) if complete or post_filters else crm_count
                    if post_filters and crm_count > limit:
                        note = (
                            f"Пост-фильтр {post_filters}: просмотрено до {limit} из "
                            f"{crm_count} CRM-строк. Для точного итога сузь CRM-фильтры "
                            f"(current/status/location)."
                        )
                        count = len(orders)
                        complete = False
                    else:
                        count = len(orders)
                        complete = True
                        note = "Список с CRM-фильтрами" + (
                            f" + пост-фильтр {post_filters}" if post_filters else ""
                        )
                else:
                    count = crm_count
                    complete = len(orders) >= min(crm_count, limit)
                    note = "Список ремонтов с фильтрами CRM."
                title = "Ремонты"
                bits = [str(v) for k, v in resolved.items() if k != "current"]
                if resolved.get("current"):
                    bits.insert(0, "сейчас")
                if bits:
                    title += " · " + ", ".join(bits[:4])
                if gb == "total" and not post_filters:
                    # fall through to total using crm_count
                    pass
                else:
                    if gb == "total" and post_filters:
                        table = {
                            "title": title,
                            "columns": ["Фильтр", "Кол-во"],
                            "rows": [[title, str(count)]],
                            "footer": ["Итого", str(count)],
                        }
                        return {
                            "source": "orders#show_repair_orders",
                            "group_by": "total",
                            "count": count,
                            "crm_record_total": crm_count,
                            "filters": resolved,
                            "crm_params": crm_params,
                            "complete": complete,
                            "method": "crm_filtered_total_post",
                            "note": note,
                            "table": table,
                            "tables": [table],
                        }
                    return self._repair_list_result(
                        orders=orders[:max_sample] if gb == "list" else orders,
                        count=count,
                        crm_count=crm_count,
                        resolved=resolved,
                        crm_params=crm_params,
                        title=title,
                        note=note,
                        complete=complete,
                    )

            meta = await self._repair_orders_count(crm_params=crm_params)
            count = meta["count"]
            title = "Ремонты"
            bits = [str(v) for k, v in resolved.items() if k != "current"]
            if resolved.get("current"):
                bits.insert(0, "сейчас")
            if bits:
                title += " · " + ", ".join(bits[:4])
            table = {
                "title": title,
                "columns": ["Фильтр", "Кол-во"],
                "rows": [[title, str(count)]],
                "footer": ["Итого", str(count)],
            }
            return {
                "source": "orders#show_repair_orders",
                "group_by": "total",
                "count": count,
                "crm_record_total": count,
                "filters": resolved,
                "crm_params": crm_params,
                "complete": True,
                "method": "crm_footer_totals",
                "note": "Итог из футера CRM с фильтрами.",
                "table": table,
                "tables": [table],
            }

        if not ranges:
            if not date_from or not date_to:
                raise GincoreError(
                    "Нужен период для ремонтов (или current=true / status / другие фильтры)"
                )
            ranges = [{"date_from": date_from, "date_to": date_to, "label": date_from[:4]}]

        norm: list[dict[str, str]] = []
        for r in ranges:
            df, dt = r["date_from"], r["date_to"]
            end = datetime.strptime(dt, "%Y-%m-%d").date()
            if end > today:
                dt = today.isoformat()
            norm.append(
                {
                    "date_from": df,
                    "date_to": dt,
                    "label": str(r.get("label") or df[:4]),
                }
            )
        ranges = norm
        date_from, date_to = ranges[0]["date_from"], ranges[0]["date_to"]
        start = datetime.strptime(date_from, "%Y-%m-%d").date()
        end = datetime.strptime(date_to, "%Y-%m-%d").date()
        span_days = (end - start).days + 1

        if len(ranges) > 1 and gb in {"auto", "month"}:
            gb = "month"
        if gb == "auto":
            if span_days <= 1:
                gb = "list"
            elif span_days >= 28 or start.month != end.month or start.year != end.year:
                gb = "month"
            else:
                gb = "total"

        if gb == "month":
            if post_filters:
                raise GincoreError(
                    "Пост-фильтр channel нельзя с group_by=month — используй current=true + total/list"
                )
            series_out: list[dict[str, Any]] = []
            for r in ranges:
                parts = await self._repair_month_parts(
                    r["date_from"], r["date_to"], crm_params=crm_params
                )
                total = sum(p["count"] for p in parts)
                series_out.append(
                    {
                        "label": r["label"],
                        "year": r["label"],
                        "date_from": r["date_from"],
                        "date_to": r["date_to"],
                        "months": parts,
                        "count": total,
                    }
                )

            if len(series_out) == 1:
                parts = series_out[0]["months"]
                labels = [p["label"] for p in parts]
                counts = [p["count"] for p in parts]
                total = series_out[0]["count"]
                chart = {
                    "type": "bar",
                    "title": "Принято в ремонт по месяцам",
                    "labels": labels,
                    "datasets": [
                        {
                            "label": series_out[0]["label"],
                            "data": counts,
                            "backgroundColor": "rgba(21, 101, 192, 0.75)",
                            "borderColor": "#1565c0",
                        }
                    ],
                }
                table = {
                    "title": "Принято в ремонт по месяцам",
                    "columns": ["Месяц", "Кол-во"],
                    "rows": [[p["label"], str(p["count"])] for p in parts],
                    "footer": ["Итого", str(total)],
                }
                return {
                    "source": "orders#show_repair_orders",
                    "date_from": date_from,
                    "date_to": date_to,
                    "group_by": "month",
                    "count": total,
                    "months": parts,
                    "series": series_out,
                    "filters": resolved,
                    "crm_params": crm_params,
                    "complete": True,
                    "method": "crm_footer_per_month",
                    "note": "Помесячные итоги из футера списка ремонтов.",
                    "chart": chart,
                    "charts": [chart],
                    "table": table,
                    "tables": [table],
                }

            chart = month_comparison_chart(
                series_out,
                title="Сравнение приёмов в ремонт по месяцам",
                metric="count",
            )
            table = month_comparison_table(
                series_out,
                title="Сравнение приёмов в ремонт по месяцам",
                metric="count",
                unit="шт",
            )
            return {
                "source": "orders#show_repair_orders",
                "group_by": "month",
                "complete": True,
                "method": "crm_footer_per_month_series",
                "series": series_out,
                "count": series_out[0]["count"],
                "filters": resolved,
                "crm_params": crm_params,
                "totals_by_series": [
                    {"label": s["label"], "count": s["count"]} for s in series_out
                ],
                "note": f"Сравнение {len(series_out)} периодов · приём в ремонт",
                "chart": chart,
                "charts": [chart],
                "table": table,
                "tables": [table],
            }

        if post_filters or gb == "list":
            limit = max(max_sample, 250 if post_filters else max_sample)
            crm_count, orders = await self._collect_repair_orders(
                date_from=date_from,
                date_to=date_to,
                crm_params=crm_params,
                limit=limit,
            )
            if post_filters:
                orders = filter_orders_local(orders, post_filters)
                count = len(orders)
                complete = crm_count <= limit
                note = "Список за период с фильтрами" + (
                    f" + пост-фильтр {post_filters}" if post_filters else ""
                )
            else:
                count = crm_count
                complete = len(orders) >= min(crm_count, limit)
                note = "Список ремонтов (sample). Итог count — из футера CRM."
            title = f"Ремонты {date_from} — {date_to}"
            if resolved:
                title += " · " + ", ".join(str(v) for v in list(resolved.values())[:3])
            return self._repair_list_result(
                orders=orders[:max_sample],
                count=count,
                crm_count=crm_count,
                resolved=resolved,
                crm_params=crm_params,
                title=title,
                note=note,
                date_from=date_from,
                date_to=date_to,
                complete=complete,
            )

        meta = await self._repair_orders_count(
            date_from=date_from, date_to=date_to, crm_params=crm_params
        )
        count = meta["count"]
        title = f"Ремонты {date_from} — {date_to}"
        if resolved:
            title += " · " + ", ".join(str(v) for v in list(resolved.values())[:3])
        table = {
            "title": title,
            "columns": ["Период", "Кол-во"],
            "rows": [[f"{date_from} — {date_to}", str(count)]],
            "footer": ["Итого", str(count)],
        }
        return {
            "source": "orders#show_repair_orders",
            "date_from": date_from,
            "date_to": date_to,
            "group_by": "total",
            "count": count,
            "crm_record_total": count,
            "filters": resolved,
            "crm_params": crm_params,
            "complete": True,
            "method": "crm_footer_totals",
            "note": "Итог из футера /orders (без выгрузки всех строк).",
            "table": table,
            "tables": [table],
        }

    async def _repair_month_parts(
        self,
        date_from: str,
        date_to: str,
        *,
        crm_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        months_spec = months_in_range(date_from, date_to)
        sem = asyncio.Semaphore(PAGE_CONCURRENCY)
        ru_labels = [
            "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
            "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
        ]

        async def one(y: int, m: int, df: str, dt: str) -> dict[str, Any]:
            async with sem:
                meta = await self._repair_orders_count(
                    date_from=df, date_to=dt, crm_params=crm_params
                )
                return {
                    "month": m,
                    "year": y,
                    "label": f"{ru_labels[m - 1]} {y}",
                    "key": f"{y:04d}-{m:02d}",
                    "date_from": df,
                    "date_to": dt,
                    "count": meta["count"],
                }

        return list(
            await asyncio.gather(*[one(y, m, df, dt) for y, m, df, dt in months_spec])
        )

    async def day_transactions(self, *, day: str | None = None) -> dict[str, Any]:
        """Summary + transaction list for one day (today by default)."""
        day_iso = day or date.today().isoformat()
        return await self.query(
            ranges=[{"date_from": day_iso, "date_to": day_iso, "label": day_iso}],
            group_by="list",
        )

    async def analytics_summary(self, *, date_from: str, date_to: str) -> dict[str, Any]:
        """Period summary via CRM footers. Monthly charts only for multi-month spans."""
        start = datetime.strptime(date_from, "%Y-%m-%d").date()
        end = datetime.strptime(date_to, "%Y-%m-%d").date()
        span_days = (end - start).days + 1

        if span_days <= 1:
            return await self.day_transactions(day=date_from)

        _rows, _pages, overall = await self.fetch_transactions_page(
            date_from=date_from, date_to=date_to, page=1
        )
        income_total = float(overall.get("footer_income_total") or 0)
        expense_total = float(overall.get("footer_expense_total") or 0)
        record_total = overall.get("record_total")

        categories = await self.list_categories()
        expense_cats = [
            c
            for c in categories
            if "↓" in c["name"] or "расход" in c["name"].lower() or "зарплат" in c["name"].lower()
        ]
        if not expense_cats:
            expense_cats = categories

        sem = asyncio.Semaphore(PAGE_CONCURRENCY)

        async def one(cat: dict[str, str]) -> dict[str, Any]:
            async with sem:
                total = await self.category_period_total(
                    category_id=cat["id"], date_from=date_from, date_to=date_to
                )
                return {
                    "category": cat["name"].lstrip("↓↑- ").strip(),
                    "category_id": cat["id"],
                    "expense_total": total["expense_total"],
                    "income_total": total["income_total"],
                    "record_total": total["record_total"],
                }

        breakdown = await asyncio.gather(*[one(c) for c in expense_cats])
        top = sorted(
            [b for b in breakdown if (b["expense_total"] or 0) > 0],
            key=lambda x: x["expense_total"],
            reverse=True,
        )[:12]

        palette = [
            "rgba(15, 110, 86, 0.8)",
            "rgba(198, 40, 40, 0.7)",
            "rgba(21, 101, 192, 0.7)",
            "rgba(245, 124, 0, 0.75)",
            "rgba(123, 31, 162, 0.7)",
            "rgba(0, 121, 107, 0.7)",
            "rgba(183, 28, 28, 0.65)",
            "rgba(69, 90, 100, 0.7)",
            "rgba(46, 125, 50, 0.7)",
            "rgba(239, 108, 0, 0.7)",
        ]
        top_chart = {
            "type": "bar",
            "title": f"Топ статей расходов {date_from} — {date_to}",
            "labels": [t["category"][:32] for t in top[:10]],
            "datasets": [
                {
                    "label": "Расход",
                    "data": [t["expense_total"] for t in top[:10]],
                    "backgroundColor": palette[: len(top[:10])],
                    "borderColor": palette[: len(top[:10])],
                }
            ],
        }

        charts: list[dict[str, Any]] = [top_chart]
        by_month = None
        if span_days >= 28 and (start.month != end.month or start.year != end.year or span_days >= 60):
            monthly = await self.analytics_by_month(year=start.year)
            by_month = monthly["months"]
            charts = [monthly["charts"][0], monthly["charts"][1], top_chart]

        return {
            "date_from": date_from,
            "date_to": date_to,
            "crm_record_total": record_total,
            "income_total": income_total,
            "expense_total": expense_total,
            "net": round(income_total - expense_total, 2),
            "complete": True,
            "method": "crm_footer_totals",
            "note": (
                "Итоги из футера Gincore. Топ статей — фильтр по каждой статье. "
                + (
                    "Помесячные графики добавлены для длинного периода."
                    if by_month
                    else "Для помесячной динамики вызови gincore_analytics_by_month."
                )
            ),
            "by_month": by_month,
            "top_expense_categories": [
                {
                    "category": t["category"],
                    "expense_total": t["expense_total"],
                    "record_total": t["record_total"],
                }
                for t in top
            ],
            "chart": charts[0],
            "charts": charts,
        }
