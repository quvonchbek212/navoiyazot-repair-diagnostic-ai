"""Bazadan o'qish va hisobni bir joyga yig'ish — LLM'siz qism.

Router uni fon oqimida chaqiradi, so'ng natijaga `explain` izoh qo'shadi.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from breakdown_report.metrics import CLOSED_REPAIR_STATUSES
from repair_assistant import config, diagnosis, estimate, queries, recurrence
from repair_assistant.common import exit_of


class RepairNotFound(LookupError):
    """Bunday naryad yo'q — 404."""


class RepairClosed(RuntimeError):
    """Naryad yopilgan — taxmin faqat ochiq naryadga (409)."""

    def __init__(self, exited_at: datetime | None) -> None:
        super().__init__(str(exited_at))
        self.exited_at = exited_at


def _open_repair(repair_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(naryad, butun tarix). Naryad yo'q — 404, yopilgan — 409."""
    repairs = queries.fetch_repairs(limit=config.MAX_ROWS)
    target = next((r for r in repairs if r["id"] == repair_id), None)
    if target is None:
        raise RepairNotFound(repair_id)
    exited_at, _source = exit_of(target)
    if exited_at is not None or target.get("status") in CLOSED_REPAIR_STATUSES:
        raise RepairClosed(exited_at)
    return target, repairs


def _finish(result: dict[str, Any], started: float) -> dict[str, Any]:
    result["generated_at"] = datetime.now()
    result["timings"] = {"db": round(time.perf_counter() - started, 2)}
    return result


def eta(*, repair_id: str, lang: str, now: datetime | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    # Naryad vaqtlari `timestamptz` — "hozir" ham zonali bo'lishi shart.
    now = now or datetime.now(timezone.utc)
    target, repairs = _open_repair(repair_id)
    parts = queries.fetch_parts([r["id"] for r in repairs])
    return _finish(estimate.build(target, repairs, parts, now=now, top=config.SIMILAR_TOP,
                                  lang=lang), started)


class VehicleNotFound(LookupError):
    """Bunday mashina yo'q — 404."""


def recurrence_facts(*, vehicle_id: str, lang: str, component: str | None = None,
                     now: datetime | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    now = now or datetime.now(timezone.utc)
    vehicle = queries.fetch_vehicle(vehicle_id)
    if vehicle is None:
        raise VehicleNotFound(vehicle_id)
    repairs = queries.fetch_repairs(limit=config.MAX_ROWS)
    ids = [r["id"] for r in repairs]
    mine = [r["opened_at"] for r in repairs if r.get("vehicle_id") == vehicle_id]
    # Reys va ko'rik faqat birinchi ta'mirdan keyin kerak (oraliqlar shundan).
    history = (queries.fetch_vehicle_history(vehicle_id, since=min(mine)) if mine
               else {"waybills": [], "inspections": [], "vehicle_parts": []})
    return _finish(recurrence.build(vehicle, repairs, queries.fetch_parts(ids),
                                    queries.fetch_work_items(ids), history, now=now, lang=lang,
                                    component=component), started)


def diagnosis_facts(*, repair_id: str, lang: str, now: datetime | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    now = now or datetime.now(timezone.utc)
    target, repairs = _open_repair(repair_id)
    ids = [r["id"] for r in repairs]
    return _finish(diagnosis.build(target, repairs, queries.fetch_parts(ids),
                                   queries.fetch_work_items(ids), now=now,
                                   top=config.SIMILAR_TOP, lang=lang), started)
