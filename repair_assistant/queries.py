"""Bazadan o'qish — FAQAT SELECT, parametrli, READ ONLY tranzaksiyada.

ALOMAT MATNI O'QILADI: o'xshash ta'mirni topish uchun mexanik nima
yozgani kerak. Shuning uchun bu modul faqat ichki vLLM bilan ishlaydi
(`llm.py`).

Erkin matn ustunlari `FREE_TEXT_COLUMNS` da sanab qo'yilgan; test SQL da
ulardan boshqa matn ustuni yo'qligini tekshiradi. Ism ustunlari (`*_by`,
`*_name`) baribir o'qilmaydi: alomat kerak, uni kim yozgani — yo'q.

Matn qaysi ustunda (31.10.2026, 20 naryad):

    initial_diagnosis   19/20  mexanik yozgan alomat ("tormoz pedali yumshoq...")
    defect_area         19/20  qisqa joy nomi ("Tormoz tizimi")
    work_performed      16/20  nima qilingani; 7 tasida bitta shablon ("Barcha ta'mirlash...")
    work_items          19 qator, 14 naryadda — ish bandlari ("shina yamaldi")
    arm_diagnosis       18/20  "Tekshiruv o'tkazildi: " + initial_diagnosis — nusxa, O'QILMAYDI
    description         15/20  "Nosozlik aniqlandi" — O'QILMAYDI
    final_conclusion    16/16  bitta shablon — O'QILMAYDI
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

_CHATBOT_DIR = Path(__file__).resolve().parent.parent / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

import psycopg2  # noqa: E402

from db.connect_db_for_server import read_only_cursor  # noqa: E402

logger = logging.getLogger(__name__)

#: SQL da o'qiladigan erkin matn ustunlari — boshqasi yo'q (test tekshiradi).
FREE_TEXT_COLUMNS = ("initial_diagnosis", "defect_area", "work_performed")
WORK_ITEM_TEXT_COLUMNS = ("description",)


class RepairDataError(RuntimeError):
    """Bazadan o'qib bo'lmadi — router buni 503 ga aylantiradi."""


def _select(sql: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        with read_only_cursor() as cur:
            cur.execute(sql, dict(params or {}))
            return [dict(row) for row in cur.fetchall()]
    except psycopg2.Error as exc:
        message = (getattr(exc, "pgerror", None) or str(exc)).strip().splitlines()[0]
        logger.warning("Ta'mir yordamchisi so'rovi bajarilmadi: %s", message[:300])
        raise RepairDataError(message[:300]) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Bazaga ulanishda kutilmagan xato")
        raise RepairDataError(f"{type(exc).__name__}: {exc}"[:300]) from exc


# Eng YANGISIDAN: `RA_MAX_ROWS` ga yetilsa eski tarix tushib qoladi, hozir
# ochiq naryad emas.
REPAIRS_SQL = """
select r.id::text                  as id,
       r.repair_number,
       r.vehicle_id::text          as vehicle_id,
       r.status,
       r.component_category,
       r.opened_at,
       r.received_by_arm_at,
       r.chief_mechanic_diagnosed_at,
       r.estimated_completion_time,
       r.repaired_at,
       r.final_arm_approved_at,
       r.completed_at,
       r.initial_diagnosis,
       r.defect_area,
       r.work_performed,
       v.plate_number,
       v.brand,
       v.model,
       v.transport_type
  from vehicle_repair r
  left join transport_vehicle v on v.id = r.vehicle_id
 order by r.opened_at desc, r.repair_number
 limit %(limit)s
"""


def fetch_repairs(*, limit: int) -> list[dict[str, Any]]:
    """Butun tarix: o'xshash ta'mirlar shundan tanlanadi."""
    rows = _select(REPAIRS_SQL, {"limit": limit})
    if len(rows) >= limit:
        logger.warning("Naryadlar RA_MAX_ROWS=%d da qirqildi — eski tarix olinmadi", limit)
    return rows


PARTS_SQL = """
select p.repair_order_id::text as repair_id,
       p.item_name,
       p.status,
       p.requested_at,
       p.issued_at
  from repair_order_part_request p
 where p.repair_order_id = any(%(ids)s::uuid[])
 order by p.requested_at
"""


def fetch_parts(repair_ids: Sequence[str]) -> list[dict[str, Any]]:
    if not repair_ids:
        return []
    return _select(PARTS_SQL, {"ids": list(repair_ids)})


#: Ish bandlari: `category` 30.10.2026 da 19 tadan 0 tasida to'ldirilgan — o'qilmaydi.
WORK_ITEMS_SQL = """
select w.repair_id::text as repair_id,
       w.description,
       w.completed
  from vehicle_repair_work_items w
 where w.repair_id = any(%(ids)s::uuid[])
"""


def fetch_work_items(repair_ids: Sequence[str]) -> list[dict[str, Any]]:
    if not repair_ids:
        return []
    return _select(WORK_ITEMS_SQL, {"ids": list(repair_ids)})


# ------------------------------------------------------- Takroriy nosozlik (bitta mashina)

VEHICLE_SQL = """
select v.id::text as id,
       v.plate_number,
       v.brand,
       v.model,
       v.transport_type
  from transport_vehicle v
 where v.id = %(id)s::uuid
"""


def fetch_vehicle(vehicle_id: str) -> dict[str, Any] | None:
    rows = _select(VEHICLE_SQL, {"id": vehicle_id})
    return rows[0] if rows else None


# Reys `trip` dan emas, `waybill` dan: `trip` vaqtlari zonasiz va `waybill` dan
# roppa-rosa 5 soat farq qiladi (28.10.2026).
WAYBILLS_SQL = """
select w.actual_departure_at
  from waybill w
 where w.vehicle_id = %(id)s::uuid
   and w.status <> 'CANCELLED'
   and w.actual_departure_at >= %(since)s
"""

#: Texnik ko'rik: faqat vaqt va holat — izoh (`notes`) o'qilmaydi. BLOCKED
#: ko'riklarning hammasida `inspected_at = 1970-01-01` (31.10.2026, 165 ta) —
#: `since` filtri ularni o'zi tashlaydi.
INSPECTIONS_SQL = """
select i.inspected_at,
       i.status
  from vehicle_technical_inspection i
 where i.vehicle_id = %(id)s::uuid
   and i.inspected_at >= %(since)s
"""

#: O'rnatilgan shina va akkumulyatorlar: eskirishi — probeg yoki oy bo'yicha.
#: `name` — qism nomi ("Shina 155/70R12 (0065B07138548)"), odam emas.
VEHICLE_PARTS_SQL = """
select p.category,
       p.name,
       p.installed_at,
       p.installed_at_km,
       p.current_odometer_km,
       p.expected_life_km,
       p.expected_life_months
  from vehicle_part p
 where p.vehicle_id = %(id)s::uuid
   and p.removed_at is null
"""


def fetch_vehicle_history(vehicle_id: str, *, since: Any) -> dict[str, list[dict[str, Any]]]:
    """Mashinaning `since` dan keyingi reyslari, ko'riklari va o'rnatilgan qismlari."""
    params = {"id": vehicle_id, "since": since}
    return {
        "waybills": _select(WAYBILLS_SQL, params),
        "inspections": _select(INSPECTIONS_SQL, params),
        "vehicle_parts": _select(VEHICLE_PARTS_SQL, {"id": vehicle_id}),
    }
