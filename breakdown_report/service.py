"""Bazadan o'qish va hisobni bir joyga yig'ish — LLM'siz qism.

BITTA KIRISH NUQTASI: `report(...)`. Router uni fon oqimida chaqiradi,
so'ng natijaga `explain.analyze` tahlil qo'shadi.

Bo'sh jadval o'qilmaydi: sabab jadvali bo'sh bo'lsa uning so'rovi
yuborilmaydi va omil `None` ("tekshirilmadi") bo'lib qoladi.

FILTR FAQAT `transport_type`. `brand` filtri olib tashlangan (15.09.2026):
markalar bo'yicha taqsimot `summary.by_brand` va `by_model` da filtrsiz
turadi, bazadagi marka nomlari esa tartibsiz (`1`, `c-1402`, `T-28X4MC`) va
`brand=samosval` kabi tur bilan chalkashlikka olib keldi.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any

from breakdown_report import config, metrics, queries, texts
from atil_ai_dispetcher.vehicle_selection import labels as vs_labels


class FilterNotMatched(ValueError):
    """Filtrga birorta mashina mos kelmadi — router 400 qaytaradi.

    NIMA UCHUN XATO, BO'SH HISOBOT EMAS (15.09.2026): hech narsa topmagan
    filtr 0 mashinali hisobot qaytarardi va izohda "buzilish yozuvi yo'q"
    deb yozilardi — go'yo mashinalar buzilmagan.
    """


def filter_problem(
    *, transport_type: str, types: list[str], lang: str = texts.DEFAULT_LANG
) -> str:
    """Tur nega hech narsa topmaganini aytadi — so'ralgan tilda, tur nomlari ham.

    `types` — bazada mashinasi bor turlar. Kod qavsda qoladi: foydalanuvchi
    uni filtrga ko'chirib yozishi mumkin.
    """
    names = ", ".join(
        f"{vs_labels.label('transport_type', code, lang)} ({code})" for code in sorted(types))
    unknown = (texts.t(lang, "error.unknown_type")
               if transport_type not in vs_labels.TRANSPORT_TYPE else "")
    return texts.t(lang, "error.no_vehicles_for_type",
                   given=transport_type, unknown=unknown, types=names)


def report(
    *,
    date_from: date | None,
    date_to: date | None,
    transport_type: str | None,
    limit: int,
    lang: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    period = {"date_from": date_from, "date_to": date_to}

    counts = queries.row_counts()
    vehicles = queries.fetch_vehicles(transport_type=transport_type, limit=config.MAX_ROWS)
    if not vehicles and transport_type:
        # Faqat natija bo'sh bo'lganda qo'shimcha so'rov — to'g'ri filtrga narxi yo'q.
        raise FilterNotMatched(filter_problem(
            transport_type=transport_type, types=queries.fetch_transport_types(), lang=lang))

    repairs = (queries.fetch_repairs(**period, limit=config.MAX_ROWS)
               if counts.get("vehicle_repair") else [])
    workload = (queries.fetch_workload(**period)
                if counts.get("trip") or counts.get("waybill") else [])
    driver_trips = (queries.fetch_driver_trips(**period, limit=config.MAX_ROWS)
                    if counts.get("trip") else [])
    parts = (queries.fetch_parts([r["id"] for r in repairs])
             if counts.get("repair_order_part_request") and repairs else [])
    factors = {
        table: queries.FACTOR_FETCHERS[table](**period) if counts.get(table) else None
        for table in metrics.FACTOR_TABLES
    }
    truncated = (len(vehicles) >= config.MAX_ROWS or len(repairs) >= config.MAX_ROWS
                 or len(driver_trips) >= config.MAX_ROWS)

    result = metrics.build_report(
        vehicles=vehicles,
        repairs=repairs,
        workload=workload,
        driver_trips=driver_trips,
        parts=parts,
        factors=factors,
        row_counts=counts,
        date_from=date_from,
        date_to=date_to,
        today=date.today(),
        limit=limit,
        lang=lang,
        truncated_at=config.MAX_ROWS if truncated else None,
    )
    db_seconds = round(time.perf_counter() - started, 2)
    result["generated_at"] = datetime.now()
    result["filters"] = {"transport_type": transport_type}
    # Router LLM tahlilidan keyin `llm` ni qo'shadi va `elapsed_seconds` ni
    # BUTUN javob vaqtiga almashtiradi.
    result["timings"] = {"db": db_seconds}
    result["elapsed_seconds"] = db_seconds
    return result
