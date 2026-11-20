"""Takroriy nosozlik — faktlar, sof funksiya, baza va LLM'siz.

TAKROR = bitta mashinada bir xil tugun (`component_category`) bo'yicha 2 va
undan ko'p remont. Vaqt chegarasi YO'Q: "30 kun ichida qaytsa takror" degan
raqam bazadan chiqmaydi — oraliq kunlarda ko'rsatiladi, xulosani o'qigan odam
qiladi. `OTHER` ("boshqa") tugun hech narsa aytmaydi: u yerda alomat matnida
umumiy so'z ham shart (`similar.py` dagi qoida).

Har takror uchun:
  * har remont: alomat, nima qilingani (shablonsiz — `diagnosis.work_done`),
    so'ralgan qism, muddat;
  * ikki remont ORASI: necha kun, nechta reys (`waybill`) va nechta texnik
    ko'rikdan "soz" (FIT) deb o'tgan. 31.10.2026: 85312EBA tormoz ta'miridan
    keyin 2 reys va 4 ko'rikdan o'tib, 3.6 kunda yana tormoz bilan qaytgan;
  * shina yoki akkumulyator tuguni bo'lsa — o'rnatilgan qismlarning eskirishi
    (`vehicle_part`): shina — probeg bo'yicha, akkumulyator — oy bo'yicha;
  * shu modeldagi BOSHQA mashinalarda shu tugun takrorlanganmi.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from breakdown_report import labels as br_labels
from breakdown_report.metrics import model_name
from repair_assistant import diagnosis, similar
from repair_assistant.common import EXCLUDED_PART_STATUSES, EXCLUDED_REPAIR_STATUSES, exit_of

_DAY = 86400.0

#: Tugun -> `vehicle_part.category`. Faqat kodlar mos kelganlari: "elektr"
#: tugunini akkumulyatorga bog'lash — taxmin, kod uni qilmaydi.
PART_CATEGORIES = {"TIRES": "TIRE", "BATTERY": "BATTERY"}


def _counted(repairs: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    return sorted((r for r in repairs if r.get("status") not in EXCLUDED_REPAIR_STATUSES
                   and r["opened_at"] <= now), key=lambda r: r["opened_at"])


def groups(repairs: list[dict[str, Any]], vehicle_id: str, *, now: datetime,
           component: str | None = None) -> dict[str | None, list[dict[str, Any]]]:
    """Mashinaning takrorlangan tugunlari: `{tugun: [remontlar, eski -> yangi]}`."""
    by_component: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for repair in _counted(repairs, now):
        if repair.get("vehicle_id") == vehicle_id and (
                component is None or repair.get("component_category") == component):
            by_component[repair.get("component_category")].append(repair)
    out = {}
    for code, items in by_component.items():
        if code in similar.VAGUE_COMPONENTS:
            bags = [similar.words(similar.symptom(r)) for r in items]
            items = [r for i, r in enumerate(items)
                     if any(bags[i] & bags[j] for j in range(len(items)) if j != i)]
        if len(items) > 1:
            out[code] = items
    return out


def _between(times: list[datetime], start: datetime | None, end: datetime) -> int | None:
    if start is None or end < start:
        return None
    return sum(1 for t in times if start < t < end)


def part_wear(parts: list[dict[str, Any]], category: str, *, now: datetime) -> list[dict[str, Any]]:
    """O'rnatilgan qismlarning ishlatilgan ulushi (%). Kelajakdagi o'rnatish sanasi —
    yozuv xatosi (31.10.2026: shinalarda 1 ta, 2027-04-02) — hisoblanmaydi."""
    out = []
    today = now.date()
    for part in parts:
        if part.get("category") != category:
            continue
        installed = part.get("installed_at")
        if isinstance(installed, datetime):
            installed = installed.date()
        if isinstance(installed, date) and installed > today:
            continue
        km_life, km_now, km_at = (part.get("expected_life_km"), part.get("current_odometer_km"),
                                  part.get("installed_at_km"))
        if km_life and km_now is not None and km_at is not None and km_now >= km_at:
            used, measured_by = float(km_now - km_at) / float(km_life), "km"
        elif part.get("expected_life_months") and isinstance(installed, date):
            used = (today - installed).days / 30.44 / part["expected_life_months"]
            measured_by = "months"
        else:
            continue
        out.append({"name": part.get("name"), "category": category,
                    "used_pct": round(100 * used), "measured_by": measured_by})
    return out


def _park(repairs: list[dict[str, Any]], vehicle: dict[str, Any], component: str | None,
          now: datetime) -> dict[str, int]:
    """Shu modeldagi boshqa mashinalar: shu tugunda ta'mirlangani va takrorlangani."""
    model = " ".join(model_name(vehicle).casefold().split())
    per_vehicle: dict[str, int] = defaultdict(int)
    for repair in _counted(repairs, now):
        if (repair.get("vehicle_id") != vehicle["id"] and model
                and repair.get("component_category") == component
                and " ".join(model_name(repair).casefold().split()) == model):
            per_vehicle[repair["vehicle_id"]] += 1
    return {"vehicles_with_component": len(per_vehicle),
            "vehicles_with_repeat": sum(1 for n in per_vehicle.values() if n > 1)}


def build(
    vehicle: dict[str, Any],
    repairs: list[dict[str, Any]],
    parts: list[dict[str, Any]],
    work_items: list[dict[str, Any]],
    history: dict[str, list[dict[str, Any]]],
    *,
    now: datetime,
    lang: str,
    component: str | None = None,
) -> dict[str, Any]:
    """`history` — `queries.fetch_vehicle_history`: reyslar, ko'riklar, o'rnatilgan qismlar."""
    items_by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in work_items:
        items_by[item["repair_id"]].append(item)
    parts_by: dict[str, list[str]] = defaultdict(list)
    for part in parts:
        if part.get("status") not in EXCLUDED_PART_STATUSES and part.get("item_name") \
                and part["item_name"] not in parts_by[part["repair_id"]]:
            parts_by[part["repair_id"]].append(part["item_name"])
    skip = diagnosis.templates(similar.closed_before(repairs, now=now, exclude_id=""), items_by)
    trips = [w["actual_departure_at"] for w in history.get("waybills") or []
             if w.get("actual_departure_at") and w["actual_departure_at"] <= now]
    passed = [i["inspected_at"] for i in history.get("inspections") or []
              if i.get("status") == "FIT" and i.get("inspected_at") and i["inspected_at"] <= now]

    found = groups(repairs, vehicle["id"], now=now, component=component)
    codes = iter(f"R{n}" for n in range(1, 1 + sum(len(g) for g in found.values())))
    out_groups = []
    for code, items in sorted(found.items(), key=lambda kv: kv[1][0]["opened_at"]):
        episodes = []
        for repair in items:
            exited, _source = exit_of(repair)
            is_open = exited is None or exited > now
            episodes.append({
                "code": next(codes),
                "repair_id": repair["id"],
                "repair_number": repair.get("repair_number"),
                "opened_at": repair["opened_at"],
                "exited_at": None if is_open else exited,
                "is_open": is_open,
                "duration_seconds": ((now if is_open else exited) - repair["opened_at"]).total_seconds(),
                "symptom": (repair.get("initial_diagnosis") or "").strip() or None,
                "area": (repair.get("defect_area") or "").strip() or None,
                "work": [] if is_open else diagnosis.work_done(repair, items_by.get(repair["id"]) or [], skip),
                "parts": parts_by.get(repair["id"]) or [],
            })
        intervals = []
        for previous, current in zip(episodes, episodes[1:]):
            start = previous["exited_at"]
            overlap = start is not None and current["opened_at"] < start
            intervals.append({
                "from_code": previous["code"], "to_code": current["code"],
                "from_repair_id": previous["repair_id"], "to_repair_id": current["repair_id"],
                "days": (round((current["opened_at"] - start).total_seconds() / _DAY, 1)
                         if start is not None and not overlap else None),
                "overlap": overlap,
                "trips": _between(trips, start, current["opened_at"]),
                "inspections_passed": _between(passed, start, current["opened_at"]),
            })
        category = PART_CATEGORIES.get(code)
        out_groups.append({
            "component": code,
            "component_name": br_labels.label("component", code, lang),
            "episodes": episodes,
            "intervals": intervals,
            "parts": (part_wear(history.get("vehicle_parts") or [], category, now=now)
                      if category else []),
            "park": _park(repairs, vehicle, code, now),
        })

    vehicle_repairs = [r for r in _counted(repairs, now) if r.get("vehicle_id") == vehicle["id"]]
    return {
        "vehicle_id": vehicle["id"],
        "repair_id": None,
        "plate_number": vehicle.get("plate_number"),
        "model_name": model_name(vehicle) or None,
        "now": now,
        "outcome": "REPEATS" if out_groups else "NO_REPEATS",
        "repairs_total": len(vehicle_repairs),
        # Filtr bilan "takror yo'q" — faqat shu tugun haqida, butun mashina emas.
        "component_name": (br_labels.label("component", component, lang)
                           if component else None),
        "groups": out_groups,
        "basis": {"groups": len(out_groups),
                  "repairs": sum(len(g["episodes"]) for g in out_groups)},
    }
