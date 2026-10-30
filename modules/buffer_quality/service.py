"""Сервис «Качество обработки буфера»: снимки из кэша Quality."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from modules.buffer_quality.compute import build_day_payload
from modules.gincore.quality import compute_quality_metrics

def merge_snapshot_assignments(
    live_masters: list[dict[str, Any]],
    snapshot_masters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    snap = {str(m.get("master_key")): m for m in snapshot_masters or []}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in live_masters:
        row = dict(m)
        key = str(row.get("master_key"))
        seen.add(key)
        s = snap.get(key)
        if s:
            row["assigned_from_buffer"] = int(s.get("assigned_from_buffer") or 0)
            row["assign_quality"] = s.get("assign_quality")
        out.append(row)
    # мастер получил из буфера, но сейчас не в живом списке — не теряем раздачу
    for key, s in snap.items():
        if key not in seen and int(s.get("assigned_from_buffer") or 0) > 0:
            out.append(dict(s))
    return out


# Максимальный разрыв между снимками, при котором ещё считаем раздачу.
MAX_GAP_DAYS = 7


class BufferQualityService:
    def __init__(self, db: Any, quality_service: Any | None = None) -> None:
        self.db = db
        self.quality_service = quality_service

    async def get_sync_state(self) -> dict[str, Any]:
        return await self.db.buffer_quality_get_sync_state()

    async def _load_orders(self) -> list[dict[str, Any]]:
        rows = await self.db.quality_list_orders()
        out: list[dict[str, Any]] = []
        for r in rows:
            feed: list[dict[str, Any]] = []
            if r.get("feed_json"):
                try:
                    feed = json.loads(r["feed_json"])
                except json.JSONDecodeError:
                    feed = []
            if feed or r.get("accepted_at"):
                metrics = compute_quality_metrics(
                    accepted_at=r.get("accepted_at"),
                    repair_cost=r.get("repair_cost"),
                    feed=feed,
                    engineer=r.get("engineer"),
                    status=r.get("status"),
                )
            else:
                try:
                    metrics = json.loads(r.get("metrics_json") or "{}")
                except json.JSONDecodeError:
                    metrics = {}
            out.append(
                {
                    "order_id": r["order_id"],
                    "status": r.get("status"),
                    "engineer": r.get("engineer") or metrics.get("master_name"),
                    "accepted_at": r.get("accepted_at"),
                    **metrics,
                }
            )
        return out

    async def sync(self, *, day: date | None = None) -> dict[str, Any]:
        day = day or date.today()
        day_s = day.isoformat()
        now = datetime.now(timezone.utc).isoformat()

        await self.db.buffer_quality_set_sync_state(
            status="running",
            message="Обновление мастеров из CRM-списка…",
            started_at=now,
            finished_at=None,
            total=1,
            done=0,
        )
        try:
            list_refresh: dict[str, Any] | None = None
            if self.quality_service is not None:
                try:
                    list_refresh = await self.quality_service.refresh_list_fields()
                    await self.db.buffer_quality_set_sync_state(
                        message=(
                            f"Список CRM: {list_refresh.get('listed', 0)} зак. · "
                            "пересчёт загрузки…"
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    list_refresh = {"ok": False, "error": str(exc)}
                    await self.db.buffer_quality_set_sync_state(
                        message=f"Список CRM не обновлён ({exc}); считаем по кэшу…",
                    )

            orders = await self._load_orders()
            if not orders:
                await self.db.buffer_quality_set_sync_state(
                    status="idle",
                    message="Нет заказов в кэше Quality — сначала обновите Качество",
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    done=1,
                    total=1,
                )
                return {
                    "ok": True,
                    "needs_quality_sync": True,
                    "day": day_s,
                    "list_refresh": list_refresh,
                    "sync": await self.get_sync_state(),
                }

            # Сравниваем с последним доступным снимком, а не строго со вчера:
            # пропущенные дни (выходные, не запускали) не обнуляют раздачу.
            prev_day_s = await self.db.buffer_quality_find_prev_day(day_s)
            if prev_day_s and (day - date.fromisoformat(prev_day_s)).days > MAX_GAP_DAYS:
                prev_day_s = None
            prev_ids = (
                await self.db.buffer_quality_list_buffer_ids(prev_day_s) if prev_day_s else []
            )
            prev_masters = (
                await self.db.buffer_quality_list_masters_daily(prev_day_s)
                if prev_day_s
                else []
            )
            prev_daily = (
                await self.db.buffer_quality_get_daily(prev_day_s) if prev_day_s else None
            )
            has_prev = bool(prev_ids) or bool(prev_daily)

            payload = build_day_payload(
                orders,
                day=day,
                prev_buffer_ids=prev_ids if has_prev else None,
                prev_masters=prev_masters if has_prev else None,
                prev_buffer_over_3d=(
                    int(prev_daily["buffer_over_3d"])
                    if prev_daily and prev_daily.get("buffer_over_3d") is not None
                    else None
                ),
                prev_day=prev_day_s if has_prev else None,
            )

            await self.db.buffer_quality_upsert_daily(payload["daily"])
            await self.db.buffer_quality_replace_buffer_ids(
                day_s, payload["buffer_ids"]
            )
            await self.db.buffer_quality_replace_masters_daily(
                day_s, payload["masters"]
            )

            msg = (
                f"Снимок {day_s}: буфер {payload['daily']['buffer_count']}, "
                f"мастеров {len(payload['masters'])}"
            )
            assigned = payload["daily"].get("assigned_from_buffer")
            if assigned is not None:
                msg += f", из буфера → мастерам {assigned}"
                gap = payload["daily"].get("gap_days")
                if gap and gap > 1:
                    msg += f" (за {gap} дн. с {payload['daily'].get('prev_day')})"
                score = payload["daily"].get("dispatch_score")
                if score is not None:
                    msg += f", оценка {score}"

            try:
                exp = await self.export_pages_snapshot()
                msg += f", pages {exp.get('masters', 0)} маст."
            except Exception:  # noqa: BLE001
                pass

            await self.db.buffer_quality_set_sync_state(
                status="idle",
                message=msg,
                finished_at=datetime.now(timezone.utc).isoformat(),
                done=1,
                total=1,
            )
            return {
                "ok": True,
                "needs_quality_sync": False,
                "day": day_s,
                "daily": payload["daily"],
                "masters_count": len(payload["masters"]),
                "list_refresh": list_refresh,
                "sync": await self.get_sync_state(),
            }
        except Exception as exc:  # noqa: BLE001
            await self.db.buffer_quality_set_sync_state(
                status="error",
                message=str(exc),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            raise

    async def get_stats(self, *, limit: int = 365) -> dict[str, Any]:
        orders = await self._load_orders()
        daily = await self.db.buffer_quality_list_daily(limit=limit)
        sync = await self.get_sync_state()
        today_s = date.today().isoformat()
        masters = await self.db.buffer_quality_list_masters_daily(today_s)
        if not masters and daily:
            masters = await self.db.buffer_quality_list_masters_daily(daily[-1]["day"])

        # живой пересчёт фона загрузки (без записи), если есть кэш Quality
        live_masters = None
        live_buffer = None
        if orders:
            live = build_day_payload(orders, day=date.today(), prev_buffer_ids=None)
            live_masters = live["masters"]
            # Живой пересчёт не знает про раздачу (нет prev-снимка) — берём её
            # из последнего сохранённого снимка, иначе «Из буфера/Раздача» = 0.
            live_masters = merge_snapshot_assignments(live_masters, masters)
            live_buffer = {
                "buffer_count": live["daily"]["buffer_count"],
                "buffer_over_3d": live["daily"]["buffer_over_3d"],
                "avg_load_index": live["daily"]["avg_load_index"],
                "masters_high": live["daily"]["masters_high"],
                "masters_ok": live["daily"]["masters_ok"],
                "masters_low": live["daily"]["masters_low"],
            }

        latest = daily[-1] if daily else None
        return {
            "ok": True,
            "title": "Качество обработки буфера",
            "needs_quality_sync": not bool(orders),
            "sync": sync,
            "latest": latest,
            "live": live_buffer,
            "masters": live_masters if live_masters is not None else masters,
            "masters_snapshot": masters,
            "daily": daily,
            "series": {
                "days": [d["day"] for d in daily],
                "buffer_count": [d.get("buffer_count") for d in daily],
                "buffer_over_3d": [d.get("buffer_over_3d") for d in daily],
                "assigned_from_buffer": [d.get("assigned_from_buffer") for d in daily],
                "assign_to_high": [d.get("assign_to_high") for d in daily],
                "assign_to_ok": [d.get("assign_to_ok") for d in daily],
                "assign_to_low": [d.get("assign_to_low") for d in daily],
                "dispatch_score": [d.get("dispatch_score") for d in daily],
                "avg_load_index": [d.get("avg_load_index") for d in daily],
            },
        }

    async def export_pages_snapshot(self, *, path: Any = None) -> dict[str, Any]:
        from pathlib import Path

        from modules.buffer_quality.export import (
            build_buffer_quality_pages_payload,
            write_buffer_quality_pages_json,
        )

        stats = await self.get_stats()
        payload = build_buffer_quality_pages_payload(stats)
        out = write_buffer_quality_pages_json(
            payload, Path(path) if path else None
        )
        return {
            "ok": True,
            "path": str(out),
            "masters": len(payload.get("masters") or []),
            "days": len(payload.get("daily") or []),
            "exported_at": payload.get("exported_at"),
        }
