"""Синхронизация и агрегаты «КПД мастеров»."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable

from modules.masters_kpi.config import (
    DUBOVOY_FOLDER_ID,
    FOCUS_SURNAMES,
    MASTER_META,
    ROOT_FOLDER_ID,
    SKIP_FOLDER_NAMES,
    SKIP_SURNAMES,
    SURNAME_TO_KEY,
    ZNAYDENOV_SPREADSHEET_ID,
)
from modules.masters_kpi.drive import (
    MIME_SHEET,
    MastersDriveClient,
    MastersDriveError,
)
from modules.masters_kpi.parse import (
    aggregate_weeks,
    apply_ready_fallback,
    compute_kpi,
    date_from_report_name,
    in_chart_window,
    is_copy_or_template_name,
    master_key_from_name,
    parse_report_rows,
)

SettingsFactory = Callable[[], Awaitable[dict[str, Any]]]


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def surname_of(name: str) -> str:
    parts = (name or "").strip().split()
    if not parts:
        return ""
    return parts[0].casefold().replace("ё", "е")


def resolve_active_master_keys(crm_engineers: list[str]) -> set[str]:
    """Ключи мастеров: focus-набор ∩ Drive + CRM-активные (кроме skip)."""
    keys: set[str] = set()
    for eng in crm_engineers:
        s = surname_of(eng)
        if not s or s in SKIP_SURNAMES:
            continue
        key = SURNAME_TO_KEY.get(s) or SURNAME_TO_KEY.get(eng.casefold())
        if key:
            keys.add(key)
        elif s in FOCUS_SURNAMES:
            # неизвестный ключ — всё равно через folder name
            pass
    # Явный focus всегда (если есть папка — подтянем при sync)
    for s, key in SURNAME_TO_KEY.items():
        if s in FOCUS_SURNAMES:
            keys.add(key)
    return keys


class MastersKpiService:
    def __init__(self, db: Any, settings_factory: SettingsFactory) -> None:
        self.db = db
        self._settings_factory = settings_factory
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    async def _sa_json(self) -> str:
        cfg = await self._settings_factory()
        raw = cfg.get("service_account_json") or ""
        if not raw:
            raise MastersDriveError(
                "Нет service_account_json в настройках модуля «Выработка»"
            )
        return str(raw)

    async def get_sync_state(self) -> dict[str, Any]:
        return await self.db.masters_kpi_get_sync_state()

    async def get_stats(self) -> dict[str, Any]:
        masters = await self.db.masters_kpi_list_masters()
        weeks = await self.db.masters_kpi_list_weeks()
        # Подстраховка: даже старые записи в БД не показываем до 2025-W31
        weeks = [
            w
            for w in weeks
            if int(w.get("iso_year") or 0) > 2025
            or (
                int(w.get("iso_year") or 0) == 2025
                and int(w.get("iso_week") or 0) >= 31
            )
        ]
        # Карточки считаем по тому же окну, что и графики
        by_key: dict[str, list[dict[str, Any]]] = {}
        for w in weeks:
            by_key.setdefault(str(w["master_key"]), []).append(w)
        masters_out: list[dict[str, Any]] = []
        for m in masters:
            mw = by_key.get(str(m["master_key"])) or []
            if not mw:
                # Нет недель в окне — карточку всё равно покажем, но нули по периоду
                row = dict(m)
                row["work_sum"] = 0
                row["tickets"] = 0
                row["avg_ticket"] = None
                row["efficiency"] = None
                row["lines"] = 0
                masters_out.append(row)
                continue
            work = round(sum(float(x.get("work_sum") or 0) for x in mw), 2)
            tickets = int(sum(int(x.get("tickets") or 0) for x in mw))
            avg = round(work / tickets, 2) if tickets else None
            row = dict(m)
            row["work_sum"] = work
            row["tickets"] = tickets
            row["avg_ticket"] = avg
            row["efficiency"] = compute_kpi(work, tickets, avg)
            row["lines"] = int(sum(int(x.get("lines") or 0) for x in mw))
            masters_out.append(row)
        masters_out.sort(
            key=lambda x: (
                -(x.get("efficiency") or 0),
                -(x.get("work_sum") or 0),
                x.get("display_name") or "",
            )
        )
        sync = await self.get_sync_state()
        charts = build_masters_kpi_charts(masters_out, weeks)
        return {
            "ok": True,
            "sync": sync,
            "masters": masters_out,
            "weeks": weeks,
            "charts": charts,
        }

    async def start_sync(self) -> dict[str, Any]:
        if self._task and not self._task.done():
            return {
                "ok": True,
                "started": False,
                "sync": await self.get_sync_state(),
                "message": "Синхронизация уже идёт",
            }
        await self.db.masters_kpi_set_sync_state(
            status="running",
            total=0,
            done=0,
            message="Запуск…",
            started_at=_utcnow(),
            finished_at=None,
        )
        self._task = asyncio.create_task(self._run_sync())
        return {
            "ok": True,
            "started": True,
            "sync": await self.get_sync_state(),
        }

    async def _run_sync(self) -> None:
        async with self._lock:
            try:
                await self._sync_body()
            except Exception as exc:  # noqa: BLE001
                await self.db.masters_kpi_set_sync_state(
                    status="error",
                    message=str(exc)[:500],
                    finished_at=_utcnow(),
                )

    async def _crm_engineers(self) -> list[str]:
        rows = await self.db.quality_list_orders()
        names: list[str] = []
        seen: set[str] = set()
        for r in rows:
            eng = (r.get("engineer") or "").strip()
            if not eng or eng in seen:
                continue
            seen.add(eng)
            names.append(eng)
        return names

    async def _sync_body(self) -> None:
        client = MastersDriveClient(await self._sa_json())
        crm = await self._crm_engineers()
        active_keys = resolve_active_master_keys(crm)

        folders = await client.list_master_folders(ROOT_FOLDER_ID)
        folder_by_key: dict[str, dict[str, Any]] = {}
        for f in folders:
            name = f.get("name") or ""
            if name in SKIP_FOLDER_NAMES:
                continue
            key = master_key_from_name(name)
            if not key:
                continue
            if key not in active_keys and surname_of(name) not in FOCUS_SURNAMES:
                continue
            folder_by_key[key] = {
                "key": key,
                "folder_id": f["id"],
                "folder_name": name,
                "display_name": MASTER_META.get(key, {}).get("title") or name,
            }

        # Дубовой — отдельная папка
        if "dubovoy" in active_keys or "дубовой" in FOCUS_SURNAMES:
            folder_by_key["dubovoy"] = {
                "key": "dubovoy",
                "folder_id": DUBOVOY_FOLDER_ID,
                "folder_name": "Дубовой (отдельная папка)",
                "display_name": "Дубовой",
            }

        masters_plan = list(folder_by_key.values())
        # Оценка объёма: файлы
        file_jobs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for m in masters_plan:
            files = await client.list_report_files(m["folder_id"])
            for f in files:
                name = f.get("name") or ""
                if is_copy_or_template_name(name):
                    continue
                # Дубовой: много старых xlsx → берём с 2025, иначе Drive сыплет 429
                if m["key"] == "dubovoy":
                    mt = str(f.get("modifiedTime") or "")
                    if not (
                        "2025" in name
                        or "2026" in name
                        or mt.startswith("2025")
                        or mt.startswith("2026")
                    ):
                        continue
                file_jobs.append((m, f))

        # Знайденов: явная таблица (layout свой), даже если папка пустая/устарела
        if "znaydenov" in folder_by_key or "znaydenov" in active_keys:
            m = folder_by_key.get("znaydenov") or {
                "key": "znaydenov",
                "folder_id": "",
                "folder_name": "Знайденов",
                "display_name": "Знайденов",
            }
            folder_by_key["znaydenov"] = m
            file_jobs.append(
                (
                    m,
                    {
                        "id": ZNAYDENOV_SPREADSHEET_ID,
                        "name": "Отчет Знайденов Валентин",
                        "mimeType": "application/vnd.google-apps.spreadsheet",
                        "forced": True,
                    },
                )
            )

        # Сначала Sheets (стабильнее), потом xlsx — меньше обрывов на квоте.
        def _job_rank(item: tuple[dict[str, Any], dict[str, Any]]) -> tuple[int, str]:
            _m, f = item
            mime = (f.get("mimeType") or "").lower()
            name = (f.get("name") or "").lower()
            is_xlsx = "openxml" in mime or name.endswith(".xlsx")
            return (1 if is_xlsx else 0, name)

        file_jobs.sort(key=_job_rank)

        total = max(len(file_jobs), 1)
        await self.db.masters_kpi_set_sync_state(
            status="running",
            total=total,
            done=0,
            message=f"Файлов: {len(file_jobs)}",
        )

        all_rows: list[dict[str, Any]] = []
        master_stats: dict[str, dict[str, Any]] = {
            k: {
                "master_key": k,
                "display_name": v["display_name"],
                "folder_name": v["folder_name"],
                "folder_id": v["folder_id"],
                "color": MASTER_META.get(k, {}).get("color") or "#334155",
                "files": 0,
                "lines": 0,
                "tickets": 0,
                "work_sum": 0.0,
                "hours": 0.0,
                "hours_known": False,
                "crm_orders": 0,
            }
            for k, v in folder_by_key.items()
        }

        # CRM counts
        for eng in crm:
            key = master_key_from_name(eng)
            if key and key in master_stats:
                # recount properly below
                pass
        crm_counts: dict[str, int] = {}
        for r in await self.db.quality_list_orders():
            eng = (r.get("engineer") or "").strip()
            key = master_key_from_name(eng)
            if key:
                crm_counts[key] = crm_counts.get(key, 0) + 1
        for k, st in master_stats.items():
            st["crm_orders"] = crm_counts.get(k, 0)

        done = 0
        errors: list[str] = []
        failed_jobs: list[tuple[dict[str, Any], dict[str, Any]]] = []

        async def _ingest(m: dict[str, Any], f: dict[str, Any]) -> None:
            key = m["key"]
            name = f.get("name") or ""
            mime = f.get("mimeType") or ""
            # Важно: xlsx MIME содержит «spreadsheetml» — нельзя матчить просто «spreadsheet».
            if mime == MIME_SHEET or f.get("forced"):
                title, values = await client.read_sheet_values(f["id"])
                source_name = title or name
            else:
                values = await client.read_xlsx_values(f["id"])
                source_name = name
            fallback = date_from_report_name(source_name) or date_from_report_name(name)
            if fallback is None and f.get("modifiedTime"):
                try:
                    fallback = datetime.fromisoformat(
                        str(f["modifiedTime"]).replace("Z", "+00:00")
                    ).date()
                except ValueError:
                    fallback = None
            parsed = parse_report_rows(
                values, source_name=source_name, fallback_ready=None
            )
            parsed = apply_ready_fallback(parsed, fallback)
            for row in parsed:
                row["master_key"] = key
                row["source_file_id"] = f["id"]
                all_rows.append(row)
            st = master_stats[key]
            st["files"] += 1
            st["lines"] += len(parsed)

        for m, f in file_jobs:
            name = f.get("name") or ""
            try:
                await _ingest(m, f)
            except Exception as exc:  # noqa: BLE001
                failed_jobs.append((m, f))
                errors.append(f"{name}: {exc}")
            done += 1
            mime_l = (f.get("mimeType") or "").lower()
            is_xlsx = "openxml" in mime_l or name.lower().endswith(".xlsx")
            await asyncio.sleep(0.55 if is_xlsx else 0.1)
            if done % 5 == 0 or done == total:
                await self.db.masters_kpi_set_sync_state(
                    status="running",
                    total=total,
                    done=done,
                    message=f"{m['display_name']}: {name[:40]}",
                )

        if failed_jobs:
            await self.db.masters_kpi_set_sync_state(
                status="running",
                total=total,
                done=done,
                message=f"Повтор {len(failed_jobs)} файлов…",
            )
            await asyncio.sleep(2.0)
            still_err: list[str] = []
            for m, f in failed_jobs:
                name = f.get("name") or ""
                try:
                    await _ingest(m, f)
                    await asyncio.sleep(0.8)
                except Exception as exc:  # noqa: BLE001
                    still_err.append(f"{name}: {exc}")
            errors = still_err

        # Deduplicate by master+ticket+ready+work+hours (same line in overlapping reports)
        dedup: dict[tuple, dict[str, Any]] = {}
        for r in all_rows:
            k = (
                r.get("master_key"),
                r.get("ticket"),
                r.get("ready_day"),
                r.get("work_sum"),
                r.get("hours"),
                r.get("description"),
            )
            dedup[k] = r
        unique_rows = list(dedup.values())

        week_rows: list[dict[str, Any]] = []
        for key, st in master_stats.items():
            m_rows = [r for r in unique_rows if r.get("master_key") == key]
            # Итоги карточек = тот же период, что и графики (с 2025-W31)
            period_rows: list[dict[str, Any]] = []
            for r in m_rows:
                day_s = r.get("ready_day")
                if not day_s:
                    continue
                try:
                    d = date.fromisoformat(str(day_s)[:10])
                except ValueError:
                    continue
                if in_chart_window(d):
                    period_rows.append(r)
            use_rows = period_rows if period_rows else m_rows
            tickets = {str(r.get("ticket")) for r in use_rows}
            work = sum(float(r.get("work_sum") or 0) for r in use_rows)
            avg = round(work / len(tickets), 2) if tickets else None
            st["tickets"] = len(tickets)
            st["lines"] = len(use_rows)
            st["work_sum"] = round(work, 2)
            st["hours"] = None
            st["avg_ticket"] = avg
            st["efficiency"] = compute_kpi(work, len(tickets), avg)
            for w in aggregate_weeks(m_rows):
                week_rows.append({**w, "master_key": key})

        masters_out = sorted(
            [
                {
                    "master_key": st["master_key"],
                    "display_name": st["display_name"],
                    "folder_name": st["folder_name"],
                    "folder_id": st["folder_id"],
                    "color": st["color"],
                    "files": st["files"],
                    "lines": st["lines"],
                    "tickets": st["tickets"],
                    "work_sum": st["work_sum"],
                    "hours": None,
                    "avg_ticket": st["avg_ticket"],
                    "efficiency": st["efficiency"],
                    "crm_orders": st["crm_orders"],
                }
                for st in master_stats.values()
                if st["files"] > 0 or st["lines"] > 0
            ],
            key=lambda x: (-(x.get("efficiency") or 0), -(x.get("work_sum") or 0), x["display_name"]),
        )

        await self.db.masters_kpi_replace_all(masters_out, week_rows)
        msg = f"Готово: {len(masters_out)} мастеров, {len(unique_rows)} строк"
        if errors:
            msg += f" · ошибок файлов: {len(errors)}"
        await self.db.masters_kpi_set_sync_state(
            status="idle",
            total=total,
            done=done,
            message=msg[:500],
            finished_at=_utcnow(),
        )

    async def export_pages_snapshot(self) -> dict[str, Any]:
        from modules.masters_kpi.export import (
            build_masters_kpi_pages_payload,
            write_masters_kpi_pages_json,
        )

        stats = await self.get_stats()
        payload = build_masters_kpi_pages_payload(stats)
        path = write_masters_kpi_pages_json(payload)
        return {"ok": True, "path": str(path), "counts": payload.get("counts")}


def build_masters_kpi_charts(
    masters: list[dict[str, Any]], weeks: list[dict[str, Any]]
) -> dict[str, Any]:
    """Сводный график КПД + work_sum по неделям (с обрезкой пустого начала)."""
    labels_set: set[str] = set()
    by_master: dict[str, dict[str, dict[str, Any]]] = {}
    for w in weeks:
        lab = f"{int(w['iso_year'])}-W{int(w['iso_week']):02d}"
        labels_set.add(lab)
        mk = str(w["master_key"])
        by_master.setdefault(mk, {})[lab] = w
    labels = sorted(labels_set)

    # Убрать ведущие недели без данных.
    start = 0
    for i, lab in enumerate(labels):
        if any(lab in by_master.get(mk, {}) for mk in by_master):
            start = i
            break
    labels = labels[start:]

    meta = {m["master_key"]: m for m in masters}

    def _series_for(field: str) -> list[dict[str, Any]]:
        out = []
        for mk, m in sorted(meta.items(), key=lambda x: x[1].get("display_name") or ""):
            bucket = by_master.get(mk) or {}
            out.append(
                {
                    "key": mk,
                    "label": m.get("display_name") or mk,
                    "color": m.get("color") or "#334155",
                    "data": [
                        (bucket[lab].get(field) if lab in bucket else None)
                        for lab in labels
                    ],
                }
            )
        return out

    per_master: dict[str, Any] = {}
    for mk in meta:
        bucket = by_master.get(mk) or {}
        m_labels = sorted(bucket.keys())
        per_master[mk] = {
            "labels": m_labels,
            "efficiency": [bucket[l].get("efficiency") for l in m_labels],
            "work_sum": [bucket[l].get("work_sum") for l in m_labels],
            "tickets": [bucket[l].get("tickets") for l in m_labels],
            "avg_ticket": [bucket[l].get("avg_ticket") for l in m_labels],
            "weeks": [bucket[l] for l in m_labels],
        }

    return {
        "labels": labels,
        "efficiency": _series_for("efficiency"),
        "work_sum": _series_for("work_sum"),
        "tickets": _series_for("tickets"),
        "per_master": per_master,
    }
