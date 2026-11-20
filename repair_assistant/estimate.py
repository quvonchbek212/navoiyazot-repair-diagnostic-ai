"""Ta'mir qachon tugashini taxminlash — sof funksiya, baza va LLM'siz.

ODDIY MEDIANADAN FARQI — naryadning hozirgi holati hisobga olinadi:

1. Naryad qaysi bosqichda: oxirgi yozilgan belgi (`ANCHORS`: ochildi, ARM
   qabul qildi, diagnostika qilindi). Har o'xshash ta'mirda SHU BELGIDAN
   chiqishgacha ketgan vaqt olinadi. O'xshash ta'mirda bu belgi yozilmagan
   bo'lsa — ochilishdan chiqishgacha, naryad ochilganidan beri o'tgan vaqt
   bilan solishtiriladi (`measured_from`).
2. Naryad allaqachon qancha turgan bo'lsa, undan TEZ tugagan ta'mirlar
   olinmaydi — ular endi hech narsa aytmaydi. Qolganlaridan: qolgan vaqt =
   ularning vaqti - o'tgan vaqt.
3. Natija — oraliq: eng qisqa, mediana, eng uzun, soni bilan. Kvartil EMAS:
   30.10.2026 da tugun bo'yicha yopilgan ta'mir 1-7 ta, kvartil ma'nosiz.

TARIX YO'Q yoki naryad hammasidan uzoq turgan bo'lsa — taxmin YO'Q
(`estimate: None`): tarixsiz muddatni faqat o'ylab topish mumkin.

VAQT TARTIBI: faqat `now` gacha chiqqan remontlar olinadi. `eval.py` dagi
orqaga qarab sinash shu funksiya bilan "o'sha paytda nima degan bo'lardik"ni
hisoblaydi.

Ehtiyot qism omborda bor-yo'qligi HISOBGA OLINMAYDI: 30.10.2026 da qism
so'rovi ombor bilan bog'lanmagan (`item_id` bo'yicha 0/11, `stock_id` 0/11).
Berilmagan qism va o'xshash ta'mirlardagi qism kutish — faqat LLM izohi
uchun fakt, oraliqqa qo'shilmaydi (o'xshash ta'mirlar muddatida u bor).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from breakdown_report import labels as br_labels
from breakdown_report.metrics import model_name
from repair_assistant import similar
from repair_assistant.common import PENDING_PART_STATUSES, exit_of, parts_wait_seconds
from repair_assistant.texts import t

#: (belgi ustuni, belgidan keyingi bosqich) — naryaddagi ketma-ketlik tartibida.
ANCHORS = (
    ("opened_at", "ARM_ACCEPTANCE"),
    ("received_by_arm_at", "DIAGNOSIS"),
    ("chief_mechanic_diagnosed_at", "REPAIR"),
)

_HOUR = 3600.0


def _hours(seconds: float) -> float:
    return round(seconds / _HOUR, 1)


def anchor(repair: dict[str, Any], now: datetime) -> tuple[str, datetime]:
    """Oxirgi yozilgan belgi: (ustun, vaqt). Tartibi buzilgan yoki kelajakdagi belgi olinmaydi."""
    column, at = ANCHORS[0][0], repair["opened_at"]
    for name, _stage in ANCHORS[1:]:
        value = repair.get(name)
        if value is not None and at <= value <= now:
            column, at = name, value
    return column, at


def _measure(candidate: dict[str, Any], column: str, since: datetime, opened: datetime,
             now: datetime) -> dict[str, Any]:
    """O'xshash ta'mir: belgidan chiqishgacha va naryadda shu belgidan beri o'tgan vaqt."""
    exited, _source = exit_of(candidate)
    mark = candidate.get(column)
    if column != ANCHORS[0][0] and mark is not None and candidate["opened_at"] <= mark <= exited:
        to_exit, elapsed, measured_from = exited - mark, now - since, "stage"
    else:
        to_exit, elapsed, measured_from = exited - candidate["opened_at"], now - opened, "opened"
    to_exit_s, elapsed_s = to_exit.total_seconds(), elapsed.total_seconds()
    return {
        "measured_from": measured_from,
        "duration_seconds": (exited - candidate["opened_at"]).total_seconds(),
        "to_exit_seconds": to_exit_s,
        "used": to_exit_s > elapsed_s,
        "remaining_seconds": to_exit_s - elapsed_s if to_exit_s > elapsed_s else None,
    }


def _plan(target: dict[str, Any], estimate: dict[str, Any] | None, now: datetime) -> dict[str, Any] | None:
    """Naryad rejasi: oraliqqa nisbatan qayerda — buni ham kod aytadi, model emas."""
    planned = target.get("estimated_completion_time")
    if not planned or planned < target["opened_at"]:
        return None
    if planned <= now:
        position = "PASSED"
    elif estimate is None:
        position = None
    elif planned < estimate["ready_from"]:
        position = "BEFORE"
    elif planned > estimate["ready_to"]:
        position = "AFTER"
    else:
        position = "INSIDE"
    return {"planned_exit_at": planned, "passed": planned <= now, "position": position}


def build(
    target: dict[str, Any],
    repairs: list[dict[str, Any]],
    parts: list[dict[str, Any]],
    *,
    now: datetime,
    top: int,
    lang: str,
) -> dict[str, Any]:
    """Ochiq naryad uchun taxmin. `target` — `repairs` dagi qator (ochiq ekanini chaqiruvchi tekshiradi)."""
    parts_by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for part in parts:
        parts_by[part["repair_id"]].append(part)

    column, since = anchor(target, now)
    history = similar.closed_before(repairs, now=now, exclude_id=target["id"])
    ranked = similar.rank(target, history, top=top)

    rows = []
    for match in ranked:
        candidate = match["repair"]
        exited, _source = exit_of(candidate)
        own_parts = parts_by.get(candidate["id"]) or []
        rows.append({
            "repair_id": candidate["id"],
            "repair_number": candidate.get("repair_number"),
            "plate_number": candidate.get("plate_number"),
            "model_name": model_name(candidate) or None,
            "match": match["match"],
            "parts_wait_seconds": (parts_wait_seconds(own_parts, candidate["opened_at"], exited)
                                   if own_parts else None),
            **_measure(candidate, column, since, target["opened_at"], now),
        })

    remaining = sorted(r["remaining_seconds"] for r in rows if r["used"])
    if not rows:
        outcome, estimate = "NO_HISTORY", None
    elif not remaining:
        outcome, estimate = "LONGER_THAN_HISTORY", None
    else:
        middle = median(remaining)
        outcome = "ESTIMATED"
        # Naryad vaqtlari zonasida: javobda `opened_at` bilan bir xil ofset.
        zone = target["opened_at"].tzinfo
        estimate = {
            "ready_from": (now + timedelta(seconds=remaining[0])).astimezone(zone),
            "ready_median": (now + timedelta(seconds=middle)).astimezone(zone),
            "ready_to": (now + timedelta(seconds=remaining[-1])).astimezone(zone),
            "remaining_hours": {"min": _hours(remaining[0]), "median": _hours(middle),
                                "max": _hours(remaining[-1])},
        }

    stage = dict(ANCHORS)[column]
    pending = [p for p in parts_by.get(target["id"]) or []
               if p.get("status") in PENDING_PART_STATUSES and not p.get("issued_at")
               and p.get("requested_at")]
    return {
        "repair_id": target["id"],
        "repair_number": target.get("repair_number"),
        "vehicle_id": target.get("vehicle_id"),
        "plate_number": target.get("plate_number"),
        "model_name": model_name(target) or None,
        "component_name": br_labels.label("component", target.get("component_category"), lang),
        "opened_at": target["opened_at"],
        "now": now,
        "current_stage": {"code": stage, "name": t(lang, f"stage.{stage}"), "since": since},
        "outcome": outcome,
        "estimate": estimate,
        "basis": {"similar_repairs": len(rows), "used": len(remaining),
                  "excluded_shorter": len(rows) - len(remaining)},
        "similar": rows,
        "pending_parts": [{"item_name": p.get("item_name"), "requested_at": p["requested_at"]}
                          for p in pending],
        "plan": _plan(target, estimate, now),
    }
