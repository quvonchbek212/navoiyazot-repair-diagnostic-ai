"""Buzilish hisobotining hisob qismi — sof funksiyalar, baza va LLM'siz.

MODULNING BUTUN MANTIG'I BESH QOIDADA:

1. BUZILISH = `vehicle_repair` yozuvi. Rad etilgan yoki bekor qilingan
   so'rov (`REJECTED`, `CANCELLED`) buzilish sifatida SANALMAYDI — u
   ro'yxatda `counted: false` bo'lib ko'rinadi va soni izohda yoziladi.

2. CHEGARA YO'Q, SOLISHTIRISH BOR. "Ko'p" — ro'yxatda yuqorida turish;
   "erta" — buzilmagan guruhdoshlaridan YANGI bo'lsa ham buzilish; "tez
   qayta buzildi" — oldingi ta'mirdan keyin necha reysda. Hech bir o'ylab
   topilgan son (masalan "oyiga 3 marta") yo'q.

   "Davr boshidan buzilishgacha necha reys" ERTALIK O'LCHOVI EMAS: reys
   yozuvlari 19.08.2026 dan boshlangan va o'sha kuni buzilgan mashina
   "0 reysda buzildi" bo'lib chiqardi (14.09.2026: 9 tadan 6 tasi). Bu
   kuzatuv oynasining boshlanishi, mashinaning tezligi emas. Shuning uchun
   `trips_before` faqat ko'rsatiladi, undan hukm chiqarilmaydi.

3. NOMA'LUM — NOL EMAS. `trip` jadvali bo'sh bo'lsa reys soni `None`
   bo'ladi, 0 emas: aks holda hamma mashina "ishlamagan" deb chiqardi.
   `trip` da yozuv bor-u, shu mashinada yo'q bo'lsa — bu O'LCHANGAN nol.
   Sabab jadvali (`speed_violation`, ...) bo'sh bo'lsa omil "tekshirilmadi"
   bo'ladi, "sabab yo'q" emas.

4. SOLISHTIRISH GURUHI. Avval bir xil model (marka + model): "15 ta
   Damas'dan nega aynan shu buzildi". Modelda buzilmagan faol mashina
   bo'lmasa — bir xil transport turi. U ham bo'lmasa solishtirilmaydi.
   "Buzilmagan faol" = davrda reys qilgan va buzilmagan.

5. KM UMUMAN CHIQARILMAYDI. Bazada reys masofasi kiritish xatolariga to'la
   (14.09.2026: bitta reysda 574 596 km, yo'l varaqasida 2 499 956 km).
   Ish hajmi o'lchovi — yakunlangan reys soni. Ilgari km "faqat ma'lumot
   uchun" ko'rsatilardi; 15.09.2026 tekshiruvida 162 ta so'rovning 72
   holatida reysiga 5000 km dan oshdi va foydalanuvchini chalg'itdi —
   olib tashlandi.

6. MOTOSOAT FAQAT MOTOSOAT BILAN ISHLAYDIGAN MASHINADA
   (`MOTOHOUR_MODES`). Km bilan ishlaydigan avtobuslarning yo'l varaqasida
   test qiymati turibdi (1000 -> 1005, ya'ni "5"); ish rejimi bazaning
   o'zidan (`transport_vehicle.usage_mode`) olinadi.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from breakdown_report import labels
from breakdown_report.texts import t

#: Sabab omillari olinadigan jadvallar. Bo'sh bo'lsa omil tekshirilmaydi
#: va bu `data_quality` da ochiq yoziladi.
FACTOR_TABLES = (
    "speed_violation",
    "incident",
    "vehicle_accident",
    "maintenance_plan",
    "vehicle_part",
)

#: Buzilish sifatida SANALMAYDIGAN ta'mir holatlari: so'rov rad etilgan
#: (mexanik nosozlikni tasdiqlamagan) yoki bekor qilingan.
EXCLUDED_REPAIR_STATUSES = ("REJECTED", "CANCELLED")

#: Yopiq ta'mir holatlari — qolganlari ochiq. `vehicle_selection/queries.py`
#: dagi ro'yxat bilan bir xil bo'lishi shart (test tekshiradi).
CLOSED_REPAIR_STATUSES = (
    "CLOSED", "COMPLETED", "CANCELLED", "ARM_CLOSED", "REJECTED", "REPAIRED",
)

#: `incident.incident_type` dagi haydash uslubiga oid hodisalar.
HARSH_INCIDENT_TYPES = ("HARD_BRAKING", "RAPID_ACCELERATION")

#: Motosoat hisoblanadigan ish rejimlari (`transport_vehicle.usage_mode`).
MOTOHOUR_MODES = ("MOTOSOAT", "KM_AND_MOTOSOAT")


# ------------------------------------------------------------------ Yordamchi


def _float(value: Any) -> float | None:
    """`numeric` ustunlar psycopg2 dan `Decimal` bo'lib keladi."""
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _num(value: Any) -> int | float | None:
    """Javob va matn uchun: butun bo'lsa int, aks holda bir xona aniqlik."""
    number = _float(value)
    if number is None:
        return None
    return int(number) if number.is_integer() else round(number, 1)


def _median(values: list[Any]) -> float | None:
    known = [float(v) for v in values if v is not None]
    return median(known) if known else None


def _ratio(trips: int | None, breakdowns: int) -> int | float | None:
    """Necha reysga bitta buzilish. Reys noma'lum yoki nol bo'lsa — hisoblanmaydi."""
    if trips is None or trips == 0 or breakdowns == 0:
        return None
    return _num(trips / breakdowns)


def _occurred(repair: dict[str, Any]) -> datetime | None:
    return repair.get("occurred_at") or repair.get("detected_at") or repair.get("opened_at")


def _occurred_key(repair: dict[str, Any]) -> tuple[bool, float, str]:
    moment = _occurred(repair)
    return (moment is None, moment.timestamp() if moment else 0.0,
            repair.get("repair_number") or "")


def _counted(repair: dict[str, Any]) -> bool:
    return (repair.get("status") or "") not in EXCLUDED_REPAIR_STATUSES


def _model_key(vehicle: dict[str, Any]) -> tuple[str, str] | None:
    """(solishtirish kaliti, ko'rinadigan nom).

    Bazada model nomi ko'pincha markani o'z ichiga oladi ("Isuzu FVR34Q"),
    ba'zan esa yo'q ("Damas") — ikkala holatda ham nom takrorlanmasin.
    """
    brand = (vehicle.get("brand") or "").strip()
    model = (vehicle.get("model") or "").strip()
    if not brand and not model:
        return None
    if not model or model.casefold().startswith(brand.casefold()):
        name = model or brand
    else:
        name = f"{brand} {model}".strip()
    return " ".join(name.casefold().split()), name


def model_name(vehicle: dict[str, Any]) -> str:
    """Ko'rinadigan model nomi ("Chevrolet Damas", lekin "Isuzu Isuzu FVR34Q" emas)."""
    key = _model_key(vehicle)
    return key[1] if key else ""


def downtime_hours(repair: dict[str, Any]) -> float | None:
    """Mashina qancha soat ta'mirda turgani.

    Avval bazadagi qo'lda yozilgan qiymat (`actual_downtime_hours`, keyin
    `downtime_hours`). Ular bo'sh bo'lsa (14.09.2026: 11 tadan 0 tasida
    yozilgan) aniqlangan va ta'mirlangan vaqt farqi olinadi. `completed_at`
    EMAS: u hujjat yopilgan payt, 6 kungacha keyin bo'lishi kuzatilgan.
    """
    for key in ("actual_downtime_hours", "downtime_hours"):
        value = _float(repair.get(key))
        if value is not None:
            return round(value, 1)
    start, end = _occurred(repair), repair.get("repaired_at")
    if isinstance(start, datetime) and isinstance(end, datetime) and end >= start:
        return round((end - start).total_seconds() / 3600, 1)
    return None


def _vehicle_ref(vehicle: dict[str, Any], ref_date: date, lang: str) -> dict[str, Any]:
    release = _date(vehicle.get("release_date"))
    transport_type = vehicle.get("transport_type")
    return {
        "id": vehicle["id"],
        "plate_number": vehicle.get("plate_number"),
        "brand": vehicle.get("brand"),
        "model": vehicle.get("model"),
        "transport_type": transport_type,
        "transport_type_name": (
            labels.label("transport_type", transport_type, lang) if transport_type else None),
        "usage_mode": vehicle.get("usage_mode"),
        "current_status": vehicle.get("current_status"),
        "release_year": release.year if release else None,
        # Bazada chiqarilgan sana doim 1-yanvar — ya'ni aniqlik YIL.
        "age_years": ref_date.year - release.year if release else None,
    }


def _repair_items(
    own: list[dict[str, Any]],
    parts_by_repair: dict[str, list[dict[str, Any]]],
    trips_known: bool,
    lang: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for repair in own:
        counted = _counted(repair)
        raw_before = repair.get("trips_before")
        trips_before = int(raw_before) if trips_known and raw_before is not None else None
        since = None
        if (counted and previous is not None and trips_before is not None
                and previous["trips_before"] is not None):
            since = trips_before - previous["trips_before"]
        context = (repair.get("inspection_context") or "").upper() or None
        component = repair.get("component_category")
        item = {
            "id": repair["id"],
            "repair_number": repair.get("repair_number"),
            "occurred_at": _occurred(repair),
            "status": repair.get("status"),
            "is_open": (repair.get("status") or "") not in CLOSED_REPAIR_STATUSES,
            "counted": counted,
            "component": component,
            "component_name": labels.label("component", component, lang),
            "context": context,
            "context_name": labels.label("context", context, lang) if context else None,
            "defect_area": repair.get("defect_area"),
            "defect_reason": repair.get("defect_reason"),
            "work_performed": repair.get("work_performed"),
            "driver_name": repair.get("driver_name"),
            "trips_before": trips_before,
            "trips_since_previous": since,
            "downtime_hours": downtime_hours(repair),
            "estimated_cost": _float(repair.get("estimated_cost")),
            "parts": parts_by_repair.get(repair["id"], []),
        }
        items.append(item)
        if counted:
            previous = item
    return items


def _peer_stats(kind: str, name: str, members: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Guruhdagi BUZILMAGAN FAOL mashinalarning medianalari."""
    healthy = [m for m in members if _healthy(m)]
    if not healthy:
        return None
    return {
        "kind": kind,
        "name": name,
        "healthy_vehicles": len(healthy),
        "median_release_year": _median([m["vehicle"]["release_year"] for m in healthy]),
        "median_trips": _median([m["trips"] for m in healthy]),
        "median_drivers": _median([m["drivers"] for m in healthy]),
    }


def _healthy(stat: dict[str, Any]) -> bool:
    return stat["trips"] is not None and stat["trips"] > 0 and stat["breakdowns"] == 0


# --------------------------------------------------------------------- Faktlar


def _signals(
    stat: dict[str, Any],
    *,
    peer: dict[str, Any] | None,
    factors: dict[str, Any],
    fleet_trips_per_breakdown: int | float | None,
    driver_trips: Counter,
    driver_breakdowns: Counter,
    driver_names: dict[str, str | None],
    ref_date: date,
    lang: str,
) -> list[dict[str, str]]:
    """Buzilgan mashina haqidagi o'lchangan faktlar — sabab emas, dalil."""
    out: list[dict[str, str]] = []

    def add(code: str, **kwargs: Any) -> None:
        out.append({"code": code, "text": t(lang, f"signal.{code}", **kwargs)})

    vehicle_id = stat["vehicle"]["id"]
    counted: list[dict[str, Any]] = stat["_counted"]
    items = [i for i in stat["repairs"] if i["counted"]]
    trips = stat["trips"]

    if trips == 0:
        add("NO_TRIPS_RECORDED")

    if peer:
        group = peer["name"]
        peer_trips = peer["median_trips"]

        year, peer_year = stat["vehicle"]["release_year"], peer["median_release_year"]
        if year is not None and peer_year is not None and year != peer_year:
            add("OLDER_THAN_PEERS" if year < peer_year else "NEWER_THAN_PEERS",
                year=year, group=group, peer_year=_num(peer_year),
                years=_num(abs(peer_year - year)))

        if trips and peer_trips is not None and trips != peer_trips:
            add("MORE_TRIPS_THAN_PEERS" if trips > peer_trips else "FEWER_TRIPS_THAN_PEERS",
                trips=trips, group=group, peer_trips=_num(peer_trips))

        drivers, peer_drivers = stat["drivers"], peer["median_drivers"]
        if drivers is not None and peer_drivers is not None and drivers > peer_drivers:
            add("MORE_DRIVERS_THAN_PEERS", drivers=drivers, group=group,
                peer_drivers=_num(peer_drivers))

    for component, count in Counter(i["component"] for i in items).items():
        if count > 1:
            add("REPEATED_COMPONENT",
                component=labels.label("component", component, lang), count=count)

    for previous, current in zip(items, items[1:]):
        if current["trips_since_previous"] is not None:
            add("REPEAT_BREAKDOWN", previous=previous["repair_number"] or "?",
                trips=current["trips_since_previous"], current=current["repair_number"] or "?")

    by_driver = Counter(
        r.get("driver_id") or r.get("driver_name")
        for r in counted if r.get("driver_id") or r.get("driver_name")
    )
    names_in_repairs = {
        (r.get("driver_id") or r.get("driver_name")): r.get("driver_name") for r in counted
    }
    for key, same in by_driver.items():
        if same > 1:
            add("SAME_DRIVER", same=same, count=len(counted),
                driver=names_in_repairs.get(key) or driver_names.get(key) or key)

    seen: set[str] = set()
    for repair in counted:
        driver_id = repair.get("driver_id")
        if not driver_id or driver_id in seen:
            continue
        seen.add(driver_id)
        trips_driven = driver_trips.get(driver_id)
        breakdowns = driver_breakdowns.get(driver_id)
        # Faqat TAKROR bo'lsa (2+ buzilish): bitta hodisa haydovchini
        # tasodifdan ajrata olmaydi. 14.09.2026 da bu shartsiz fakt 8 ta
        # haydovchining 7 tasida chiqardi — park bo'yicha 74.7 reysga bitta
        # buzilish bo'lganda bir marta buzilgan har kim "yomon" ko'rinardi.
        if (trips_driven and breakdowns and breakdowns > 1
                and fleet_trips_per_breakdown is not None
                and trips_driven / breakdowns < fleet_trips_per_breakdown):
            add("DRIVER_HIGH_RATE",
                driver=repair.get("driver_name") or driver_names.get(driver_id) or driver_id,
                trips=trips_driven, breakdowns=breakdowns, fleet=_num(fleet_trips_per_breakdown))

    for repair in counted:
        if (repair.get("rework_count") or 0) > 0 or (
                (repair.get("mechanic_recheck_decision") or "").lower() == "failed"):
            add("REWORK", number=repair.get("repair_number") or "?")

    # ------------------------------------------------ Sabab jadvallari
    speed = factors.get("speed_violation")
    if speed and speed.get(vehicle_id, {}).get("count"):
        row = speed[vehicle_id]
        add("SPEEDING", count=row["count"], max=_num(row.get("max_excess_kph")))

    incidents = factors.get("incident")
    if incidents and vehicle_id in incidents:
        harsh = sum(n for kind, n in incidents[vehicle_id].items() if kind in HARSH_INCIDENT_TYPES)
        if harsh:
            add("HARSH_DRIVING", count=harsh)

    accidents = factors.get("vehicle_accident")
    if accidents and accidents.get(vehicle_id, {}).get("count"):
        row = accidents[vehicle_id]
        add("ACCIDENT", count=row["count"], repair=row.get("repair_required") or 0)

    plans = factors.get("maintenance_plan")
    if plans and vehicle_id in plans:
        for repair in counted:
            on_day = _date(_occurred(repair))
            if on_day is None:
                continue
            late = []
            for plan in plans[vehicle_id]:
                due = _date(plan.get("next_due_at"))
                served = _date(plan.get("last_serviced_at"))
                # Reja HOZIRGI holat: xizmat buzilishdan keyin o'tkazilgan
                # bo'lsa `next_due_at` allaqachon siljigan, ya'ni bu shart
                # yolg'on ijobiy bermaydi.
                if due is not None and due < on_day and (served is None or served < due):
                    late.append((due, plan))
            if late:
                due, plan = min(late, key=lambda pair: pair[0])
                kind = (labels.label("maintenance_kind", plan["kind"], lang) if plan.get("kind")
                        else labels.label("maintenance_type", plan.get("maintenance_type"), lang))
                add("MAINTENANCE_OVERDUE", number=repair.get("repair_number") or "?",
                    kind=kind, due=due.isoformat())

    parts = factors.get("vehicle_part")
    if parts and vehicle_id in parts:
        worn: set[str] = set()
        for part in parts[vehicle_id]:
            installed = _date(part.get("installed_at"))
            life_days = part.get("expected_life_days")
            by_days = (installed is not None and life_days is not None
                       and installed + timedelta(days=int(life_days)) < ref_date)
            installed_km = _float(part.get("installed_at_km"))
            life_km = _float(part.get("expected_life_km"))
            current_km = _float(part.get("current_odometer_km"))
            by_km = (None not in (installed_km, life_km, current_km)
                     and current_km - installed_km > life_km)
            if part.get("status") == "WORN" or by_days or by_km:
                worn.add(part.get("name") or "?")
        if worn:
            add("PART_PAST_LIFE", parts=", ".join(sorted(worn)))

    return out


def assess_predictive_risk(stat: dict[str, Any], lang: str = "uz") -> dict[str, Any]:
    """Transport vositasi bo'yicha bashoratli texnik xizmat xavfini baholash."""
    score = 0
    factors: list[str] = []
    signals = stat.get("signals") or []
    signal_codes = {s.get("code") for s in signals}

    breakdowns = stat.get("breakdowns") or 0
    if breakdowns >= 3:
        score += 3
        factors.append("FREQUENT_BREAKDOWNS")
    elif breakdowns >= 2:
        score += 2
        factors.append("MULTIPLE_BREAKDOWNS")

    if "REPEAT_BREAKDOWN" in signal_codes:
        score += 3
        factors.append("REPEAT_BREAKDOWN")
    if "MAINTENANCE_OVERDUE" in signal_codes:
        score += 3
        factors.append("MAINTENANCE_OVERDUE")
    if "PART_PAST_LIFE" in signal_codes:
        score += 2
        factors.append("PART_PAST_LIFE")
    if "REWORK" in signal_codes:
        score += 2
        factors.append("REWORK")
    if "HARSH_DRIVING" in signal_codes or "SPEEDING" in signal_codes:
        score += 1
        factors.append("AGGRESSIVE_OPERATION")

    if score >= 4:
        level = "HIGH"
    elif score >= 2:
        level = "MEDIUM"
    else:
        level = "LOW"

    recommendations = {
        "HIGH": {
            "uz": "Zudlik bilan to'liq diagnostika va nosozlik takrorlangan tugunlarni chuqur tekshirish zarur.",
            "ru": "Необходима срочная полная диагностика и углубленная проверка проблемных узлов.",
            "en": "Immediate full diagnostic inspection and overhaul of repeated failure components required.",
        },
        "MEDIUM": {
            "uz": "Rejali texnik xizmat ko'rsatish va eskirgan qismlarni almashtirish tavsiya etiladi.",
            "ru": "Рекомендуется плановое техническое обслуживание и превентивная замена изношенных деталей.",
            "en": "Scheduled preventive maintenance and replacement of worn components recommended.",
        },
        "LOW": {
            "uz": "Texnik holat me'yorda; muntazam reja asosida monitoring davom ettirilsin.",
            "ru": "Техническое состояние в норме; продолжать регулярный плановый мониторинг.",
            "en": "Technical state within normal range; continue routine scheduled monitoring.",
        },
    }
    rec_lang = lang if lang in ("uz", "ru", "en") else "uz"
    return {
        "risk_level": level,
        "score": score,
        "factors": factors,
        "recommendation": recommendations[level][rec_lang],
    }


# --------------------------------------------------------------------- Hisobot


def build_report(
    *,
    vehicles: list[dict[str, Any]],
    repairs: list[dict[str, Any]],
    workload: list[dict[str, Any]],
    driver_trips: list[dict[str, Any]],
    parts: list[dict[str, Any]],
    factors: dict[str, Any],
    row_counts: dict[str, int],
    date_from: date | None,
    date_to: date | None,
    today: date,
    limit: int,
    lang: str,
    truncated_at: int | None = None,
) -> dict[str, Any]:
    """Bazadan o'qilgan qatorlardan to'liq hisobot quradi (LLM tahlilisiz).

    `repairs`, `workload`, `driver_trips` BUTUN PARK bo'yicha keladi,
    `vehicles` esa filtrlangan bo'lishi mumkin: haydovchining buzilish
    tezligi uni boshqa turdagi mashinada ham hisobga olib solishtirilishi
    kerak.

    `truncated_at` — o'qish resurs chegarasiga yetgan bo'lsa o'sha chegara;
    izohda ochiq yoziladi.
    """
    ref_date = date_to or today
    trips_known = (row_counts.get("trip") or 0) > 0

    # ------------------------------------------------ Ish hajmi
    work = {row["vehicle_id"]: row for row in workload}

    def trips_of(vehicle_id: str) -> int | None:
        if not trips_known:
            return None
        value = (work.get(vehicle_id) or {}).get("trips")
        # `trip` da yozuv bor, shu mashinada esa yo'q — O'LCHANGAN nol.
        return int(value) if value is not None else 0

    driver_total_trips: Counter = Counter()
    driver_names: dict[str, str | None] = {}
    vehicle_drivers: dict[str, set[str]] = defaultdict(set)
    for row in driver_trips:
        driver_id = row.get("driver_id")
        if not driver_id:
            continue
        driver_total_trips[driver_id] += int(row["trips"])
        driver_names.setdefault(driver_id, row.get("full_name"))
        vehicle_drivers[row["vehicle_id"]].add(driver_id)

    # Haydovchi solishtirishi BUTUN PARK bo'yicha (filtrdan qat'i nazar).
    counted_fleet = [r for r in repairs if _counted(r)]
    driver_breakdowns = Counter(r["driver_id"] for r in counted_fleet if r.get("driver_id"))
    fleet_trips_all = (
        sum(int(row["trips"]) for row in workload if row.get("trips") is not None)
        if trips_known else None
    )
    fleet_tpb_all = _ratio(fleet_trips_all, len(counted_fleet))

    # ------------------------------------------------ Mashinalar
    vehicle_ids = {v["id"] for v in vehicles}
    by_vehicle: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for repair in sorted((r for r in repairs if r["vehicle_id"] in vehicle_ids), key=_occurred_key):
        by_vehicle[repair["vehicle_id"]].append(repair)

    parts_by_repair: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for part in parts:
        used = _float(part.get("used_quantity"))
        parts_by_repair[part["repair_id"]].append({
            "item_name": part.get("item_name"),
            "status": part.get("status"),
            "quantity": used if used else _float(part.get("requested_quantity")),
            "unit": part.get("unit_of_measure"),
        })

    stats: list[dict[str, Any]] = []
    for vehicle in vehicles:
        vehicle_id = vehicle["id"]
        own = by_vehicle.get(vehicle_id, [])
        counted = [r for r in own if _counted(r)]
        trips = trips_of(vehicle_id)
        items = _repair_items(own, parts_by_repair, trips_known, lang)
        downtimes = [i["downtime_hours"] for i in items
                     if i["counted"] and i["downtime_hours"] is not None]
        costs = [i["estimated_cost"] for i in items
                 if i["counted"] and i["estimated_cost"] is not None]
        moments = [m for m in (_occurred(r) for r in counted) if m is not None]
        row = work.get(vehicle_id) or {}
        components = Counter(r.get("component_category") for r in counted)
        stats.append({
            "vehicle": _vehicle_ref(vehicle, ref_date, lang),
            "breakdowns": len(counted),
            "repairs_excluded": len(own) - len(counted),
            "breakdowns_open": sum(1 for i in items if i["counted"] and i["is_open"]),
            "trips": trips,
            "drivers": len(vehicle_drivers.get(vehicle_id, ())) if trips_known else None,
            "engine_hours": (_num(row.get("engine_hours"))
                             if vehicle.get("usage_mode") in MOTOHOUR_MODES else None),
            "trips_per_breakdown": _ratio(trips, len(counted)),
            "first_breakdown_after_trips": next(
                (i["trips_before"] for i in items if i["counted"]), None),
            "avg_downtime_hours": round(sum(downtimes) / len(downtimes), 1) if downtimes else None,
            "repair_cost": round(sum(costs), 2) if costs else None,
            "last_breakdown_at": max(moments) if moments else None,
            "components": [
                {"code": code, "name": labels.label("component", code, lang),
                 "count": count, "share": None}
                for code, count in components.most_common()
            ],
            "peer_group": None,
            "signals": [],
            "repairs": items,
            "_model": _model_key(vehicle),
            "_counted": counted,
        })

    # ------------------------------------------------ Guruhlar
    model_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    type_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stat in stats:
        if stat["_model"]:
            model_groups[stat["_model"][0]].append(stat)
        if stat["vehicle"]["transport_type"]:
            type_groups[stat["vehicle"]["transport_type"]].append(stat)

    for stat in stats:
        if not stat["breakdowns"]:
            continue
        peer = None
        if stat["_model"]:
            peer = _peer_stats("model", stat["_model"][1], model_groups[stat["_model"][0]])
        transport_type = stat["vehicle"]["transport_type"]
        if peer is None and transport_type:
            peer = _peer_stats("transport_type", labels.label("transport_type", transport_type, lang),
                               type_groups[transport_type])
        stat["peer_group"] = peer
        stat["signals"] = _signals(
            stat, peer=peer, factors=factors, fleet_trips_per_breakdown=fleet_tpb_all,
            driver_trips=driver_total_trips, driver_breakdowns=driver_breakdowns,
            driver_names=driver_names, ref_date=ref_date, lang=lang,
        )
        stat["predictive_risk"] = assess_predictive_risk(stat, lang=lang)

    # ------------------------------------------------ Ro'yxatlar
    broken = sorted(
        (s for s in stats if s["breakdowns"]),
        key=lambda s: (-s["breakdowns"], s["trips_per_breakdown"] is None,
                       s["trips_per_breakdown"] or 0, s["vehicle"]["plate_number"] or ""),
    )
    most_broken = broken[:limit]
    shown = {s["vehicle"]["id"] for s in most_broken}

    # Kam buzilayotgan = KO'P ISHLAB kam buzilgan. Reysi yo'q mashina bu
    # ro'yxatga TUSHMAYDI: u buzilmagani uchun emas, ishlamagani uchun toza.
    active = sorted(
        (s for s in stats if s["trips"] and s["vehicle"]["id"] not in shown),
        key=lambda s: (s["breakdowns"] > 0,
                       -(s["trips"] if not s["breakdowns"] else (s["trips_per_breakdown"] or 0)),
                       s["vehicle"]["plate_number"] or ""),
    )
    least_broken = active[:limit]
    idle = [s for s in stats if s["trips"] == 0 and not s["breakdowns"]]

    # ------------------------------------------------ Umumiy
    counted_all = [r for s in stats for r in s["_counted"]]
    items_all = [i for s in stats for i in s["repairs"] if i["counted"]]
    total = len(counted_all)
    trips_total = sum(s["trips"] for s in stats) if trips_known else None

    def shares(counter: Counter, group: str) -> list[dict[str, Any]]:
        return [
            {"code": code, "name": labels.label(group, code, lang), "count": count,
             "share": round(count / total, 3) if total else None}
            for code, count in counter.most_common()
        ]

    def group_rows(key_of, name_of) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for stat in stats:
            key = key_of(stat)
            if key:
                groups[key].append(stat)
        rows = []
        for key, members in groups.items():
            breakdowns = sum(m["breakdowns"] for m in members)
            trips = sum(m["trips"] for m in members) if trips_known else None
            rows.append({
                "key": key,
                "name": name_of(key, members),
                "vehicles": len(members),
                "vehicles_active": sum(1 for m in members if m["trips"]) if trips_known else None,
                "vehicles_broken": sum(1 for m in members if m["breakdowns"]),
                "breakdowns": breakdowns,
                "trips": trips,
                "trips_per_breakdown": _ratio(trips, breakdowns),
            })
        rows.sort(key=lambda r: (-r["breakdowns"], r["trips_per_breakdown"] is None,
                                 r["trips_per_breakdown"] or 0, -r["vehicles"], r["name"]))
        return rows

    downtimes_all = [i["downtime_hours"] for i in items_all if i["downtime_hours"] is not None]
    moments_all = [m for m in (_occurred(r) for r in counted_all) if m is not None]

    summary = {
        "vehicles_total": len(stats),
        "vehicles_active": sum(1 for s in stats if s["trips"]) if trips_known else None,
        "vehicles_broken": sum(1 for s in stats if s["breakdowns"]),
        "vehicles_no_activity": len(idle) if trips_known else None,
        "breakdowns_total": total,
        "breakdowns_open": sum(s["breakdowns_open"] for s in stats),
        "repairs_excluded": sum(s["repairs_excluded"] for s in stats),
        "trips_total": trips_total,
        "trips_per_breakdown": _ratio(trips_total, total),
        "avg_downtime_hours": (
            round(sum(downtimes_all) / len(downtimes_all), 1) if downtimes_all else None),
        "downtime_measured": len(downtimes_all),
        "by_component": shares(Counter(r.get("component_category") for r in counted_all),
                               "component"),
        "by_context": shares(
            Counter(i["context"] for i in items_all if i["context"]), "context"),
        "by_transport_type": group_rows(
            lambda s: s["vehicle"]["transport_type"],
            lambda key, _m: labels.label("transport_type", key, lang)),
        "by_brand": group_rows(
            lambda s: " ".join((s["vehicle"]["brand"] or "").casefold().split()) or None,
            lambda _key, members: (members[0]["vehicle"]["brand"] or "").strip()),
        "by_model": group_rows(
            lambda s: s["_model"][0] if s["_model"] else None,
            lambda _key, members: members[0]["_model"][1]),
    }

    # ------------------------------------------------ Model guruhlari
    cohorts = []
    for members in model_groups.values():
        broken_members = [m for m in members if m["breakdowns"]]
        # Kamida ikki mashina — solishtirishning ta'rifi, meyor emas.
        if len(members) < 2 or not broken_members:
            continue
        name = members[0]["_model"][1]
        peer = _peer_stats("model", name, members)
        median_year = peer["median_release_year"] if peer else None
        cohorts.append({
            "model": name,
            "transport_types": sorted({
                labels.label("transport_type", m["vehicle"]["transport_type"], lang)
                for m in members if m["vehicle"]["transport_type"]
            }),
            "vehicles": len(members),
            "vehicles_active": sum(1 for m in members if m["trips"]) if trips_known else None,
            "vehicles_broken": len(broken_members),
            "breakdowns": sum(m["breakdowns"] for m in members),
            "healthy": peer,
            "broken": [
                {
                    "vehicle_id": m["vehicle"]["id"],
                    "plate_number": m["vehicle"]["plate_number"],
                    "breakdowns": m["breakdowns"],
                    "release_year": m["vehicle"]["release_year"],
                    "trips": m["trips"],
                    "drivers": m["drivers"],
                    "first_breakdown_after_trips": m["first_breakdown_after_trips"],
                    # Erta = hayotida erta: buzilmagan guruhdoshlaridan YANGI.
                    "early": (m["vehicle"]["release_year"] > median_year
                              if m["vehicle"]["release_year"] is not None
                              and median_year is not None else None),
                }
                for m in sorted(broken_members, key=lambda m: -m["breakdowns"])
            ],
        })
    cohorts.sort(key=lambda c: (-c["breakdowns"], -c["vehicles"], c["model"]))

    # ------------------------------------------------ Haydovchilar
    drivers: dict[str, dict[str, Any]] = {}
    for stat in stats:
        for repair in stat["_counted"]:
            driver_id = repair.get("driver_id")
            key = driver_id or repair.get("driver_name")
            if not key:
                continue
            row = drivers.setdefault(key, {
                "driver_id": driver_id,
                "full_name": repair.get("driver_name") or driver_names.get(driver_id or ""),
                "breakdowns": 0,
                "vehicles": set(),
            })
            row["breakdowns"] += 1
            if stat["vehicle"]["plate_number"]:
                row["vehicles"].add(stat["vehicle"]["plate_number"])
    driver_rows = []
    for row in drivers.values():
        trips = (driver_total_trips.get(row["driver_id"], 0)
                 if trips_known and row["driver_id"] else None)
        driver_rows.append({**row, "vehicles": sorted(row["vehicles"]), "trips": trips,
                            "trips_per_breakdown": _ratio(trips, row["breakdowns"])})
    driver_rows.sort(key=lambda r: (-r["breakdowns"], r["trips_per_breakdown"] is None,
                                    r["trips_per_breakdown"] or 0, r["full_name"] or ""))

    # ------------------------------------------------ Ma'lumot sifati
    notes: list[str] = []
    unchecked = [table for table in FACTOR_TABLES if factors.get(table) is None]
    if unchecked:
        notes.append(t(lang, "note.factors_unchecked", items=", ".join(
            f"{t(lang, f'factor.{table}')} (`{table}`)" for table in unchecked)))
    if not trips_known:
        notes.append(t(lang, "note.no_trip_data"))
    if summary["repairs_excluded"]:
        notes.append(t(lang, "note.excluded_repairs", count=summary["repairs_excluded"]))
    without_trips = [s["vehicle"]["plate_number"] or s["vehicle"]["id"]
                     for s in broken if s["trips"] == 0]
    if without_trips:
        notes.append(t(lang, "note.broken_without_trips", count=len(without_trips),
                       plates=", ".join(without_trips)))
    no_year = sum(1 for s in stats if s["vehicle"]["release_year"] is None)
    if no_year:
        notes.append(t(lang, "note.no_release_year", count=no_year))
    if total and not any(i["estimated_cost"] is not None for i in items_all):
        notes.append(t(lang, "note.no_cost"))
    if truncated_at:
        notes.append(t(lang, "note.max_rows", limit=truncated_at))
    if not total:
        notes.append(t(lang, "note.no_breakdowns"))

    for stat in stats:
        for key in [k for k in stat if k.startswith("_")]:
            del stat[key]

    return {
        "period": {
            "date_from": date_from,
            "date_to": date_to,
            "first_breakdown_at": min(moments_all) if moments_all else None,
            "last_breakdown_at": max(moments_all) if moments_all else None,
        },
        "summary": summary,
        "most_broken": [{"rank": n, **s} for n, s in enumerate(most_broken, 1)],
        "least_broken": [{"rank": n, **s} for n, s in enumerate(least_broken, 1)],
        "no_activity": [s["vehicle"] for s in idle[:limit]],
        "cohorts": cohorts[:limit],
        "drivers": driver_rows[:limit],
        "data_quality": {
            "row_counts": row_counts,
            "factors_unchecked": unchecked,
            "notes": notes,
        },
    }
