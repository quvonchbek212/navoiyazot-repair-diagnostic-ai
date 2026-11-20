"""Bazadan buzilish ma'lumotlarini o'qish — FAQAT SELECT, parametrli.

O'n bir jadval o'qiladi:

    ma'lumoti bor (14.09.2026)
        vehicle_repair             buzilish: tizim, vaqt, haydovchi, ta'mir
        transport_vehicle          model guruhi, chiqarilgan yil, tur
        trip                       ish hajmi: yakunlangan reys, haydovchilar
        waybill                    motosoat (`motohours_worked`)
        repair_order_part_request  ta'mirda ishlatilgan ehtiyot qism
        driver                     haydovchi ismi

    hozir bo'sh — sabab omili sifatida ulangan, to'lganda o'zi ishlaydi
        speed_violation            tezlikni oshirish
        incident                   keskin tormoz/tezlanish
        vehicle_accident           avariyalar
        maintenance_plan           texnik xizmat muddati
        vehicle_part               ehtiyot qism resursi

ATAYLAB O'QILMAYDI: `vehicle_technical_inspection` dagi `BLOCKED` ko'riklar.
14.09.2026 da 153 ta shunday yozuv bor edi, lekin ular buzilish belgisi
emas: izohida "Chiqish ko'rigi soz", bir mashinada soniyalar ichida
BLOCKED/FIT almashadi, `inspected_at` hammasida 1970 yil va 11 ta ta'mirdan
faqat 1 tasi ularga yaqin tushadi. Ular hisobga olinsa hech qachon
ta'mirlanmagan avtobuslar "eng ko'p buziladigan" bo'lib chiqardi.

BAZAGA ZARAR YETMASLIGI uch qatlam bilan kafolatlangan — `oil_detection/
queries.py` dagi kabi: faqat `select`, READ ONLY tranzaksiya, SELECT huquqli
foydalanuvchi. Sana va filtr FOYDALANUVCHIDAN keladi, shuning uchun
psycopg2 parametrlari ishlatiladi.
"""

from __future__ import annotations

import logging
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

_CHATBOT_DIR = Path(__file__).resolve().parent.parent / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

import psycopg2  # noqa: E402

from db.connect_db_for_server import read_only_cursor  # noqa: E402

from breakdown_report.metrics import FACTOR_TABLES  # noqa: E402

logger = logging.getLogger(__name__)

#: Modul o'qiydigan jadvallar — `data_quality.row_counts` da shular chiqadi.
SOURCE_TABLES = (
    "vehicle_repair",
    "transport_vehicle",
    "trip",
    "waybill",
    "repair_order_part_request",
    "driver",
    *FACTOR_TABLES,
)


class BreakdownDataError(RuntimeError):
    """Bazadan o'qib bo'lmadi — router buni 503 ga aylantiradi."""


def _select(sql: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        with read_only_cursor() as cur:
            cur.execute(sql, dict(params or {}))
            return [dict(row) for row in cur.fetchall()]
    except psycopg2.Error as exc:
        message = (getattr(exc, "pgerror", None) or str(exc)).strip().splitlines()[0]
        logger.warning("Buzilish so'rovi bajarilmadi: %s", message[:300])
        raise BreakdownDataError(message[:300]) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Bazaga ulanishda kutilmagan xato")
        raise BreakdownDataError(f"{type(exc).__name__}: {exc}"[:300]) from exc


def _period(column: str) -> str:
    """Davr sharti. `column` — shu fayldagi ifoda, foydalanuvchidan EMAS.

    Chegara berilmasa (`None`) o'sha tomon ochiq. `date_to` kun oxirigacha
    kiradi: `< date_to + 1`.
    """
    return (
        f"(%(date_from)s::date is null or {column} >= %(date_from)s::date) "
        f"and (%(date_to)s::date is null or {column} < %(date_to)s::date + 1)"
    )


def row_counts(tables: Sequence[str] = SOURCE_TABLES) -> dict[str, int]:
    """Jadvallardagi yozuvlar soni — `count(*)` bilan, bitta so'rovda.

    `pg_stat_user_tables` EMAS: bu bazada statistika yig'ilmagan va u
    yolg'on nol ko'rsatadi (batafsil: `vehicle_selection/queries.py`).
    Bo'sh jadval sabab omilini "tekshirilmadi" qiladi, ya'ni bu son
    TO'G'RI bo'lishi shart.
    """
    names = [name for name in tables if re.fullmatch(r"[a-z_][a-z0-9_]*", name)]
    if not names:
        return {}
    sql = " union all ".join(
        f"select '{name}' as table_name, count(*) as row_count from {name}" for name in names
    )
    counts = {name: 0 for name in tables}
    counts.update({r["table_name"]: int(r["row_count"] or 0) for r in _select(sql)})
    return counts


# ---------------------------------------------------------------- Asosiy

VEHICLES_SQL = """
select v.id::text          as id,
       v.plate_number,
       v.brand,
       v.model,
       v.transport_type,
       v.usage_mode,
       v.current_status,
       v.release_date,
       v.commissioning_date
  from transport_vehicle v
 where (%(transport_type)s::text is null or v.transport_type = %(transport_type)s::text)
 order by v.plate_number nulls last, v.id
 limit %(limit)s
"""


def fetch_vehicles(*, transport_type: str | None, limit: int) -> list[dict[str, Any]]:
    return _select(VEHICLES_SQL, {"transport_type": transport_type, "limit": limit})


def fetch_transport_types() -> list[str]:
    """Bazada mashinasi bor turlar — filtr hech narsa topmaganda izoh uchun."""
    rows = _select("select distinct v.transport_type from transport_vehicle v")
    return [r["transport_type"] for r in rows if r["transport_type"]]


REPAIRS_SQL = f"""
select r.id::text                              as id,
       r.repair_number,
       r.vehicle_id::text                      as vehicle_id,
       r.status,
       r.component_category,
       r.priority,
       r.inspection_context,
       r.defect_area,
       r.defect_reason,
       r.work_performed,
       r.detected_at,
       r.opened_at,
       coalesce(r.detected_at, r.opened_at)    as occurred_at,
       r.repaired_at,
       r.completed_at,
       r.rework_count,
       r.mechanic_recheck_decision,
       r.driver_id::text                       as driver_id,
       r.driver_name,
       r.estimated_cost,
       r.actual_downtime_hours,
       r.downtime_hours,
       -- Buzilishgacha davr ichida nechta yakunlangan reys qilgan.
       -- `count(distinct route_id)`: bitta reys bir necha ariza uchun
       -- bir necha `trip` qatori bo'lib yozilishi mumkin.
       (select count(distinct t.route_id)
          from trip t
         where t.vehicle_id = r.vehicle_id
           and t.status = 'COMPLETED'
           and coalesce(t.actual_departure_at, t.scheduled_departure_at)
               < coalesce(r.detected_at, r.opened_at)
           and (%(date_from)s::date is null
                or coalesce(t.actual_departure_at, t.scheduled_departure_at)
                   >= %(date_from)s::date))       as trips_before
  from vehicle_repair r
 where {_period("coalesce(r.detected_at, r.opened_at)")}
 order by coalesce(r.detected_at, r.opened_at), r.repair_number
 limit %(limit)s
"""


def fetch_repairs(*, date_from: date | None, date_to: date | None, limit: int) -> list[dict[str, Any]]:
    """Davrdagi HAMMA ta'mir yozuvi — butun park bo'yicha (filtr metrics'da)."""
    return _select(REPAIRS_SQL, {"date_from": date_from, "date_to": date_to, "limit": limit})


WORKLOAD_SQL = f"""
with trips as (
    select t.vehicle_id, t.route_id
      from trip t
     where t.status = 'COMPLETED'
       and {_period("coalesce(t.actual_departure_at, t.scheduled_departure_at)")}
     group by t.vehicle_id, t.route_id
),
trip_totals as (
    select vehicle_id, count(*) as trips
      from trips
     group by vehicle_id
),
hours as (
    select w.vehicle_id, sum(w.motohours_worked) as engine_hours
      from waybill w
     where w.status in ('CLOSED', 'RETURNED')
       and w.motohours_worked is not null
       and {_period("w.issue_date")}
     group by w.vehicle_id
)
select v.id::text         as vehicle_id,
       tt.trips,
       h.engine_hours
  from transport_vehicle v
  left join trip_totals tt on tt.vehicle_id = v.id
  left join hours h        on h.vehicle_id = v.id
"""


def fetch_workload(*, date_from: date | None, date_to: date | None) -> list[dict[str, Any]]:
    """Har mashina uchun ish hajmi — BUTUN PARK. Reysi yo'qda `trips` NULL."""
    return _select(WORKLOAD_SQL, {"date_from": date_from, "date_to": date_to})


DRIVER_TRIPS_SQL = f"""
select t.vehicle_id::text          as vehicle_id,
       t.driver_id::text           as driver_id,
       d.full_name,
       count(distinct t.route_id)  as trips
  from trip t
  left join driver d on d.id = t.driver_id
 where t.status = 'COMPLETED'
   and {_period("coalesce(t.actual_departure_at, t.scheduled_departure_at)")}
 group by t.vehicle_id, t.driver_id, d.full_name
 limit %(limit)s
"""


def fetch_driver_trips(*, date_from: date | None, date_to: date | None, limit: int) -> list[dict[str, Any]]:
    return _select(DRIVER_TRIPS_SQL, {"date_from": date_from, "date_to": date_to, "limit": limit})


PARTS_SQL = """
select p.repair_order_id::text as repair_id,
       p.item_name,
       p.status,
       p.requested_quantity,
       p.used_quantity,
       p.unit_of_measure
  from repair_order_part_request p
 where p.repair_order_id = any(%(ids)s::uuid[])
 order by p.requested_at
"""


def fetch_parts(repair_ids: Sequence[str]) -> list[dict[str, Any]]:
    if not repair_ids:
        return []
    return _select(PARTS_SQL, {"ids": list(repair_ids)})


# ---------------------------------------------------------- Sabab omillari
#
# Har biri `{vehicle_id: ...}` qaytaradi. Jadval bo'sh bo'lsa umuman
# chaqirilmaydi (`service.py`) va omil `None` — "tekshirilmadi" bo'ladi.


def fetch_speed_violations(*, date_from: date | None, date_to: date | None) -> dict[str, Any]:
    rows = _select(f"""
        select s.vehicle_id::text as vehicle_id,
               count(*)           as count,
               max(s.excess_kph)  as max_excess_kph
          from speed_violation s
         where {_period("s.occurred_at")}
         group by s.vehicle_id
    """, {"date_from": date_from, "date_to": date_to})
    return {r["vehicle_id"]: {"count": int(r["count"]), "max_excess_kph": r["max_excess_kph"]}
            for r in rows}


def fetch_incidents(*, date_from: date | None, date_to: date | None) -> dict[str, Any]:
    rows = _select(f"""
        select i.vehicle_id::text as vehicle_id, i.incident_type, count(*) as count
          from incident i
         where {_period("i.occurred_at")}
           and i.status <> 'DISMISSED'
         group by i.vehicle_id, i.incident_type
    """, {"date_from": date_from, "date_to": date_to})
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for r in rows:
        out[r["vehicle_id"]][r["incident_type"]] = int(r["count"])
    return dict(out)


def fetch_accidents(*, date_from: date | None, date_to: date | None) -> dict[str, Any]:
    rows = _select(f"""
        select a.vehicle_id::text as vehicle_id,
               count(*)                                   as count,
               count(*) filter (where a.repair_required)  as repair_required
          from vehicle_accident a
         where {_period("a.occurred_at")}
           and a.status <> 'CANCELLED'
         group by a.vehicle_id
    """, {"date_from": date_from, "date_to": date_to})
    return {r["vehicle_id"]: {"count": int(r["count"]), "repair_required": int(r["repair_required"])}
            for r in rows}


def fetch_maintenance_plans(*, date_from: date | None, date_to: date | None) -> dict[str, Any]:
    """Texnik xizmat rejalari — HOZIRGI holat (tarix jadvali yo'q)."""
    rows = _select("""
        select m.vehicle_id::text as vehicle_id, m.kind, m.maintenance_type, m.status,
               m.next_due_at, m.last_serviced_at
          from maintenance_plan m
         where m.next_due_at is not null
    """)
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        out[r["vehicle_id"]].append(r)
    return dict(out)


def fetch_vehicle_parts(*, date_from: date | None, date_to: date | None) -> dict[str, Any]:
    """O'rnatilgan va eskirgan qismlar — resurs muddati bazaning o'zidan."""
    rows = _select("""
        select p.vehicle_id::text as vehicle_id, p.name, p.category, p.status,
               p.installed_at, p.expected_life_days,
               p.installed_at_km, p.expected_life_km, p.current_odometer_km
          from vehicle_part p
         where p.vehicle_id is not null
           and p.status in ('INSTALLED', 'WORN')
    """)
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        out[r["vehicle_id"]].append(r)
    return dict(out)


#: Jadval -> o'quvchi. `FACTOR_TABLES` bilan bir xil kalitlar.
FACTOR_FETCHERS = {
    "speed_violation": fetch_speed_violations,
    "incident": fetch_incidents,
    "vehicle_accident": fetch_accidents,
    "maintenance_plan": fetch_maintenance_plans,
    "vehicle_part": fetch_vehicle_parts,
}
