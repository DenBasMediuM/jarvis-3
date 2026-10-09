from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.config import WEB_DIR, settings
from core.crypto import SecretBox
from core.db import Database
from core.llm import LLMService
from modules import load_modules
from modules.base import BaseModule, ToolSpec
from modules.cash_journal.parser import is_parts_attach_line
from modules.gincore.module import GincoreModule
from core.telegram import send_telegram_messages, telegram_configured
from modules.gincore.quality import QualityService, compute_quality_metrics
from modules.gincore.quality_tg import format_quality_analysis_tg_blocks
from modules.vyrobotka.service import VyrobotkaService


db = Database(settings.resolved_db_path())
secrets = SecretBox(settings.resolved_secret_key_path())
modules: list[BaseModule] = []
gincore_module: GincoreModule | None = None
quality_service: QualityService | None = None
vyrobotka_service: VyrobotkaService | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: int | None = None


class ModuleSettingsUpdate(BaseModel):
    values: dict[str, Any]


class AppSettingsUpdate(BaseModel):
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None


class CashJournalImportPreview(BaseModel):
    amount: float
    action: str
    order_id: str | None = None
    line_id: str | None = None
    cashbox_id: str | None = None
    note: str | None = None


class CashJournalImportAccept(BaseModel):
    amount: float
    cashbox_id: str | None = None
    kind: str = "client_order_cash_in"
    order_id: str | None = None
    currency_id: str = "3"
    form_act: str = "pay_for_repair_form"
    transaction_type: str = "2"
    order_kind: str = "repair"
    category_id: str | None = None
    contractor_id: str | None = None
    comment: str | None = None
    without_contractor: bool = False
    line_id: str | None = None
    note: str | None = None


def _module_settings_key(module_id: str) -> str:
    return f"module:{module_id}"


async def get_module_settings(module_id: str) -> dict[str, Any]:
    raw = await db.get_setting(_module_settings_key(module_id), {}) or {}
    module = next((m for m in modules if m.id == module_id), None)
    if not module:
        return raw
    out = dict(raw)
    for field in module.settings_schema():
        if field.secret and field.key in out and out[field.key]:
            try:
                out[field.key] = secrets.decrypt(out[field.key])
            except Exception:
                pass
        if field.key == "base_url" and not out.get(field.key):
            out[field.key] = settings.default_gincore_base_url
        if (
            module_id == "vyrobotka"
            and field.key == "spreadsheet_id"
            and not out.get(field.key)
        ):
            out[field.key] = "1ardPmT-a-eyFZmEk97J70aPiirlLDhoySCXlauZbT-c"
        if field.key == "enabled" and field.key not in out:
            out[field.key] = True
    return out


async def public_module_settings(module_id: str) -> dict[str, Any]:
    values = await get_module_settings(module_id)
    module = next((m for m in modules if m.id == module_id), None)
    if not module:
        return values
    public = dict(values)
    for field in module.settings_schema():
        if field.secret and public.get(field.key):
            public[field.key] = "********"
    return public


def collect_tools() -> list[ToolSpec]:
    tools: list[ToolSpec] = []
    for module in modules:
        tools.extend(module.tools())
    return tools


async def build_llm() -> LLMService:
    app_cfg = await db.get_setting("app", {}) or {}
    return LLMService(
        base_url=app_cfg.get("llm_base_url") or settings.llm_base_url,
        api_key=app_cfg.get("llm_api_key") or settings.llm_api_key,
        model=app_cfg.get("llm_model") or settings.llm_model,
        tools=collect_tools(),
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    global modules, gincore_module, quality_service, vyrobotka_service
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    await db.connect()
    modules = load_modules()
    gincore_module = next((m for m in modules if isinstance(m, GincoreModule)), None)
    if gincore_module is not None:
        mod = gincore_module
        mod.bind_settings_provider(lambda: getattr(mod, "_cached_settings", {}))

    async def _quality_client():
        client = await _gincore_client()
        await client.ensure_login()
        return client

    quality_service = QualityService(db, _quality_client)

    async def _vyrobotka_gincore():
        client = await _gincore_client()
        await client.ensure_login()
        return client

    vyrobotka_service = VyrobotkaService(
        db,
        lambda: get_module_settings("vyrobotka"),
        gincore_client_factory=_vyrobotka_gincore,
    )
    yield
    await db.close()


app = FastAPI(title="Jarvis", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        WEB_DIR / "index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "modules": [m.id for m in modules]}


@app.get("/api/modules")
async def list_modules() -> dict[str, Any]:
    items = []
    for module in modules:
        items.append(
            {
                "id": module.id,
                "name": module.name,
                "description": module.description,
                "settings": [
                    {
                        "key": f.key,
                        "label": f.label,
                        "type": f.type,
                        "placeholder": f.placeholder,
                        "help": f.help,
                        "secret": f.secret,
                    }
                    for f in module.settings_schema()
                ],
                "values": await public_module_settings(module.id),
            }
        )
    return {"modules": items}


@app.put("/api/modules/{module_id}/settings")
async def update_module_settings(module_id: str, body: ModuleSettingsUpdate) -> dict[str, Any]:
    module = next((m for m in modules if m.id == module_id), None)
    if not module:
        raise HTTPException(404, "Module not found")

    current = await get_module_settings(module_id)
    schema = {f.key: f for f in module.settings_schema()}
    merged = dict(current)

    for key, value in body.values.items():
        field = schema.get(key)
        if not field:
            continue
        if field.secret and (value in (None, "", "********")):
            continue
        if field.type == "checkbox":
            merged[key] = bool(value)
        else:
            merged[key] = value

    stored = dict(merged)
    for field in module.settings_schema():
        if field.secret and stored.get(field.key):
            stored[field.key] = secrets.encrypt(str(stored[field.key]))

    await db.set_setting(_module_settings_key(module_id), stored)
    await module.on_settings_saved(merged)
    return {"ok": True, "values": await public_module_settings(module_id)}


@app.post("/api/modules/gincore/test")
async def test_gincore() -> dict[str, Any]:
    if not gincore_module:
        raise HTTPException(404, "Gincore module missing")
    cfg = await get_module_settings("gincore")
    gincore_module._cached_settings = cfg
    try:
        result = await gincore_module._test_connection({})
        return {"ok": True, "result": result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@app.post("/api/modules/vyrobotka/test")
async def test_vyrobotka() -> dict[str, Any]:
    """Проверить доступ service account к Google Таблице модуля «Выработка»."""
    from modules.vyrobotka.module import VyrobotkaModule
    from modules.vyrobotka.sheets import SheetsError

    module = next((m for m in modules if isinstance(m, VyrobotkaModule)), None)
    if not module:
        raise HTTPException(404, "Модуль «Выработка» не найден")
    cfg = await get_module_settings("vyrobotka")
    try:
        result = await module.test_connection(cfg)
        return result
    except SheetsError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@app.get("/api/vyrobotka/stats")
async def vyrobotka_stats() -> dict[str, Any]:
    if not vyrobotka_service:
        raise HTTPException(503, "Сервис Выработка не готов")
    return await vyrobotka_service.get_stats()


@app.get("/api/vyrobotka/sync")
async def vyrobotka_sync_status() -> dict[str, Any]:
    if not vyrobotka_service:
        raise HTTPException(503, "Сервис Выработка не готов")
    return {"ok": True, "sync": await db.vyrobotka_get_sync_state()}


@app.post("/api/vyrobotka/sync")
async def vyrobotka_sync_start() -> dict[str, Any]:
    if not vyrobotka_service:
        raise HTTPException(503, "Сервис Выработка не готов")
    try:
        return await vyrobotka_service.start_sync()
    except Exception as exc:  # noqa: BLE001
        from modules.vyrobotka.sheets import SheetsError

        if isinstance(exc, SheetsError):
            raise HTTPException(400, str(exc)) from exc
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/vyrobotka/debt-verify")
async def vyrobotka_debt_verify_status() -> dict[str, Any]:
    if not vyrobotka_service:
        raise HTTPException(503, "Сервис Выработка не готов")
    return {"ok": True, "verify": await vyrobotka_service.get_debt_verify()}


class DebtVerifyStartBody(BaseModel):
    mode: str = Field(default="all", description="all | new")


@app.post("/api/vyrobotka/debt-verify")
async def vyrobotka_debt_verify_start(
    body: DebtVerifyStartBody = Body(default_factory=DebtVerifyStartBody),
) -> dict[str, Any]:
    if not vyrobotka_service:
        raise HTTPException(503, "Сервис Выработка не готов")
    mode = body.mode or "all"
    try:
        return await vyrobotka_service.start_debt_verify(mode=mode)
    except Exception as exc:  # noqa: BLE001
        from modules.vyrobotka.sheets import SheetsError

        if isinstance(exc, SheetsError):
            raise HTTPException(400, str(exc)) from exc
        raise HTTPException(500, str(exc)) from exc


@app.post("/api/vyrobotka/debt-verify/cancel")
async def vyrobotka_debt_verify_cancel() -> dict[str, Any]:
    if not vyrobotka_service:
        raise HTTPException(503, "Сервис Выработка не готов")
    return {"ok": True, "verify": await vyrobotka_service.cancel_debt_verify()}


@app.post("/api/vyrobotka/export-pages")
async def vyrobotka_export_pages() -> dict[str, Any]:
    """Записать docs/vyrobotka/data.json для GitHub Pages (без push)."""
    if not vyrobotka_service:
        raise HTTPException(503, "Сервис Выработка не готов")
    try:
        return await vyrobotka_service.export_pages_snapshot()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc


async def _gincore_client():
    if not gincore_module:
        raise HTTPException(404, "Модуль Gincore не найден")
    cfg = await get_module_settings("gincore")
    gincore_module._cached_settings = cfg
    try:
        return gincore_module._client()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/cash-journal/import/preview")
async def cash_journal_import_preview(body: CashJournalImportPreview) -> dict[str, Any]:
    """Preview CRM form for the next journal line (payment, expense, or parts attach)."""
    client = await _gincore_client()
    try:
        if body.action in ("cash_in", "card_in") and body.order_id:
            preview = await client.get_order_payment_preview(body.order_id)
            pay_form = await client.begin_client_order_payment(body.order_id, body.amount)
            boxes = await client.list_cashboxes()
            by_id = {str(b.get("id")): b for b in boxes if b.get("id")}
            cashboxes = []
            for cb in pay_form.get("cashboxes") or []:
                extra = by_id.get(str(cb["id"])) or {}
                cashboxes.append({**cb, "total_uah": extra.get("total_uah")})
            return {
                "ok": True,
                "kind": "client_order_cash_in",
                "line_id": body.line_id,
                "amount": body.amount,
                "action": body.action,
                "order": preview,
                "payment_form": {**pay_form, "cashboxes": cashboxes},
            }

        if body.action == "cash_out" and body.order_id:
            if not is_parts_attach_line(
                {
                    "action": body.action,
                    "order_id": body.order_id,
                    "raw": body.note or "",
                    "note": body.note or "",
                }
            ):
                raise HTTPException(
                    400,
                    "Эта строка «из кассы» с номером — не привязка запчасти "
                    "(нужен вид «123956 -256 …»)",
                )
            preview = await client.preview_parts_attach(
                body.order_id,
                body.amount,
                note=body.note or "",
            )
            return {
                **preview,
                "line_id": body.line_id,
                "action": body.action,
            }

        if body.action == "cash_out" and not body.order_id:
            expense = await client.begin_cashbox_expense(body.cashbox_id)
            boxes = await client.list_cashboxes()
            by_id = {str(b.get("id")): b for b in boxes if b.get("id")}
            cashboxes = []
            for cb in expense.get("cashboxes") or []:
                extra = by_id.get(str(cb["id"])) or {}
                cashboxes.append({**cb, "total_uah": extra.get("total_uah")})
            preferred = body.cashbox_id or expense.get("selected_cashbox_id")
            if preferred and any(str(c["id"]) == str(preferred) for c in cashboxes):
                selected = str(preferred)
            else:
                selected = expense.get("selected_cashbox_id")
            return {
                "ok": True,
                "kind": "cashbox_expense",
                "line_id": body.line_id,
                "amount": body.amount,
                "note": body.note or "",
                "expense_form": {
                    **expense,
                    "cashboxes": cashboxes,
                    "selected_cashbox_id": selected,
                },
            }

        raise HTTPException(
            400,
            "Поддерживается: «в кассу»/«в карту» с квитанцией, "
            "«из кассы» без заказа (расход) или «из кассы» с номером "
            "(привязка запчасти)",
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc
    finally:
        await client.aclose()


@app.get("/api/cash-journal/import/contractors")
async def cash_journal_import_contractors(category_id: str) -> dict[str, Any]:
    client = await _gincore_client()
    try:
        items = await client.list_contractors_by_category(category_id)
        return {"ok": True, "category_id": category_id, "contractors": items}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc
    finally:
        await client.aclose()


@app.post("/api/cash-journal/import/accept")
async def cash_journal_import_accept(body: CashJournalImportAccept) -> dict[str, Any]:
    """Accept payment, cash expense, or spare-parts attach into CRM."""
    client = await _gincore_client()
    try:
        if body.kind == "parts_attach":
            if not body.order_id:
                raise HTTPException(400, "Нужен order_id для привязки запчасти")
            result = await client.attach_spare_part(
                body.order_id,
                body.amount,
                note=body.note or body.comment or "",
            )
            return {**result, "line_id": body.line_id}

        if body.kind == "cashbox_expense":
            if not body.cashbox_id:
                raise HTTPException(400, "Выберите кассу")
            if not body.category_id:
                raise HTTPException(400, "Выберите статью расхода")
            if not body.contractor_id and not body.without_contractor:
                raise HTTPException(400, "Выберите контрагента")
            result = await client.create_cashbox_expense(
                cashbox_id=body.cashbox_id,
                amount=body.amount,
                category_id=body.category_id,
                contractor_id=body.contractor_id,
                comment=body.comment or "",
                currency_id=body.currency_id,
                without_contractor=body.without_contractor,
            )
            return {**result, "line_id": body.line_id}

        if not body.order_id:
            raise HTTPException(400, "Нужен order_id для оплаты по квитанции")
        if not body.cashbox_id:
            raise HTTPException(400, "Выберите кассу")
        result = await client.accept_client_order_payment(
            body.order_id,
            cashbox_id=body.cashbox_id,
            amount=body.amount,
            currency_id=body.currency_id,
            order_kind=body.order_kind,
            form_act=body.form_act,
            transaction_type=body.transaction_type,
            issued=False,
        )
        return {**result, "line_id": body.line_id, "kind": "client_order_cash_in"}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc
    finally:
        await client.aclose()


@app.get("/api/settings")
async def get_app_settings() -> dict[str, Any]:
    app_cfg = await db.get_setting("app", {}) or {}
    return {
        "llm_base_url": app_cfg.get("llm_base_url") or settings.llm_base_url,
        "llm_api_key": "********" if (app_cfg.get("llm_api_key") or settings.llm_api_key) else "",
        "llm_model": app_cfg.get("llm_model") or settings.llm_model,
        "has_api_key": bool(app_cfg.get("llm_api_key") or settings.llm_api_key),
    }


@app.put("/api/settings")
async def update_app_settings(body: AppSettingsUpdate) -> dict[str, Any]:
    app_cfg = await db.get_setting("app", {}) or {}
    if body.llm_base_url is not None:
        app_cfg["llm_base_url"] = body.llm_base_url.strip()
    if body.llm_model is not None:
        app_cfg["llm_model"] = body.llm_model.strip()
    if body.llm_api_key is not None and body.llm_api_key not in ("", "********"):
        app_cfg["llm_api_key"] = body.llm_api_key
    await db.set_setting("app", app_cfg)
    return await get_app_settings()


class QualitySyncRequest(BaseModel):
    force: bool = False


def _quality_base_url() -> str:
    base = settings.default_gincore_base_url
    return base.rstrip("/") if base else ""


async def _quality_order_url(order_id: str) -> str:
    base = _quality_base_url()
    if gincore_module is not None:
        cfg = await get_module_settings("gincore")
        base = (cfg.get("base_url") or base).rstrip("/")
    return f"{base}/orders/{order_id}"


@app.get("/api/quality/orders")
async def quality_orders() -> dict[str, Any]:
    if not quality_service:
        raise HTTPException(503, "Сервис качества не готов")
    data = await quality_service.list_rows()
    for row in data.get("orders") or []:
        oid = row.get("order_id")
        if oid:
            row["url"] = await _quality_order_url(str(oid))
    return data


@app.get("/api/quality/orders/{order_id}")
async def quality_order_detail(order_id: str) -> dict[str, Any]:
    """Cached order row + full live feed from local DB (no CRM call)."""
    if not quality_service:
        raise HTTPException(503, "Сервис качества не готов")
    row = await db.quality_get_order(str(order_id))
    if not row:
        raise HTTPException(404, f"Заказ {order_id} не найден в кэше")
    feed: list[Any] = []
    if row.get("feed_json"):
        try:
            feed = json.loads(row["feed_json"])
        except json.JSONDecodeError:
            feed = []
    metrics = compute_quality_metrics(
        accepted_at=row.get("accepted_at"),
        repair_cost=row.get("repair_cost"),
        feed=feed,
        engineer=row.get("engineer"),
        status=row.get("status"),
    )
    # Newest first for reading (stored chronological).
    feed_view = list(reversed(feed)) if feed else []
    return {
        "ok": True,
        "order": {
            "order_id": row["order_id"],
            "status": row.get("status"),
            "engineer": row.get("engineer"),
            "device": row.get("device"),
            "client": row.get("client"),
            "location": row.get("location"),
            "accepted_at": row.get("accepted_at"),
            "repair_cost": row.get("repair_cost"),
            "feed_synced_at": row.get("feed_synced_at"),
            "url": await _quality_order_url(str(row["order_id"])),
            "metrics": metrics,
            "feed": feed_view,
            "feed_count": len(feed_view),
        },
    }


@app.post("/api/quality/calc/{order_id}")
async def quality_calc(order_id: str) -> dict[str, Any]:
    """Подтянуть квитанцию из CRM и посчитать KPI (в т.ч. закрытые / вне кэша)."""
    if not quality_service:
        raise HTTPException(503, "Сервис качества не готов")
    try:
        data = await quality_service.calc_order(str(order_id))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    feed = data.get("feed") or []
    feed_view = list(reversed(feed)) if feed else []
    return {
        "ok": True,
        "source": "crm",
        "order": {
            "order_id": data.get("order_id"),
            "status": data.get("status"),
            "engineer": data.get("engineer"),
            "device": data.get("device"),
            "client": data.get("client"),
            "location": data.get("location"),
            "accepted_at": data.get("accepted_at"),
            "repair_cost": data.get("repair_cost"),
            "feed_synced_at": data.get("feed_synced_at"),
            "url": await _quality_order_url(str(data.get("order_id") or order_id)),
            "metrics": data.get("metrics") or {},
            "feed": feed_view,
            "feed_count": len(feed_view),
        },
    }


@app.get("/api/quality/daily-stats")
async def quality_daily_stats() -> dict[str, Any]:
    """История средних метрик по дням (точки только за дни с обновлением из CRM)."""
    if not quality_service:
        raise HTTPException(503, "Сервис качества не готов")
    rows = await quality_service.daily_stats(limit=730)
    return {"ok": True, "days": rows, "count": len(rows)}


@app.get("/api/quality/analysis")
async def quality_analysis() -> dict[str, Any]:
    """Последний сохранённый разбор (пересобирается после sync из CRM)."""
    if not quality_service:
        raise HTTPException(503, "Сервис качества не готов")
    data = await quality_service.get_analysis()
    if not data:
        # Есть кэш заказов, но анализ ещё не писали — собрать без CRM.
        listed = await quality_service.list_rows()
        if listed.get("orders"):
            data = await quality_service.rebuild_analysis()
        else:
            return {"ok": True, "analysis": None, "message": "Анализа ещё нет — обновите из CRM"}
    for item in data.get("urgent") or []:
        oid = item.get("order_id")
        if oid and not item.get("url"):
            item["url"] = await _quality_order_url(str(oid))
    return {"ok": True, "analysis": data}


@app.post("/api/quality/export-pages")
async def quality_export_pages() -> dict[str, Any]:
    """Записать docs/quality/data.json для GitHub Pages (без push)."""
    if not quality_service:
        raise HTTPException(503, "Сервис качества не готов")
    try:
        return await quality_service.export_pages_snapshot(
            order_base_url=_quality_base_url()
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc


@app.post("/api/quality/analysis/telegram")
async def quality_analysis_telegram() -> dict[str, Any]:
    """Отправить сокращённый текущий анализ в Telegram (блок = отдельное сообщение)."""
    if not quality_service:
        raise HTTPException(503, "Сервис качества не готов")
    if not telegram_configured():
        raise HTTPException(
            400,
            "Telegram не настроен. В файле .env в корне jarvis-3 укажите:\n"
            "JARVIS_TELEGRAM_BOT_TOKEN=токен_от_BotFather\n"
            "JARVIS_TELEGRAM_CHAT_ID=id_чата\n"
            "Затем перезапустите сервер.",
        )
    data = await quality_service.get_analysis()
    if not data:
        listed = await quality_service.list_rows()
        if listed.get("orders"):
            data = await quality_service.rebuild_analysis()
    if not data or not data.get("orders_count"):
        raise HTTPException(400, "Анализа ещё нет — сначала обновите из CRM")
    base = _quality_base_url()
    for item in data.get("urgent") or []:
        oid = item.get("order_id")
        if oid and not item.get("url"):
            item["url"] = await _quality_order_url(str(oid))
    blocks = format_quality_analysis_tg_blocks(data, order_base_url=base)
    try:
        sent = await send_telegram_messages(blocks)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "sent": sent, "blocks": len(blocks)}


@app.get("/api/quality/sync")
async def quality_sync_status() -> dict[str, Any]:
    if not quality_service:
        raise HTTPException(503, "Сервис качества не готов")
    return {"ok": True, "sync": await db.quality_get_sync_state()}


@app.post("/api/quality/sync")
async def quality_sync_start(body: QualitySyncRequest | None = None) -> dict[str, Any]:
    if not quality_service:
        raise HTTPException(503, "Сервис качества не готов")
    force = bool(body.force) if body else False
    try:
        return await quality_service.start_sync(force=force)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/conversations")
async def conversations() -> dict[str, Any]:
    return {"conversations": await db.list_conversations()}


@app.get("/api/conversations/{conversation_id}/messages")
async def conversation_messages(conversation_id: int) -> dict[str, Any]:
    return {"messages": await db.list_messages(conversation_id)}


@app.post("/api/chat")
async def chat(body: ChatRequest) -> dict[str, Any]:
    conversation_id = await db.ensure_conversation(body.conversation_id)
    await db.add_message(conversation_id, "user", body.message)

    if gincore_module is not None:
        gincore_module._cached_settings = await get_module_settings("gincore")

    history_rows = await db.list_messages(conversation_id)
    messages = [
        {"role": row["role"], "content": row["content"]}
        for row in history_rows
        if row["role"] in {"user", "assistant"}
    ]

    llm = await build_llm()
    try:
        result = await llm.chat(messages)
    except Exception as exc:  # noqa: BLE001
        err = f"Ошибка LLM: {exc}"
        await db.add_message(conversation_id, "assistant", err, meta={"error": True})
        raise HTTPException(502, err) from exc

    await db.add_message(
        conversation_id,
        "assistant",
        result["content"],
        meta={
            "tool_traces": result.get("tool_traces"),
            "charts": result.get("charts"),
            "tables": result.get("tables"),
            "cash_journals": result.get("cash_journals"),
        },
    )
    return {
        "conversation_id": conversation_id,
        "message": result["content"],
        "charts": result.get("charts") or [],
        "tables": result.get("tables") or [],
        "cash_journals": result.get("cash_journals") or [],
        "tool_traces": result.get("tool_traces") or [],
    }


def create_app() -> FastAPI:
    return app
