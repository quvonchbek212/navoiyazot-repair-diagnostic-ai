"""LLM izohlari — FAQAT ICHKI vLLM (`llm.ask_internal`).

Modul erkin matn (mexanik yozgan alomat) o'qiydi, shuning uchun so'rov faqat
ichki serverga boradi: `llm.py` da tashqi provayder yo'li yo'q.
Ism yuborilmaydi: ism ustunlari bazadan o'qilmaydi (`queries.py`).

MUDDAT IZOHIGA ALOMAT BORMAYDI — u faqat o'xshash ta'mirni tanlashda
(`similar.py`) ishlatiladi. 31.10.2026 o'lchovi `ETA_PROMPT` izohida.

SONNI KOD YOZADI. Muddat oralig'i, o'xshash ta'mirlar soni, reja oraliqqa
nisbatan qayerda — `estimate.py` da; model faqat izohlaydi. "N ta o'xshash
ta'mir asosida" jumlasi ham koddan (`texts.py`).

LLM JAVOB BERMASA YOKI BO'SH JAVOB BERSA — `AnalysisUnavailable` -> 503.
Taxmin yo'q bo'lsa (tarix yo'q) LLM chaqirilmaydi: izohlaydigan narsa yo'q.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from repair_assistant import config, llm, similar, texts
from repair_assistant.common import span

logger = logging.getLogger(__name__)


class AnalysisUnavailable(RuntimeError):
    """LLM izoh yozib bera olmadi — router buni 503 ga aylantiradi."""


RULES = """QAT'IY QOIDALAR:
- Faqat berilgan sonlar va sanalarni ishlat. Yangi son, sana yoki muddat O'YLAB
  TOPMA; umumiy bilimdan muddat ("odatda 2 kun") AYTMA.
- Oraliq va sanalarni TAKRORLAMA — ular ekranda alohida ko'rsatiladi.
- Odamlarni (haydovchi, mexanik, usta) tilga olma.
- Baho so'zlarini ("ko'p", "juda", "tez", "ancha") ishlatma.
- Kodlarni (BRAKES, REPAIR, jadval va ustun nomlari) ko'chirma. Davlat raqami,
  model va ehtiyot qism nomi — nom, ular o'zgarmaydi.
- Sarlavha, ro'yxat belgisi va qo'shtirnoq yozma."""

#: 31.10.2026 (vLLM, gemma4-31b; `eval.py eta`: 5 holat — qism kutilayotgan,
#: tezroq tugaganlar olinmagan, oddiy va sun'iy reja — har biri 3 marta). 1-band:
#:   v1 "nechta ta'mir va nimasi bilan o'xshash" — 15/15 da "N ta ta'mirga
#:      tayanadi", `basis.text` ning takrori;
#:   v2 "muddatlar farq qilsa, naryad alomati qaysilariga yaqin" — 6/15 xato
#:      xulosa (10.1-10.6 kunlik ta'mirlarni "turlicha" dedi; "7-bosqich..."
#:      degan alomatdan "uzoqlariga yaqin" dedi, naryad 0.3 soatda tugagan),
#:      4/15 ma'nosiz;
#:   v3-v5 "o'xshash ta'mirlar alomatini umumlashtir" — xom matn ko'chirildi
#:      ("old tormoz Tormoz tizimi", "7-bosqich..."), toza 6-12/15; ru da
#:      o'zbekcha matn rus jumlasi ichiga tushdi (~6/15);
#:   v6 (shu) alomat faktlardan olindi, faqat tugun va "o'xshashlik" — uz va
#:      ru da 30/30 da son to'qilmadi, xom matn ham, solishtirish ham yo'q.
#: Shartli 2-4 bandlar hamma versiyada to'g'ri: qism 12/12, tezroq tugaganlar
#: 3/3, reja 3/3 holatda aytildi va yo'q bo'lganda bir marta ham tilga olinmadi.
ETA_PROMPT = """Sen transport parkining ta'mir muddati bo'yicha izoh yozuvchisan.
Mashina ta'mirdan qachon chiqishi ALLAQACHON HISOBLANGAN — sen uni qayta
hisoblamaysan va o'zgartirmaysan.

{language_rule}

VAZIFA — TAXMIN IZOHI: 1-3 qisqa jumla (60 so'zdan oshmasin). Nechta
ta'mirga tayanganini YOZMA — u ekranda alohida ko'rsatiladi.
1. Taxmin qanday ta'mirlarga tayanadi — bitta qisqa ibora: "tugun" nomi va
   "hisobga_olingan": true bo'lgan ta'mirlarning "o'xshashlik"i. Ta'mirlarni
   muddati bo'yicha bir-biri bilan SOLISHTIRMA va naryad qaysi biriga
   yaqinligini TAXMIN QILMA.
2. "asos"dagi "olinmagan_tezroq_tugaganlar" noldan katta bo'lsa — naryad
   shuncha o'xshash ta'mirdan allaqachon uzoq turganini ayt; nol bo'lsa bu
   haqda YOZMA.
3. "berilmagan_qismlar" bo'sh bo'lmasa — shu qism kutilayotgani muddatni
   cho'zishi mumkinligini ayt; bo'sh bo'lsa ehtiyot qism haqida YOZMA.
4. "reja" bo'lsa — reja oraliqqa nisbatan qayerdaligini ayt; null bo'lsa
   rejani tilga olma.

{rules}

MA'LUMOT (JSON):
{facts}
"""

#: Faktlar shakli (`eta_facts`) ham prompt kirishi — o'zgarsa QO'LDA oshiring.
ETA_FACTS_REVISION = 2

#: Prompt versiyasi — matn va faktlar shakli xeshi: o'zgarsa versiya ham
#: o'zgaradi va jurnalda (`log.py`) qaysi javob qaysi prompt bilan yozilgani ko'rinadi.
PROMPT_VERSIONS = {
    "eta": hashlib.sha1(f"{ETA_PROMPT}{RULES}{ETA_FACTS_REVISION}".encode()).hexdigest()[:10],
}


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


def eta_facts(result: dict[str, Any], lang: str) -> dict[str, Any]:
    """Taxmin faktlari — nomlar va odam o'qiydigan vaqtlar; ism ham, alomat matni ham yo'q."""
    # Sanalar naryad vaqtlari zonasida — bazadagi boshqa sanalar bilan bir xil.
    zone = result["opened_at"].tzinfo
    now = result["now"]

    def moment(value: datetime | None) -> str | None:
        return value.astimezone(zone).strftime("%d.%m.%Y %H:%M") if value else None

    estimate = result["estimate"] or {}
    basis = result["basis"]
    plan = result["plan"]
    stage = result["current_stage"]
    return {
        "mashina": result["plate_number"],
        "model": result["model_name"],
        "tugun": result["component_name"],
        "ochiq_turibdi": span(lang, (now - result["opened_at"]).total_seconds()),
        "hozirgi_bosqich": {"bosqich": stage["name"],
                            "davom_etmoqda": span(lang, (now - stage["since"]).total_seconds())},
        "taxmin": {
            "eng_erta": moment(estimate.get("ready_from")),
            "mediana_bo'yicha": moment(estimate.get("ready_median")),
            "eng_kech": moment(estimate.get("ready_to")),
        },
        "asos": {"o'xshash_ta'mirlar": basis["similar_repairs"],
                 "hisobga_olingan": basis["used"],
                 "olinmagan_tezroq_tugaganlar": basis["excluded_shorter"]},
        "o'xshash_ta'mirlar": [
            {"mashina": r["plate_number"], "model": r["model_name"],
             "o'xshashlik": [texts.t(lang, f"match.{m}") for m in r["match"]],
             "ta'mir_muddati": span(lang, r["duration_seconds"]),
             "hisob_boshi": texts.t(lang, f"measured.{r['measured_from']}"),
             "hisobga_olingan": r["used"],
             "qism_kutish": (span(lang, r["parts_wait_seconds"])
                             if r["parts_wait_seconds"] is not None else None)}
            for r in result["similar"]
        ],
        "berilmagan_qismlar": [
            {"qism": p["item_name"],
             "so'ralganidan_beri": span(lang, (now - p["requested_at"]).total_seconds())}
            for p in result["pending_parts"]
        ],
        "reja": ({"vaqti": moment(plan["planned_exit_at"]),
                  "oraliqqa_nisbatan": texts.t(lang, f"plan.{plan['position']}")}
                 if plan and plan["position"] else None),
    }


def eta_prompt(result: dict[str, Any], lang: str) -> str:
    return ETA_PROMPT.format(language_rule=texts.llm_instruction(lang), rules=RULES,
                             facts=_json(eta_facts(result, lang)))


_SENTENCE_END = (".", "!", "?", "…")


def _complete(text: str) -> str:
    """Token chegarasida kesilgan matnni oxirgi TO'LIQ jumlagacha qisqartiradi.

    Kesilgan jumla ekranga chiqmasin. To'liq jumla umuman bo'lmasa matn
    o'zgarmaydi.
    """
    text = text.strip()
    if not text or text.endswith(_SENTENCE_END):
        return text
    cut = max(text.rfind(mark) for mark in _SENTENCE_END)
    return text[:cut + 1] if cut > 0 else text


async def explain_eta(result: dict[str, Any], *, lang: str) -> dict[str, Any] | None:
    """Taxmin izohi; taxmin yo'q bo'lsa `None` (LLM chaqirilmaydi)."""
    if result["estimate"] is None:
        return None
    try:
        raw = await llm.ask_internal(eta_prompt(result, lang), max_tokens=config.LLM_MAX_TOKENS)
    except llm.LLMUnavailable as exc:
        logger.warning("Taxmin izohi olinmadi: %s", str(exc)[:160])
        raise AnalysisUnavailable(texts.t(lang, "error.analysis")) from exc
    text = _complete(raw)
    if not text:
        logger.warning("LLM bo'sh izoh qaytardi")
        raise AnalysisUnavailable(texts.t(lang, "error.analysis"))
    return {"explanation": text, "provider": "vllm", "model": llm.internal_model_name(),
            "prompt_version": PROMPT_VERSIONS["eta"]}


# ------------------------------------------------------------ Nosozlik bo'yicha tavsiya

#: 31.10.2026 (vLLM, gemma4-31b; `eval.py diagnosis`: 7 yopilgan naryad ochilgan
#: paytida — shu mashina 3.6 kun oldin shu tugunda ta'mirlangan, alomat o'rnida
#: "7-bosqich...", tarixda aloqasiz qism, oqibatsiz tarix, tarix yo'q — har biri
#: 3 marta; 21 javob, ~110 band). Hamma versiyada: to'qilgan son 0, matnga
#: tushgan kod 0, aloqasiz qism (shinada tormoz kolodkasi) 0 marta tilga olindi.
#:   v1 — "tarix" 21 band, 6 tasi o'xshash ta'mirning ALOMATIDAN ("moy nasosini
#:        tekshiring": o'sha naryadda faqat "Moy" deb yozilgan);
#:   v2 + "alomat tarix emas" — noto'g'ri "tarix" 0, lekin "oldingi ta'mir
#:        nosozlikni bartaraf etmagan bo'lishi mumkin" 3/3 dan 0/3 ga tushdi;
#:   v3 + "qaytgan bo'lsa sabablardan biri shu" — 3/3, lekin boshqa mashina
#:        qaytgan holatni ham "oldingi ish" deb talab qilardi;
#:   v4 (shu) shu mashina va boshqa mashina ajratildi — uz: takror sababi 3/3,
#:        15 "tarix" bandining hammasi o'sha ta'mirning ishi va qaytishiga
#:        tayanadi; ru: takror 3/3, qolgani "umumiy bilim".
#: Prompt bilan tuzalmaydi: "balonlari tishildi" (teshildi) 3/3 da "tishlanish,
#: yeyilish" deb tushunildi.
DIAGNOSIS_PROMPT = """Sen transport parkining ta'mir bo'yicha maslahatchisisan. Mexanik
naryadga yozgan alomat bo'yicha ehtimoliy sabab va tekshiriladigan joylarni
aytasan. Yakuniy qarorni mexanik qiladi — sen faqat taxmin berasan.

{language_rule}

MA'LUMOT: "naryad" — hozirgi naryad. "o'xshash_ta'mirlar" — kod tanlagan
oldingi yopilgan ta'mirlar; har birida "kod" (O1, O2, ...), alomati va AMALDA
nima qilingani: "qilingan_ish", "qismlar", "keyin_shu_tugun_bilan_qaytgan",
"shu_mashinada_bu_naryaddan_oldin".

VAZIFA — JSON:
"sabablar" — 1-3 ta ehtimoliy sabab, eng ehtimoliysi birinchi;
"tekshirish" — 2-4 ta tekshiriladigan joy yoki amal, nimadan boshlash kerakligi birinchi.
Har bandda: "matn" — bitta qisqa jumla (15 so'zdan oshmasin); "manba" —
"tarix" yoki "umumiy_bilim"; "naryadlar" — tayangan o'xshash ta'mirlar kodlari.

MANBA:
- "tarix" — o'xshash ta'mirning "qilingan_ish", "qismlar" yoki qaytgani shu
  gapni to'g'ridan-to'g'ri aytsa; "naryadlar" ga o'sha ta'mir kodini yoz.
- O'xshash ta'mirning "alomat"i TARIX EMAS — u o'sha mashinada nima topilgani
  va nima qilinganini aytmaydi. Alomatdan olingan band — "umumiy_bilim".
- Qolgan hamma band — "umumiy_bilim", "naryadlar" bo'sh. O'xshash ta'mir
  bo'lmasa — hamma band "umumiy_bilim".
- O'xshash ta'mirda "shu_mashinada_bu_naryaddan_oldin" bo'lsa — shu mashina
  yaqinda shu tugun bo'yicha ta'mirlangan: sabablardan biri SHU bo'lsin —
  oldingi ish nosozlikni bartaraf etmagan bo'lishi mumkin; "manba": "tarix",
  "naryadlar" — o'sha ta'mir kodi. Hech birida bo'lmasa — bu haqda YOZMA.
- "keyin_shu_tugun_bilan_qaytgan" bo'lgan ta'mirdagi ish nosozlikni
  bartaraf etmagan bo'lishi mumkin — faqat unga tayanib sabab yozma.

QAT'IY QOIDALAR:
- Sabab — taxmin: "ehtimol", "bo'lishi mumkin" deb ayt.
- Son, foiz, muddat O'YLAB TOPMA.
- Ehtiyot qism naryad tuguniga aloqador bo'lmasa (masalan, shina ta'mirida
  tormoz kolodkasi) — uni tilga olma va unga tayanma.
- "qilingan_ish" nima qilinganini aytmasa ("yaxshi", "tuzatildi") — unga tayanma.
- Alomat nosozlikni tasvirlamasa ("test", faqat tugun nomi) — tugun bo'yicha
  umumiy tekshiruvlarni ber.
- Alomat va ish matnini so'zma-so'z ko'chirma. O1 kabi kodlarni faqat
  "naryadlar" ga yoz, "matn" ga emas.
- Odamlarni (haydovchi, mexanik, usta) tilga olma.
- Kodlarni (BRAKES, jadval va ustun nomlari) ko'chirma.
- Sarlavha, ro'yxat belgisi va qo'shtirnoq yozma.

MA'LUMOT (JSON):
{facts}
"""

#: Faktlar shakli (`diagnosis_facts`) o'zgarsa QO'LDA oshiring.
DIAGNOSIS_FACTS_REVISION = 1
PROMPT_VERSIONS["diagnosis"] = hashlib.sha1(
    f"{DIAGNOSIS_PROMPT}{DIAGNOSIS_FACTS_REVISION}".encode()).hexdigest()[:10]

#: Javobdagi bandlar soni — ekran hajmi, chegara emas.
CAUSES_MAX, CHECKS_MAX = 3, 4


def _advice_items(low: int, high: int) -> dict[str, Any]:
    return {
        "type": "array", "minItems": low, "maxItems": high,
        "items": {
            "type": "object",
            "properties": {"matn": {"type": "string"},
                           "manba": {"type": "string", "enum": ["tarix", "umumiy_bilim"]},
                           "naryadlar": {"type": "array", "items": {"type": "string"}}},
            "required": ["matn", "manba", "naryadlar"],
        },
    }


DIAGNOSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"sabablar": _advice_items(1, CAUSES_MAX),
                   "tekshirish": _advice_items(2, CHECKS_MAX)},
    "required": ["sabablar", "tekshirish"],
}


def diagnosis_facts(result: dict[str, Any], lang: str) -> dict[str, Any]:
    """Naryad va o'xshash ta'mirlar — alomat va ish matni bilan (ichki server uchun), ismsiz."""

    def days(value: float | None) -> str | None:
        return span(lang, value * 86400) if value is not None else None

    return {
        "naryad": {"mashina": result["plate_number"], "model": result["model_name"],
                   "tugun": result["component_name"], "alomat": result["symptom"],
                   "joy": result["area"]},
        "o'xshash_ta'mirlar": [
            {"kod": r["code"], "model": r["model_name"], "tugun": r["component_name"],
             "o'xshashlik": [texts.t(lang, f"match.{m}") for m in r["match"]],
             "alomat": r["symptom"], "joy": r["area"],
             "qilingan_ish": r["work"], "qismlar": r["parts"],
             "keyin_shu_tugun_bilan_qaytgan": days(r["came_back_days"]),
             "shu_mashinada_bu_naryaddan_oldin": days(r["days_before_target"])}
            for r in result["similar"]
        ],
    }


def diagnosis_prompt(result: dict[str, Any], lang: str) -> str:
    return DIAGNOSIS_PROMPT.format(language_rule=texts.llm_instruction(lang),
                                   facts=_json(diagnosis_facts(result, lang)))


def _parse(raw: str) -> dict[str, Any]:
    """Model javobidagi JSON obyekt; o'qilmasa {}."""
    from core.ollama_json import extract_json  # atil_chatbot/core/

    try:
        data = extract_json(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def advice(entries: Any, codes: dict[str, str], limit: int) -> tuple[list[dict[str, Any]], int]:
    """LLM bandlari -> javob bandlari va "tarix" dan tushirilganlar soni.

    `codes` — oqibati yozilgan o'xshash ta'mirlar (`kod -> repair_id`). "tarix"
    deb belgilangan band shulardan biriga tayanmasa — "umumiy bilim": model
    tarixda yo'q narsani tarix deb ko'rsatmasin.
    """
    out: list[dict[str, Any]] = []
    relabeled = 0
    for entry in (entries if isinstance(entries, list) else [])[:limit]:
        if not isinstance(entry, dict):
            continue
        text = _complete(str(entry.get("matn") or ""))
        if not similar.words(text):
            continue
        if not text.endswith(_SENTENCE_END):
            text += "."
        cited = [c.strip().upper() for c in entry.get("naryadlar") or [] if isinstance(c, str)]
        cited = [c for c in dict.fromkeys(cited) if c in codes]
        history = entry.get("manba") == "tarix" and bool(cited)
        relabeled += entry.get("manba") == "tarix" and not history
        out.append({"text": text, "source": "history" if history else "general_knowledge",
                    "repair_ids": [codes[c] for c in cited] if history else []})
    return out, relabeled


async def explain_diagnosis(result: dict[str, Any], *, lang: str) -> dict[str, Any] | None:
    """Sabablar va tekshiruvlar; alomat yozilmagan bo'lsa `None` (LLM chaqirilmaydi)."""
    if result["outcome"] != "ADVISED":
        return None
    try:
        raw = await llm.ask_internal(diagnosis_prompt(result, lang),
                                     max_tokens=config.DIAGNOSIS_MAX_TOKENS,
                                     json_schema=DIAGNOSIS_SCHEMA,
                                     timeout=config.DIAGNOSIS_TIMEOUT_SECONDS)
    except llm.LLMUnavailable as exc:
        logger.warning("Tavsiya olinmadi: %s", str(exc)[:160])
        raise AnalysisUnavailable(texts.t(lang, "error.analysis")) from exc
    data = _parse(raw)
    codes = {r["code"]: r["repair_id"] for r in result["similar"] if r["has_outcome"]}
    causes, relabeled_causes = advice(data.get("sabablar"), codes, CAUSES_MAX)
    checks, relabeled_checks = advice(data.get("tekshirish"), codes, CHECKS_MAX)
    if not causes or not checks:
        # Chala javob ham javob emas — bo'sh bo'lim ko'rsatishdan 503 ma'qul.
        logger.warning("LLM tavsiyasi bo'sh yoki chala: %s", raw[:200])
        raise AnalysisUnavailable(texts.t(lang, "error.analysis"))
    return {"likely_causes": causes, "check_points": checks,
            "relabeled": relabeled_causes + relabeled_checks,
            "disclaimer": texts.t(lang, "disclaimer"),
            "provider": "vllm", "model": llm.internal_model_name(),
            "prompt_version": PROMPT_VERSIONS["diagnosis"]}


# ------------------------------------------------------------- Takroriy nosozlik

#: 31.10.2026 (vLLM, gemma4-31b; `eval.py recurrence`). Haqiqiy takror bazada
#: bitta — 85312EBA tormoz: bugun va ikkinchi naryad endi ochilgan payt; uchinchi
#: holat SUN'IY (ikki mashinaning shina ta'miri bitta mashinada, shina 49%
#: eskirgan) — har biri 3 marta.
#:   v1 (bitta so'rovda hamma tugun) — shina tuguni 3/3 da e'tiborsiz qoldi;
#:      "ta'mirdan keyin 3 ko'rikdan 'soz' deb o'tib qaytgan" 9 javobning
#:      birortasida yo'q; tormozdagi metall list 2/3 da taxminga aylandi; R1
#:      ishi batafsil bo'lsa ham 2 marta "yozilmagan" deyildi;
#:   v2 (shu: har tugun alohida so'rov, ko'rik va qism eskirishi uchun shartli
#:      band, "yozilmagan" — faqat o'sha ta'mirga) — ko'rik taxmini 9/9, shina
#:      eskirishi 3/3, aloqasiz qism 0/12, "yozilmagan" faqat R2 ga 9/9; ru: ko'rik
#:      7/7, shina 2/2 (3 ta so'rov ngrok tunneli uzilib yiqildi).
#:   Hamma versiyada to'qilgan son 0, matnga tushgan kod 0. Tuzalmagan: uz da
#:   tekshiruv bandida "suyuqlik srazini" / "sızıntısını" (sizib chiqish) 8/9.
RECURRENCE_PROMPT = """Sen transport parkining ta'mir bo'yicha maslahatchisisan. Mashina
bir xil tugun bo'yicha qayta-qayta ta'mirga kelyapti. Nega qaytayotganini
uning tarixidan izlab, tekshirish uchun asoslangan taxmin berasan. Yakuniy
qarorni mexanik qiladi.

{language_rule}

MA'LUMOT: "tugun" — qaysi tugun takrorlanyapti. "ta'mirlar" — shu mashinaning
shu tugun bo'yicha ta'mirlari, eski -> yangi; har birida "kod" (R1, R2, ...),
alomati va AMALDA nima qilingani ("qilingan_ish", "qismlar"). "oraliqlar" —
ikki ta'mir orasi: necha kun, nechta reys, nechta texnik ko'rikdan "soz" deb
o'tgan. "qismlar_holati" — o'rnatilgan shina yoki akkumulyator xizmat
muddatining necha foizi ishlatilgan. "shu_modelda" — shu modeldagi boshqa
mashinalar.

VAZIFA — JSON:
"taxminlar" — 1-3 ta asoslangan taxmin: mashina nega shu tugun bilan qaytyapti;
"tekshirish" — 2-4 ta tekshiriladigan joy yoki amal, nimadan boshlash kerakligi birinchi.
Har bandda: "matn" — bitta qisqa jumla (20 so'zdan oshmasin); "manba" —
"tarix" yoki "umumiy_bilim"; "naryadlar" — tayangan ta'mirlar kodlari.

MANBA:
- "tarix" — band shu mashinaning ta'mirlari, oraliqlari yoki qismlar holatiga
  tayansa; "naryadlar" ga o'sha ta'mirlar kodini yoz.
- Qolgan hamma band — "umumiy_bilim", "naryadlar" bo'sh.

SHARTLI BANDLAR:
- Oraliqda "soz_deb_otgan_korik" noldan katta bo'lsa — taxminlardan biri SHU
  bo'lsin: mashina ta'mirdan keyin shuncha ko'rikdan "soz" deb o'tib, keyin
  qaytgan — ko'rik bu nosozlikni aniqlamagan yoki nosozlik keyin paydo
  bo'lgan bo'lishi mumkin. Nol yoki null bo'lsa — ko'rik haqida YOZMA.
- "qismlar_holati" bo'sh bo'lmasa — qismning ishlatilgan ulushini taxminda
  ayt; bo'sh bo'lsa qism eskirishi haqida YOZMA.

QAT'IY QOIDALAR:
- Taxmin — taxmin: "ehtimol", "bo'lishi mumkin" deb ayt.
- Son, foiz, muddat O'YLAB TOPMA — faqat berilganlarini ishlat.
- Ehtiyot qism tugunga aloqador bo'lmasa (masalan, tormoz ta'mirida metall
  list yoki dvutavr) — u boshqa ishga yozilgan bo'lishi mumkin: uni tilga
  olma, unga tayanma va undan xulosa chiqarma.
- Har ta'mirning "qilingan_ish"ini alohida baho: bo'sh yoki nima qilinganini
  aytmasa ("yaxshi", "tuzatildi") — FAQAT o'sha ta'mir uchun "nima qilingani
  yozilmagan" de; batafsil yozilgan ta'mir haqida bunday dema.
- Alomat va ish matnini so'zma-so'z ko'chirma. R1 kabi kodlarni faqat
  "naryadlar" ga yoz, "matn" ga emas.
- Odamlarni (haydovchi, mexanik, usta) tilga olma.
- Kodlarni (BRAKES, jadval va ustun nomlari) ko'chirma.
- Sarlavha, ro'yxat belgisi va qo'shtirnoq yozma.

MA'LUMOT (JSON):
{facts}
"""

#: Faktlar shakli (`recurrence_facts`) o'zgarsa QO'LDA oshiring.
RECURRENCE_FACTS_REVISION = 1
PROMPT_VERSIONS["recurrence"] = hashlib.sha1(
    f"{RECURRENCE_PROMPT}{RECURRENCE_FACTS_REVISION}".encode()).hexdigest()[:10]

HYPOTHESES_MAX = 3

RECURRENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"taxminlar": _advice_items(1, HYPOTHESES_MAX),
                   "tekshirish": _advice_items(2, CHECKS_MAX)},
    "required": ["taxminlar", "tekshirish"],
}


def recurrence_facts(result: dict[str, Any], group: dict[str, Any], lang: str) -> dict[str, Any]:
    """BITTA takrorlangan tugun — alomat va ish matni bilan (ichki server uchun), ismsiz.

    Har tugun alohida so'rov: 31.10.2026 da ikki tugun bitta promptda berilganda
    model 3/3 da faqat birinchisini tahlil qildi.
    """

    def day(value: datetime) -> str:
        return value.astimezone(result["now"].tzinfo).strftime("%d.%m.%Y")

    return {
        "mashina": result["plate_number"],
        "model": result["model_name"],
        "tugun": group["component_name"],
        "ta'mirlar": [
            {"kod": e["code"], "ochilgan": day(e["opened_at"]),
             "holat": "ochiq" if e["is_open"] else "yopilgan",
             "muddat": span(lang, e["duration_seconds"]),
             "alomat": e["symptom"], "joy": e["area"],
             "qilingan_ish": e["work"], "qismlar": e["parts"]}
            for e in group["episodes"]],
        "oraliqlar": [
            {"dan": i["from_code"], "gacha": i["to_code"],
             "kun": span(lang, i["days"] * 86400) if i["days"] is not None else None,
             "bir_vaqtda_ochiq": i["overlap"],
             "reyslar": i["trips"], "soz_deb_otgan_korik": i["inspections_passed"]}
            for i in group["intervals"]],
        "qismlar_holati": [
            {"qism": p["name"],
             "ishlatilgan": f"{p['used_pct']}% ({texts.t(lang, 'wear.' + p['measured_by'])})"}
            for p in group["parts"]],
        "shu_modelda": {
            "shu_tugunda_tamirlangan_boshqa_mashinalar": group["park"]["vehicles_with_component"],
            "shu_tugun_takrorlangan_boshqa_mashinalar": group["park"]["vehicles_with_repeat"]},
    }


def recurrence_prompt(result: dict[str, Any], group: dict[str, Any], lang: str) -> str:
    return RECURRENCE_PROMPT.format(language_rule=texts.llm_instruction(lang),
                                    facts=_json(recurrence_facts(result, group, lang)))


def recurrence_items(raw: str, group: dict[str, Any]) -> tuple[list, list, int]:
    """Bitta tugun javobi -> (taxminlar, tekshiruvlar, tarixdan tushirilganlar)."""
    data = _parse(raw)
    # Kodlar — shu mashinaning o'z ta'mirlari: ularga tayangan band tarix.
    codes = {e["code"]: e["repair_id"] for e in group["episodes"]}
    hypotheses, relabeled_h = advice(data.get("taxminlar"), codes, HYPOTHESES_MAX)
    checks, relabeled_c = advice(data.get("tekshirish"), codes, CHECKS_MAX)
    return hypotheses, checks, relabeled_h + relabeled_c


async def explain_recurrence(result: dict[str, Any], *, lang: str) -> dict[str, Any] | None:
    """Har takrorlangan tugunga taxmin va tekshiruv; takror yo'q bo'lsa `None`.

    Tugunlar parallel so'raladi; bittasi yiqilsa yoki chala bo'lsa — 503.
    """
    if result["outcome"] != "REPEATS":
        return None
    answers = await asyncio.gather(
        *(llm.ask_internal(recurrence_prompt(result, g, lang),
                           max_tokens=config.DIAGNOSIS_MAX_TOKENS,
                           json_schema=RECURRENCE_SCHEMA,
                           timeout=config.DIAGNOSIS_TIMEOUT_SECONDS)
          for g in result["groups"]),
        return_exceptions=True)
    groups, relabeled = [], 0
    for group, raw in zip(result["groups"], answers):
        if isinstance(raw, BaseException):
            logger.warning("Takror tahlili olinmadi: %s", str(raw)[:160])
            raise AnalysisUnavailable(texts.t(lang, "error.analysis")) from raw
        hypotheses, checks, count = recurrence_items(raw, group)
        if not hypotheses or not checks:
            logger.warning("LLM takror tahlili bo'sh yoki chala: %s", raw[:200])
            raise AnalysisUnavailable(texts.t(lang, "error.analysis"))
        groups.append({"component": group["component"], "hypotheses": hypotheses,
                       "check_points": checks})
        relabeled += count
    return {"groups": groups, "relabeled": relabeled,
            "disclaimer": texts.t(lang, "disclaimer"),
            "provider": "vllm", "model": llm.internal_model_name(),
            "prompt_version": PROMPT_VERSIONS["recurrence"]}
