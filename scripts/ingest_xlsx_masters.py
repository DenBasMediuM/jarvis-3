#!/usr/bin/env python3
"""Отдельный догруз Дубового/Вовчука (xlsx), без полного синка Sheets."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from core.config import settings
from core.db import Database
from modules.masters_kpi.config import (
    DUBOVOY_FOLDER_ID,
    MASTER_META,
    ZNAYDENOV_SPREADSHEET_ID,
)
from modules.masters_kpi.drive import MIME_SHEET, MastersDriveClient
from modules.masters_kpi.parse import (
    aggregate_weeks,
    apply_ready_fallback,
    compute_kpi,
    date_from_report_name,
    parse_report_rows,
)
from modules.masters_kpi.service import build_masters_kpi_charts

ROOT = Path(__file__).resolve().parents[1]
VOVCHUK_FOLDER = "1OGEhxNlgcvrfHqmpJpw52tztKrnyVsho"


def _sa_json() -> str:
    # Свежий ключ из файла проекта (как при пробах).
    path = ROOT / "gincore-394505-0b340cc2d2f4.json"
    return path.read_text(encoding="utf-8")


async def ingest_folder(
    client: MastersDriveClient,
    *,
    key: str,
    folder_id: str,
    display: str,
) -> tuple[dict, list[dict], list[str]]:
    files = await client.list_report_files(folder_id)
    rows: list[dict] = []
    errors: list[str] = []
    files_ok = 0
    for f in files:
        name = f.get("name") or ""
        if key == "dubovoy":
            mt = str(f.get("modifiedTime") or "")
            if not (
                "2025" in name
                or "2026" in name
                or mt.startswith("2025")
                or mt.startswith("2026")
            ):
                continue
        try:
            mime = f.get("mimeType") or ""
            if mime == MIME_SHEET:
                title, values = await client.read_sheet_values(f["id"])
                source = title or name
            else:
                values = await client.read_xlsx_values(f["id"])
                source = name
            fallback = date_from_report_name(source) or date_from_report_name(name)
            if fallback is None and f.get("modifiedTime"):
                fallback = datetime.fromisoformat(
                    str(f["modifiedTime"]).replace("Z", "+00:00")
                ).date()
            parsed = parse_report_rows(values, source_name=source, fallback_ready=None)
            parsed = apply_ready_fallback(parsed, fallback)
            for r in parsed:
                r["master_key"] = key
                r["source_file_id"] = f["id"]
            rows.extend(parsed)
            files_ok += 1
            print(f"  OK {name[:60]} → {len(parsed)}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            print(f"  ERR {name[:60]} → {exc}")
        await asyncio.sleep(0.9)

    tickets = {str(r.get("ticket")) for r in rows}
    work = sum(float(r.get("work_sum") or 0) for r in rows)
    avg = round(work / len(tickets), 2) if tickets else None
    master = {
        "master_key": key,
        "display_name": display,
        "folder_name": display,
        "folder_id": folder_id,
        "color": MASTER_META.get(key, {}).get("color") or "#334155",
        "files": files_ok,
        "lines": len(rows),
        "tickets": len(tickets),
        "work_sum": round(work, 2),
        "hours": None,
        "avg_ticket": avg,
        "efficiency": compute_kpi(work, len(tickets), avg),
        "crm_orders": 0,
    }
    weeks = [{**w, "master_key": key} for w in aggregate_weeks(rows)]
    return master, weeks, errors


async def main() -> None:
    db = Database(settings.resolved_db_path())
    await db.connect()
    client = MastersDriveClient(_sa_json())

    existing_masters = await db.masters_kpi_list_masters()
    existing_weeks = await db.masters_kpi_list_weeks()
    # CRM counts
    crm_counts: dict[str, int] = {}
    for r in await db.quality_list_orders():
        eng = (r.get("engineer") or "").strip()
        from modules.masters_kpi.parse import master_key_from_name

        k = master_key_from_name(eng)
        if k:
            crm_counts[k] = crm_counts.get(k, 0) + 1

    print("=== Вовчук")
    v_master, v_weeks, v_err = await ingest_folder(
        client, key="vovchuk", folder_id=VOVCHUK_FOLDER, display="Вовчук"
    )
    print("=== Дубовой")
    d_master, d_weeks, d_err = await ingest_folder(
        client, key="dubovoy", folder_id=DUBOVOY_FOLDER_ID, display="Дубовой"
    )

    print("=== Знайденов")
    z_rows: list[dict] = []
    z_err: list[str] = []
    z_files = 0
    try:
        title, values = await client.read_sheet_values(ZNAYDENOV_SPREADSHEET_ID)
        parsed = parse_report_rows(values, source_name=title, fallback_ready=None)
        for r in parsed:
            r["master_key"] = "znaydenov"
            r["source_file_id"] = ZNAYDENOV_SPREADSHEET_ID
        z_rows = parsed
        z_files = 1
        print(f"  OK {title} → {len(parsed)}")
    except Exception as exc:  # noqa: BLE001
        z_err.append(str(exc))
        print("  ERR", exc)
    z_tickets = {str(r.get("ticket")) for r in z_rows}
    z_work = sum(float(r.get("work_sum") or 0) for r in z_rows)
    z_avg = round(z_work / len(z_tickets), 2) if z_tickets else None
    z_master = {
        "master_key": "znaydenov",
        "display_name": "Знайденов",
        "folder_name": "Знайденов",
        "folder_id": "",
        "color": MASTER_META.get("znaydenov", {}).get("color") or "#334155",
        "files": z_files,
        "lines": len(z_rows),
        "tickets": len(z_tickets),
        "work_sum": round(z_work, 2),
        "hours": None,
        "avg_ticket": z_avg,
        "efficiency": compute_kpi(z_work, len(z_tickets), z_avg),
        "crm_orders": crm_counts.get("znaydenov", 0),
    }
    z_weeks = [{**w, "master_key": "znaydenov"} for w in aggregate_weeks(z_rows)]

    by_key = {m["master_key"]: m for m in existing_masters}
    for m in (v_master, d_master, z_master):
        if m["files"] > 0 or m["lines"] > 0:
            m["crm_orders"] = crm_counts.get(m["master_key"], 0)
            by_key[m["master_key"]] = m

    weeks = [
        w
        for w in existing_weeks
        if w.get("master_key") not in {"vovchuk", "dubovoy", "znaydenov"}
    ]
    weeks.extend(v_weeks)
    weeks.extend(d_weeks)
    weeks.extend(z_weeks)

    masters = sorted(
        by_key.values(),
        key=lambda x: (
            -(x.get("efficiency") or 0),
            -(x.get("work_sum") or 0),
            x.get("display_name") or "",
        ),
    )
    await db.masters_kpi_replace_all(masters, weeks)
    await db.masters_kpi_set_sync_state(
        status="idle",
        message=(
            f"Догруз: Вовчук {v_master['tickets']}кв, Дубовой {d_master['tickets']}кв, "
            f"Знайденов {z_master['tickets']}кв · ошибок {len(v_err)+len(d_err)+len(z_err)}"
        ),
        finished_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        done=v_master["files"] + d_master["files"] + z_files,
        total=v_master["files"] + d_master["files"] + z_files + len(v_err) + len(d_err) + len(z_err),
    )

    # экспорт
    from modules.masters_kpi.export import (
        build_masters_kpi_pages_payload,
        write_masters_kpi_pages_json,
    )

    stats = {
        "ok": True,
        "sync": await db.masters_kpi_get_sync_state(),
        "masters": masters,
        "weeks": weeks,
        "charts": build_masters_kpi_charts(masters, weeks),
    }
    path = write_masters_kpi_pages_json(build_masters_kpi_pages_payload(stats))
    print("saved masters", len(masters), "weeks", len(weeks), "→", path)
    print("vovchuk", v_master, "weeks", len(v_weeks))
    print("dubovoy", d_master, "weeks", len(d_weeks))
    print("znaydenov", z_master, "weeks", len(z_weeks))
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
