""""Nega buzildi" — LLM tahlili.

VAZIFA BO'LINISHI:
  * HISOB — `metrics.py`, sof arifmetika: nechta buzilish, necha reysga
    bitta, guruhdoshlaridan qanchalik farq qiladi. Bir xil so'rovga bir
    xil raqam chiqadi va har biri qo'lda tekshiriladi.
  * TAHLIL — shu fayl. Faktlarni bir-biriga bog'lash ("ko'p ishlagan,
    ikki marta tormoz, ikkalasida bitta haydovchi") va tavsiya berish.

NIMA UCHUN BITTA EMAS, PARALLEL SO'ROVLAR (14.09.2026 o'lchovi, vLLM,
gemma4-31b, ngrok orqali):

    yozish tezligi                   6.8 token/s — yagona tor joy
    bitta so'rov, butun park (JSON)  1159 token -> 168 s
    bitta so'rov, 1 mashina (JSON)    370 token ->  51 s
    10 ta 80 tokenli so'rov PARALLEL                21.5 s

Ya'ni bitta so'rovda 30 s ichiga ~180 token sig'adi — 5 mashinaga sabab
yozishga yetmaydi. vLLM esa parallel so'rovlarni birga dekodlaydi. Shuning
uchun tahlil 2 + N qisqa so'rovga bo'lingan va ular BIR VAQTDA yuboriladi:
umumiy xulosa, tavsiyalar va har mashinaga alohida sabab. Javob vaqti eng
uzun so'rovga teng. Prototipda: 1 mashina — 18 s, butun park top 5 — 20 s,
top 9 — 33 s (shuning uchun sukut 5).

Oddiy matn, JSON EMAS: sxema tokenlari (kalit, qavs, qo'shtirnoq) har
so'rovga ~15% qo'shardi va bo'lak baribir bitta maydon. ISTISNO —
tavsiyalar: matn ko'rinishida model "ko'pi bilan 3 ta, faqat amal" degan
qoidaga amal qilmadi (15.09.2026: 4 qator, birinchilari fakt va sabab,
so'rov 31 s ga cho'zildi). JSON sxema (`maxItems: 3`, `nima` + `amal`)
tuzilishni vLLM darajasida majburlaydi.

LLM ISHLAMASA JAVOB HAM YO'Q (qolgan modullardagidek): shablonga tushish
yo'q. Bitta so'rov yiqilsa ham `AnalysisUnavailable` -> 503 — yarim tahlil
"hamma mashina tahlil qilindi" degan yolg'on taassurot berardi.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

_CHATBOT_DIR = Path(__file__).resolve().parent.parent / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

from breakdown_report import config, texts  # noqa: E402
from breakdown_report.metrics import model_name as _model_name  # noqa: E402

logger = logging.getLogger(__name__)


class AnalysisUnavailable(RuntimeError):
    """LLM tahlil yozib bera olmadi — router buni 503 ga aylantiradi."""


_UNAVAILABLE = "Tahlil olinmadi: LLM serveri javob bermadi. Keyinroq urinib ko'ring"

# Qoidalar prototipda uchragan xatolardan yozilgan (14.09.2026):
#   * "akkumulyator tormoz tizimiga ta'sir qilgan" — ehtiyot qism boshqa
#     tizimga bog'landi (shuning uchun qismlar promptga umuman bormaydi);
#   * "ehtimol texnik xizmat muddati bilan bog'liq" — jadval BO'SH edi;
#   * "u 2 marta tormozni buzgan" — haydovchi aybdor deb yozildi;
#   * 15.09.2026: qoidada namuna jumla ("haydovchining ishini tekshirish
#     kerak") turardi va model uni haydovchi fakti YO'Q javobga ham ko'chirdi
#     — shuning uchun qoidalarda tayyor jumla yozilmaydi.
RULES = """QAT'IY QOIDALAR:
- Faqat berilgan raqamlardan foydalan. Yangi raqam O'YLAB TOPMA.
- Sabab — taxmin: "ehtimol", "bog'liq bo'lishi mumkin" deb ayt.
- Faktlarda yo'q sababni (yuk, yo'l sharoiti, haydash uslubi, ehtiyot qism,
  texnik xizmat muddati) YOZMA.
- "tekshirilmagan_sabablar" dagilarni sabab sifatida AYTMA.
- Haydovchini FAQAT "faktlar" ro'yxatida haydovchi takror uchragan bo'lsa
  tilga ol; aks holda haydovchi haqida umuman yozma. Aybdor deb yozma.
- Baho so'zlarini ("ko'p", "eng ko'p", "ancha", "juda") ishlatma — raqamning
  o'zini ayt.
- "faktlar" bo'sh yoki sababni ko'rsatmasa, sababni aniqlab bo'lmasligini
  ochiq ayt — o'zingdan sabab to'qima.
- Kodlarni (BRAKES, IN_TRIP, jadval nomlari) ko'chirma. Mashina raqami,
  model va haydovchi ismi — nom, ular o'zgarmaydi.
- Sarlavha, ro'yxat belgisi va qo'shtirnoq yozma."""

_HEAD = """Sen transport parkining texnik tahlilchisisan. Quyidagi raqamlar
ALLAQACHON HISOBLANGAN — sen ularni qayta hisoblamaysan.

{language_rule}
"""

OVERVIEW_PROMPT = _HEAD + """
VAZIFA — UMUMIY XULOSA: 2-3 qisqa jumla. Jami nechta buzilish; buzilishi
eng katta 2 ta tizim va 2 ta tur yoki model (soni bilan, qolganlarini
sanama); park bo'yicha necha reysga bitta buzilish.

{rules}

MA'LUMOT (JSON):
{facts}
"""

RECOMMENDATIONS_PROMPT = _HEAD + """
VAZIFA — TAVSIYALAR: 2-3 ta amaliy tavsiya, JSON ko'rinishida. Har birida:
"nima" — qaysi mashina (raqami), tizim yoki haydovchi (ismi);
"amal" — nima qilish kerak: bitta qisqa buyruq jumlasi, sababsiz va raqamsiz.
Fakt yoki sababni tavsiya sifatida yozma.

{rules}

MA'LUMOT (JSON):
{facts}
"""

VEHICLE_PROMPT = _HEAD + """
VAZIFA — MASHINA SABABI: shu mashina nega buzilgan bo'lishi MUMKINLIGINI
1-2 qisqa jumlada yoz (35 so'zdan oshmasin). Faqat shu mashinaning "faktlar"
va "buzilishlar" ro'yxatiga tayan; bir nechta fakt bir-biriga bog'lansa
shuni ayt.

{rules}

MA'LUMOT (JSON):
{facts}
"""


# Buzilishsiz davr (15.09.2026): ilgari bu holatda LLM umuman chaqirilmasdi
# va 54 ta tur/davr kombinatsiyasining 40 tasida `analysis` bo'sh edi —
# jumladan 146 reys qilgan avtobuslarda. Loyiha maqsadining yarmi "kam
# buzilayotganlar", ya'ni aynan shu holatda ham xulosa kerak.
RELIABILITY_OVERVIEW_PROMPT = _HEAD + """
VAZIFA — UMUMIY XULOSA (BUZILISHSIZ DAVR): tanlangan davrda buzilish qayd
etilmagan. 2-3 qisqa jumla: nechta mashina, nechtasi reys qilgan va jami
reys soni; eng ko'p reys qilgan 2 ta mashina (raqami va reysi bilan);
nechtasi davrda umuman ishlamagan. Buzilish yo'qligini mashinaning texnik
holati haqida xulosa qilib aytma — faqat shu davrda qayd etilmaganini ayt.

{rules}

MA'LUMOT (JSON):
{facts}
"""

RELIABILITY_RECOMMENDATIONS_PROMPT = _HEAD + """
VAZIFA — TAVSIYALAR (BUZILISHSIZ DAVR): 1-2 ta amaliy tavsiya, JSON
ko'rinishida. Har birida: "nima" — qaysi mashina (raqami) yoki guruh;
"amal" — nima qilish kerak: bitta qisqa buyruq jumlasi, sababsiz va raqamsiz.
Faqat ma'lumotda bor narsaga tayan.

{rules}

MA'LUMOT (JSON):
{facts}
"""


def _reliability_facts(
    report: dict[str, Any], top: int, unchecked: list[str], lang: str
) -> dict[str, Any]:
    """Buzilishsiz davr: park ko'rsatkichlari + eng ko'p ishlagan buzilmaganlar."""
    facts = _park_facts(report, lang)
    facts["tekshirilmagan_sabablar"] = unchecked
    facts["eng_kop_reys_qilgan_buzilmaganlar"] = [
        {"mashina": s["vehicle"].get("plate_number"), "model": _model_name(s["vehicle"]),
         "turi": s["vehicle"].get("transport_type_name"),
         "chiqarilgan_yili": s["vehicle"].get("release_year"), "reyslar": s["trips"]}
        for s in (report.get("least_broken") or [])[:top]
    ]
    facts["davrda_ishlamaganlar"] = (report.get("summary") or {}).get("vehicles_no_activity")
    return facts


def _json(data: Any) -> str:
    # Ixcham: prompt o'qish ham vaqt (butun park 8346 -> 6305 token).
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


def _unchecked(report: dict[str, Any], lang: str) -> list[str]:
    # So'ralgan tilda: `lang=ru` da LLM ga o'zbekcha nom borsa u ruscha
    # javobga o'zbek so'zini aralashtirishi mumkin.
    return [
        texts.t(lang, f"factor.{table}")
        for table in (report.get("data_quality") or {}).get("factors_unchecked") or []
    ]


def _park_facts(report: dict[str, Any], lang: str) -> dict[str, Any]:
    summary = report.get("summary") or {}
    period = report.get("period") or {}
    return {
        "davr": {
            "boshi": str(period.get("date_from") or "bazaning boshidan"),
            "oxiri": str(period.get("date_to") or "bugungacha"),
        },
        "park": {
            "mashinalar": summary.get("vehicles_total"),
            "reys_qilganlar": summary.get("vehicles_active"),
            "buzilgan_mashinalar": summary.get("vehicles_broken"),
            "buzilishlar": summary.get("breakdowns_total"),
            "ochiq_tamirlar": summary.get("breakdowns_open"),
            "reyslar": summary.get("trips_total"),
            "necha_reysga_bitta_buzilish": summary.get("trips_per_breakdown"),
            "tizimlar": {c["name"]: c["count"] for c in summary.get("by_component") or []},
            "aniqlangan_payt": {c["name"]: c["count"] for c in summary.get("by_context") or []},
            "turlar": [
                {"tur": g["name"], "mashinalar": g["vehicles"], "buzilgan": g["vehicles_broken"],
                 "buzilishlar": g["breakdowns"]}
                for g in summary.get("by_transport_type") or [] if g["breakdowns"]
            ],
            "modellar": [
                {"model": g["name"], "mashinalar": g["vehicles"], "buzilgan": g["vehicles_broken"],
                 "buzilishlar": g["breakdowns"]}
                for g in summary.get("by_model") or [] if g["breakdowns"]
            ],
        },
        "tekshirilmagan_sabablar": _unchecked(report, lang),
    }


#: Faqat TAKROR buzilishda (2+) LLM ga boradigan faktlar. Javobda (`signals`)
#: ular doim qoladi. 15.09.2026: bitta buzilishli mashinada "3 xil haydovchi,
#: guruhdoshlarida 2" faktidan LLM "haydovchilarning ishini tekshirish kerak"
#: degan sabab VA tavsiya yasadi. Bitta hodisa haydovchilar sonini sababga
#: aylantira olmaydi — `DRIVER_HIGH_RATE` dagi qoida bilan bir xil.
REPEAT_ONLY_SIGNALS = frozenset({"MORE_DRIVERS_THAN_PEERS"})


def _llm_signals(stat: dict[str, Any]) -> list[str]:
    repeated = stat["breakdowns"] > 1
    return [signal["text"] for signal in stat.get("signals") or []
            if repeated or signal["code"] not in REPEAT_ONLY_SIGNALS]


def _vehicle_facts(stat: dict[str, Any], unchecked: list[str]) -> dict[str, Any]:
    """Bitta mashina — faqat uning sababi uchun kerakli maydonlar.

    YUBORILMAYDI: km (ishonchsiz), `trips_before` (kuzatuv boshida doim 0 —
    metrics.py), ehtiyot qismlar (LLM ularni boshqa tizimga bog'lagan),
    bitta buzilishda haydovchilar soni (`REPEAT_ONLY_SIGNALS`), bajarilgan
    ish (`work_performed` — 15.09.2026 da LLM "kolodka va disklar holati"
    degan ta'mir ishini sabab qilib qaytardi; javobda maydon qoladi).
    """
    vehicle = stat["vehicle"]
    facts = {
        "mashina": vehicle.get("plate_number"),
        "model": _model_name(vehicle),
        "turi": vehicle.get("transport_type_name"),
        "chiqarilgan_yili": vehicle.get("release_year"),
        "buzilishlar_soni": stat["breakdowns"],
        "reyslar": stat["trips"],
        "necha_reysga_bitta": stat["trips_per_breakdown"],
        "buzilishlar": [
            {
                "sana": str(i["occurred_at"])[:10] if i.get("occurred_at") else None,
                "tizim": i.get("component_name"),
                "qayerda_aniqlandi": i.get("context_name"),
                "nosozlik": i.get("defect_area"),
                "sabab_yozuvi": i.get("defect_reason"),
                "haydovchi": i.get("driver_name"),
                "oldingi_tamirdan_keyin_reys": i.get("trips_since_previous"),
                "ochiq": i.get("is_open"),
            }
            for i in stat.get("repairs") or [] if i.get("counted")
        ],
        "faktlar": _llm_signals(stat),
        "tekshirilmagan_sabablar": unchecked,
    }
    if stat["breakdowns"] > 1:
        facts["haydovchilar_soni"] = stat["drivers"]
    return facts


def _recommendation_facts(
    report: dict[str, Any], vehicles: list[dict[str, Any]], unchecked: list[str]
) -> dict[str, Any]:
    summary = report.get("summary") or {}
    return {
        "tizimlar": {c["name"]: c["count"] for c in summary.get("by_component") or []},
        "mashinalar": [
            {"mashina": s["vehicle"].get("plate_number"), "model": _model_name(s["vehicle"]),
             "buzilishlar": s["breakdowns"],
             "faktlar": _llm_signals(s)}
            for s in vehicles
        ],
        "tekshirilmagan_sabablar": unchecked,
    }


#: Tavsiyalar javobi sxemasi — vLLM `response_format.json_schema` ga boradi.
RECOMMENDATIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tavsiyalar": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {"nima": {"type": "string"}, "amal": {"type": "string"}},
                "required": ["nima", "amal"],
            },
        },
    },
    "required": ["tavsiyalar"],
}

_SENTENCE_END = (".", "!", "?", "…")


def _complete(text: str) -> str:
    """Token chegarasida kesilgan matnni oxirgi TO'LIQ jumlagacha qisqartiradi.

    15.09.2026: tavsiya "Usmonov Farxod Ashrabovichning hay" bo'lib ekranga
    chiqdi. `ask_llm` faqat matn qaytaradi (`finish_reason` yo'q), shuning
    uchun kesilganlik matnning o'zidan aniqlanadi. To'liq jumla umuman
    bo'lmasa matn o'zgarmaydi — bo'sh qoldirishdan ko'ra ma'qul.
    """
    text = text.strip()
    if not text or text.endswith(_SENTENCE_END):
        return text
    cut = max(text.rfind(mark) for mark in _SENTENCE_END)
    return text[:cut + 1] if cut > 0 else text


def _recommendations(raw: str) -> list[str]:
    """Tavsiyalar JSON'ini "nima: amal" qatorlariga aylantiradi.

    JSON o'qilmasa bo'sh ro'yxat — chaqiruvchi uni 503 ga aylantiradi.
    `maxItems` ni server majburlaydi, lekin sxemani bilmaydigan backend
    (Ollama) uchun bu yerda ham 3 ta bilan cheklanadi.
    """
    from core.ollama_json import extract_json  # atil_chatbot/core/

    try:
        data = extract_json(raw)
    except ValueError:
        return []
    items = data.get("tavsiyalar") if isinstance(data, dict) else None
    out: list[str] = []
    for item in (items or [])[:3]:
        if not isinstance(item, dict):
            continue
        target = str(item.get("nima") or "").strip()
        action = _complete(str(item.get("amal") or ""))
        if not action:
            continue
        if not action.endswith(_SENTENCE_END):
            # JSON qiymati to'liq (kesilgan bo'lsa JSON o'qilmasdi) — model
            # shunchaki nuqta qo'ymagan; boshqa matnlar bilan bir xil ko'rinsin.
            action += "."
        # Model amalning boshiga nishonni o'zi qo'ygan bo'lsa takrorlanmasin.
        out.append(action if not target or action.casefold().startswith(target.casefold())
                   else f"{target}: {action}")
    return out


async def analyze(
    report: dict[str, Any],
    *,
    limit: int | None = None,
    lang: str = texts.DEFAULT_LANG,
) -> None:
    """Hisobotga `analysis` qo'shadi (joyida) — parallel LLM so'rovlari.

    Uch holat:
      * buzilish bor         -> xulosa + tavsiyalar + top N mashinaga sabab;
      * buzilish yo'q, lekin ishlagan mashina bor -> buzilishsiz davr
                                xulosasi + tavsiyalar (2 so'rov);
      * reys ham, buzilish ham yo'q -> tahlil qiladigan narsa yo'q: LLM
                                chaqirilmaydi, xato ham ko'tarilmaydi,
                                `analysis` bo'sh qoladi.
    """
    has_breakdowns = bool((report.get("summary") or {}).get("breakdowns_total"))
    if not has_breakdowns and not report.get("least_broken"):
        return

    top = limit if limit is not None else config.LLM_ANALYZE_TOP
    vehicles = (report.get("most_broken") or [])[:top] if has_breakdowns else []
    unchecked = _unchecked(report, lang)

    # Kech import: LLM serveri o'chiq bo'lsa ham modul yuklansin.
    from config import DEFAULT_NUM_CTX  # atil_chatbot/config.py
    from ollama_client import ask_llm

    llm_config: dict[str, Any] = {
        "options": {
            "temperature": 0.2,
            "num_predict": config.LLM_MAX_TOKENS,
            # Chatbotniki bilan bir xil — Ollama boshqa `num_ctx` da modelni
            # qayta yuklaydi (batafsil: vehicle_selection/explain.py).
            "num_ctx": DEFAULT_NUM_CTX,
        },
        "think": False,
    }
    if config.LLM_TIMEOUT_SECONDS:
        llm_config["timeout"] = config.LLM_TIMEOUT_SECONDS

    def prompt(template: str, facts: dict[str, Any]) -> str:
        return template.format(
            language_rule=texts.llm_instruction(lang), rules=RULES, facts=_json(facts))

    if has_breakdowns:
        overview_prompt = prompt(OVERVIEW_PROMPT, _park_facts(report, lang))
        recommendations_prompt = prompt(
            RECOMMENDATIONS_PROMPT, _recommendation_facts(report, vehicles, unchecked))
    else:
        facts = _reliability_facts(report, top, unchecked, lang)
        overview_prompt = prompt(RELIABILITY_OVERVIEW_PROMPT, facts)
        recommendations_prompt = prompt(RELIABILITY_RECOMMENDATIONS_PROMPT, facts)

    results = await asyncio.gather(
        ask_llm(overview_prompt, llm_config),
        ask_llm(recommendations_prompt,
                {**llm_config, "response_json_schema": RECOMMENDATIONS_SCHEMA}),
        *(ask_llm(prompt(VEHICLE_PROMPT, _vehicle_facts(s, unchecked)), llm_config)
          for s in vehicles),
        # Bittasi yiqilsa qolganlari tashlab ketilmasin — hammasi tugagach
        # bitta qaror qabul qilinadi.
        return_exceptions=True,
    )

    failed = [r for r in results if isinstance(r, BaseException)]
    if failed:
        logger.warning("LLM tahlili olinmadi (%d/%d so'rov): %s",
                       len(failed), len(results), str(failed[0])[:160])
        raise AnalysisUnavailable(_UNAVAILABLE) from failed[0]

    overview, recommendations, *causes = [(r or "").strip() for r in results]
    overview = _complete(overview)
    causes = [_complete(cause) for cause in causes]
    recommendation_lines = _recommendations(recommendations)
    if not overview or not recommendation_lines or not all(causes):
        # Bo'sh javob ham javob emas — bo'sh maydon ko'rsatishdan 503 ma'qul.
        logger.warning("LLM bo'sh javob qaytardi")
        raise AnalysisUnavailable(_UNAVAILABLE)

    report["analysis"] = {
        "overview": overview,
        "vehicles": [
            {"plate_number": s["vehicle"].get("plate_number") or s["vehicle"]["id"],
             "likely_causes": cause}
            for s, cause in zip(vehicles, causes)
        ],
        "recommendations": recommendation_lines,
        "vehicles_considered": len(vehicles),
    }
