"""Buzilish hisoboti endpointi.

Router `main.py` dagi yagona FastAPI ilovasiga ulanadi; autorizatsiya ilova
darajasida (`security.py`), shuning uchun bu yerda qayta yozilmaydi.
"""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from breakdown_report import config, service, texts
from breakdown_report.explain import AnalysisUnavailable, analyze
from breakdown_report.models import BreakdownReport
from breakdown_report.queries import BreakdownDataError
from breakdown_report.service import FilterNotMatched
from atil_ai_dispetcher.vehicle_selection import labels as vs_labels

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/breakdown-report", tags=["Buzilish hisoboti"])


@router.get(
    "/scan",
    response_model=BreakdownReport,
    summary="Eng ko'p va eng kam buzilayotgan transportlar — sabablari bilan",
    responses={
        400: {"description": "`date_from` `date_to` dan katta, yoki bu transport turida mashina yo'q (bazadagi turlar matnda)"},
        503: {"description": "Tahlilni LLM yozib bera olmadi yoki bazaga ulanib bo'lmadi — vaqtinchalik holat, qayta urinish mumkin"},
    },
)
async def scan(
    date_from: date | None = Query(
        None,
        description="Davr boshi. Berilmasa — bazadagi eng birinchi yozuvdan. "
                    "Buzilish `detected_at` bo'yicha, reys jo'nash vaqti bo'yicha olinadi.",
    ),
    date_to: date | None = Query(
        None, description="Davr oxiri (shu kun ham kiradi). Berilmasa — bugungacha."),
    transport_type: str | None = Query(
        None,
        description="Transport turi — kod ham, nom ham: `PASSENGER_CAR`, "
                    "`yengil avtomobil`, `легковой автомобиль`.",
        examples=["PASSENGER_CAR"],
    ),
    limit: int = Query(
        config.DEFAULT_LIMIT, ge=1, le=config.MAX_LIMIT,
        description="Har ro'yxat uzunligi. Jami sonlar `summary` da doim to'liq."),
    lang: Literal["uz", "ru", "en"] = Query(
        "uz",
        description="**Javob tili** — faktlar (`signals[].text`), izohlar va LLM tahlili. "
                    "Kodlar (`signals[].code`, `component`) tarjima qilinmaydi.",
    ),
) -> BreakdownReport:
    """**Qaysi transport ko'p buzilyapti, qaysi biri kam va NEGA.**

    | Bo'lim | Nima |
    |---|---|
    | `summary` | jami: mashina, buzilish, reys; tizim, tur, marka va model bo'yicha taqsimot |
    | `most_broken` | eng ko'p buzilganlar: har biri faktlar (`signals`) va ta'mirlar ro'yxati bilan |
    | `least_broken` | **ko'p ishlab** kam buzilganlar |
    | `no_activity` | reys ham, buzilish ham yo'q — ishonchli emas, **ma'lumot yo'q** |
    | `cohorts` | bir xil modeldagi mashinalar: buzilganlari buzilmaganlari bilan solishtirilgan |
    | `drivers` | buzilishlarda rulda bo'lgan haydovchilar |
    | `analysis` | LLM: umumiy xulosa, eng ko'p buzilgan 5 mashinaga ehtimoliy sabab, tavsiyalar (~20 s) |

    **Chegara yo'q, solishtirish bor.** "Ko'p" — ro'yxatda yuqorida;
    "erta buzildi" (`cohorts[].broken[].early`) — bir xil modeldagi
    buzilmagan mashinalardan yangi bo'lsa ham buzilgan; "tez qayta buzildi" —
    oldingi ta'mirdan keyin necha reysda (`trips_since_previous`). Modelda
    buzilmagan faol mashina bo'lmasa, bir xil transport turi bilan
    solishtiriladi.

    **Ish hajmi — reys soni.** Bazadagi km kiritish xatolariga to'la, shuning
    uchun javobda km yo'q. Motosoat faqat motosoat bilan ishlaydigan
    mashinalarda.

    **Buzilish bo'lmasa ham tahlil bor**: LLM ishlagan va buzilmagan
    mashinalar bo'yicha xulosa va tavsiya yozadi. Davrda reys ham, buzilish
    ham bo'lmasa LLM chaqirilmaydi (`timings.llm` ~0).

    **Rad etilgan ta'mir so'rovi buzilish emas** — `counted: false`.

    **Bo'sh jadval — "tekshirilmadi", "sabab yo'q" emas.** Tezlik buzish,
    keskin haydash, avariya, texnik xizmat muddati va qism resursi
    jadvallari to'lganda o'zi hisobga olinadi; hozir qaysi biri
    tekshirilmagani `data_quality.factors_unchecked` da.

    **Hisob arifmetika bilan, tahlil LLM bilan.** LLM javob bermasa 503.
    **Bazaga ta'sir:** faqat `SELECT`, READ ONLY tranzaksiyada.
    """
    if date_from and date_to and date_from > date_to:
        raise HTTPException(400, texts.t(lang, "error.dates"))

    started = time.perf_counter()
    try:
        result = await run_in_threadpool(
            service.report,
            date_from=date_from,
            date_to=date_to,
            transport_type=vs_labels.code_of("transport_type", transport_type),
            limit=limit,
            lang=lang,
        )
    except FilterNotMatched as exc:
        raise HTTPException(400, str(exc))
    except BreakdownDataError as exc:
        raise HTTPException(503, f"Bazadan o'qib bo'lmadi: {exc}")

    llm_started = time.perf_counter()
    try:
        await analyze(result, lang=lang)
    except AnalysisUnavailable as exc:
        raise HTTPException(503, str(exc))

    # `elapsed_seconds` — BUTUN javob. Ilgari u faqat bazani o'lchardi va
    # 22 s kelgan javobda "0.83" ko'rinardi.
    result["timings"]["llm"] = round(time.perf_counter() - llm_started, 2)
    result["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    return BreakdownReport(**result)
