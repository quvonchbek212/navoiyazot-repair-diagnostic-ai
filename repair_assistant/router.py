"""Ta'mir yordamchisi endpointlari.

Router `main.py` dagi yagona FastAPI ilovasiga ulanadi; autorizatsiya ilova
darajasida (`security.py`), shuning uchun bu yerda qayta yozilmaydi.
"""

from __future__ import annotations

import time
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder

from repair_assistant import explain, log, service, texts
from repair_assistant.explain import AnalysisUnavailable
from repair_assistant.models import RepairDiagnosis, RepairEta, VehicleRecurrence
from repair_assistant.queries import RepairDataError

router = APIRouter(prefix="/repair-assistant", tags=["Ta'mir yordamchisi"])

_ERRORS = {
    404: {"description": "Bunday naryad yo'q"},
    503: {"description": "LLM javob bermadi yoki bazaga ulanib bo'lmadi"},
}


def _basis_text(result: dict[str, Any], lang: str) -> str:
    basis = result["basis"]
    if result["outcome"] == "NO_HISTORY":
        return texts.t(lang, "basis.NO_HISTORY")
    if result["outcome"] == "LONGER_THAN_HISTORY":
        return texts.t(lang, "basis.LONGER_THAN_HISTORY", n=basis["similar_repairs"])
    if basis["excluded_shorter"]:
        return texts.t(lang, "basis.ESTIMATED_EXCLUDED", n=basis["used"],
                       m=basis["excluded_shorter"])
    return texts.t(lang, "basis.ESTIMATED", n=basis["used"])


async def _load(fetch: Any, repair_id: UUID, lang: str, *, closed_key: str) -> dict[str, Any]:
    """Bazadan o'qish va hisob (fon oqimida); xatolar — 503 / 404 / 409."""
    try:
        return await run_in_threadpool(fetch, repair_id=str(repair_id), lang=lang)
    except RepairDataError as exc:
        raise HTTPException(503, texts.t(lang, "error.data", error=exc))
    except service.RepairNotFound:
        raise HTTPException(404, texts.t(lang, "error.not_found", repair_id=repair_id))
    except service.RepairClosed as exc:
        exit_text = (texts.t(lang, "error.closed_exit", date=exc.exited_at.strftime("%d.%m.%Y"))
                     if exc.exited_at else "")
        raise HTTPException(409, texts.t(lang, closed_key, exit=exit_text))


async def _explain(write: Any, result: dict[str, Any], lang: str) -> dict[str, Any] | None:
    try:
        return await write(result, lang=lang)
    except AnalysisUnavailable as exc:
        raise HTTPException(503, str(exc))


def _log(background: BackgroundTasks, endpoint: str, result: dict[str, Any],
         analysis: dict[str, Any] | None, lang: str, response: Any) -> None:
    background.add_task(
        log.write, endpoint=endpoint, repair_id=result["repair_id"],
        vehicle_id=result["vehicle_id"], lang=lang,
        prompt_version=(analysis or {}).get("prompt_version"),
        model=(analysis or {}).get("model"), response=jsonable_encoder(response))


@router.get(
    "/eta",
    response_model=RepairEta,
    summary="Ta'mir qachon tugaydi — o'xshash ta'mirlardan oraliq va LLM izohi",
    responses={**_ERRORS, 409: {"description": "Naryad yopilgan — taxmin faqat ochiq naryadga"}},
)
async def eta(
    background: BackgroundTasks,
    repair_id: UUID = Query(..., description="`vehicle_repair.id` — OCHIQ naryad"),
    lang: Literal["uz", "ru", "en"] = Query("uz", description="**Javob tili** — LLM izohi va matnlar"),
) -> RepairEta:
    """**Mashina ta'mirdan taxminan qachon chiqadi.** Oraliqni KOD hisoblaydi,
    LLM faqat izohlaydi.

    | Qadam | Qanday |
    |---|---|
    | o'xshash ta'mirlar | bir xil tugun (`OTHER` da — alomat matni ham), tartib: alomat matni -> model -> shu mashina -> yangirog'i; eng mosi `RA_SIMILAR_TOP` (5) ta |
    | hozirgi holat | oxirgi yozilgan belgi: ochildi / ARM qabul qildi / diagnostika qilindi. O'xshash ta'mirlarda shu belgidan chiqishgacha o'lchanadi (`measured_from`) |
    | oraliq | naryad allaqachon uzoq turgan ta'mirlar olinmaydi (`used: false`); qolganlaridan eng qisqa, mediana, eng uzun qolgan vaqt |

    Tarix bo'lmasa yoki naryad har bir o'xshash ta'mirdan uzoq turgan bo'lsa —
    `estimate: null`, `analysis: null`, LLM chaqirilmaydi: tarixsiz muddatni
    faqat o'ylab topish mumkin. `basis.text` — "N ta o'xshash ta'mir asosida",
    kod yozadi.

    Ehtiyot qism omborda bor-yo'qligi hisobga OLINMAYDI — qism so'rovi ombor
    bilan bog'lanmagan. Berilmagan qism faqat izohda aytiladi.

    **Faqat ichki vLLM:** modul mexanik yozgan alomatni o'qiydi (o'xshash
    ta'mirni shu bilan tanlaydi), so'rov tashqi servisga ketmaydi.
    LLM javob bermasa — 503.
    **Bazaga ta'sir:** faqat `SELECT`, READ ONLY.
    """
    started = time.perf_counter()
    result = await _load(service.eta, repair_id, lang, closed_key="error.closed")
    llm_started = time.perf_counter()
    analysis = await _explain(explain.explain_eta, result, lang)

    timings = {**result["timings"], "llm": round(time.perf_counter() - llm_started, 2)}
    response = RepairEta(
        repair_id=result["repair_id"],
        repair_number=result["repair_number"],
        plate_number=result["plate_number"],
        outcome=result["outcome"],
        opened_at=result["opened_at"],
        current_stage=result["current_stage"],
        estimate=result["estimate"],
        basis={**result["basis"], "text": _basis_text(result, lang)},
        similar_repairs=[
            {**r, "duration_hours": round(r["duration_seconds"] / 3600, 1)}
            for r in result["similar"]
        ],
        plan=result["plan"],
        analysis=analysis,
        generated_at=result["generated_at"],
        elapsed_seconds=round(time.perf_counter() - started, 2),
        timings=timings,
    )
    _log(background, "eta", result, analysis, lang, response)
    return response


def _diagnosis_basis_text(result: dict[str, Any], lang: str) -> str:
    basis = result["basis"]
    n, k = basis["similar_repairs"], basis["with_outcome"]
    if result["outcome"] == "NO_SYMPTOM":
        return texts.t(lang, "basis.NO_SYMPTOM")
    if not n:
        return texts.t(lang, "basis.DIAG_NONE")
    if not k:
        return texts.t(lang, "basis.DIAG_NO_OUTCOME", n=n)
    if k < n:
        return texts.t(lang, "basis.DIAG_PARTIAL", n=n, k=k)
    return texts.t(lang, "basis.DIAG", n=n)


@router.get(
    "/diagnosis",
    response_model=RepairDiagnosis,
    summary="Nosozlik bo'yicha tavsiya — ehtimoliy sabab va tekshiriladigan joylar",
    responses={**_ERRORS, 409: {"description": "Naryad yopilgan — tavsiya faqat ochiq naryadga"}},
)
async def diagnosis(
    background: BackgroundTasks,
    repair_id: UUID = Query(..., description="`vehicle_repair.id` — OCHIQ naryad"),
    lang: Literal["uz", "ru", "en"] = Query("uz", description="**Javob tili** — tavsiya va matnlar"),
) -> RepairDiagnosis:
    """**Mexanik yozgan alomat bo'yicha ehtimoliy sabab va tekshiriladigan
    joylar.** Yakuniy qarorni mexanik qiladi (`analysis.disclaimer`).

    | Qadam | Qanday |
    |---|---|
    | alomat | naryaddagi `initial_diagnosis` va `defect_area`; ikkalasi bo'sh bo'lsa — `NO_SYMPTOM`, LLM chaqirilmaydi |
    | o'xshash ta'mirlar | `/eta` dagi bilan bir xil tanlov, eng mosi `RA_SIMILAR_TOP` (5) ta |
    | ularda nima qilingan | ish bandlari va `work_performed` (bir nechta naryadda so'zma-so'z takrorlangan shablon tashlanadi), so'ralgan qism, mashina keyin shu tugun bilan qaytganmi |
    | manba | har bandda `history` yoki `general_knowledge`. LLM `history` desa ham, band nima qilingani yozilgan o'xshash ta'mirga tayanmasa, kod uni `general_knowledge` ga tushiradi (`relabeled`) |

    `basis.text` — "N ta o'xshash ta'mir asosida" yoki "tavsiya umumiy
    bilimdan, tarixdan emas" — kod yozadi.

    **Faqat ichki vLLM:** promptga mexanik yozgan alomat va ish matni boradi.
    LLM javob bermasa yoki chala javob bersa — 503. Javob 33-40 s
    (31.10.2026, vLLM).
    **Bazaga ta'sir:** faqat `SELECT`, READ ONLY.
    """
    started = time.perf_counter()
    result = await _load(service.diagnosis_facts, repair_id, lang,
                         closed_key="error.closed_diagnosis")
    llm_started = time.perf_counter()
    analysis = await _explain(explain.explain_diagnosis, result, lang)

    response = RepairDiagnosis(
        repair_id=result["repair_id"],
        repair_number=result["repair_number"],
        plate_number=result["plate_number"],
        outcome=result["outcome"],
        basis={**result["basis"], "text": _diagnosis_basis_text(result, lang)},
        similar_repairs=result["similar"],
        checklist=result.get("checklist", []),
        analysis=analysis,
        generated_at=result["generated_at"],
        elapsed_seconds=round(time.perf_counter() - started, 2),
        timings={**result["timings"], "llm": round(time.perf_counter() - llm_started, 2)},
    )
    _log(background, "diagnosis", result, analysis, lang, response)
    return response


Component = Literal["ENGINE", "BRAKES", "TIRES", "BATTERY", "ELECTRICAL", "CHASSIS", "OTHER"]


def _recurrence_basis_text(result: dict[str, Any], lang: str) -> str:
    basis = result["basis"]
    if result["outcome"] == "REPEATS":
        return texts.t(lang, "basis.REC", groups=basis["groups"], repairs=basis["repairs"])
    if not result["repairs_total"]:
        return texts.t(lang, "basis.REC_EMPTY")
    if result["component_name"]:
        return texts.t(lang, "basis.REC_NONE_COMPONENT", component=result["component_name"],
                       n=result["repairs_total"])
    return texts.t(lang, "basis.REC_NONE", n=result["repairs_total"])


def _repeat(group: dict[str, Any]) -> dict[str, Any]:
    return {
        "component": group["component"],
        "component_name": group["component_name"],
        "repairs": group["episodes"],
        "intervals": group["intervals"],
        "parts": group["parts"],
        "same_model_vehicles_with_component": group["park"]["vehicles_with_component"],
        "same_model_vehicles_with_repeat": group["park"]["vehicles_with_repeat"],
    }


@router.get(
    "/recurrence",
    response_model=VehicleRecurrence,
    summary="Takroriy nosozlik — mashina nega bir xil tugun bilan qaytyapti",
    responses={**_ERRORS, 404: {"description": "Bunday mashina yo'q"}},
)
async def recurrence(
    background: BackgroundTasks,
    vehicle_id: UUID = Query(..., description="`transport_vehicle.id`"),
    component: Component | None = Query(
        None, description="Faqat shu tugun; berilmasa — mashinaning hamma takrorlangan tugunlari"),
    lang: Literal["uz", "ru", "en"] = Query("uz", description="**Javob tili** — tahlil va matnlar"),
) -> VehicleRecurrence:
    """**Mashina nega bir xil tugun bilan qayta-qayta ta'mirga kelyapti** —
    tarixdan asoslangan taxmin va tekshiriladigan joylar. Yakuniy qarorni
    mexanik qiladi (`analysis.disclaimer`).

    | Qadam | Qanday |
    |---|---|
    | takror | bir xil tugunda 2 va undan ko'p ta'mir (rad etilgan va bekor qilinganisiz); `OTHER` da alomat matnida umumiy so'z ham shart. Vaqt chegarasi yo'q — oraliq kunlarda beriladi |
    | har ta'mir | alomat, nima qilingani (shablonsiz), so'ralgan qism, muddat |
    | oraliq | necha kun, nechta reys (`waybill`), nechta texnik ko'rikdan "soz" deb o'tgan |
    | qism holati | `TIRES` — o'rnatilgan shinalar probeg bo'yicha, `BATTERY` — akkumulyator yoshi bo'yicha (`vehicle_part`) |
    | park | shu modeldagi boshqa mashinalarda shu tugun takrorlanganmi |

    Har takrorlangan tugun LLM ga alohida (parallel) so'rov. Takror bo'lmasa —
    `NO_REPEATS`, `analysis: null`, LLM chaqirilmaydi.

    **Faqat ichki vLLM:** promptga alomat va ish matni boradi. LLM javob
    bermasa yoki chala javob bersa — 503. Javob 30-36 s (31.10.2026, vLLM).
    **Bazaga ta'sir:** faqat `SELECT`, READ ONLY.
    """
    started = time.perf_counter()
    try:
        result = await run_in_threadpool(service.recurrence_facts, vehicle_id=str(vehicle_id),
                                         lang=lang, component=component)
    except RepairDataError as exc:
        raise HTTPException(503, texts.t(lang, "error.data", error=exc))
    except service.VehicleNotFound:
        raise HTTPException(404, texts.t(lang, "error.vehicle_not_found", vehicle_id=vehicle_id))
    llm_started = time.perf_counter()
    analysis = await _explain(explain.explain_recurrence, result, lang)

    response = VehicleRecurrence(
        vehicle_id=result["vehicle_id"],
        plate_number=result["plate_number"],
        outcome=result["outcome"],
        repairs_total=result["repairs_total"],
        repeats=[_repeat(g) for g in result["groups"]],
        basis={**result["basis"], "text": _recurrence_basis_text(result, lang)},
        analysis=analysis,
        generated_at=result["generated_at"],
        elapsed_seconds=round(time.perf_counter() - started, 2),
        timings={**result["timings"], "llm": round(time.perf_counter() - llm_started, 2)},
    )
    _log(background, "recurrence", result, analysis, lang, response)
    return response
