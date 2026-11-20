"""Nosozlik bo'yicha tavsiya — faktlar, sof funksiya, baza va LLM'siz.

Mexanik yozgan alomatga eng o'xshash yopilgan ta'mirlar (`similar.rank`) va
ularda AMALDA NIMA QILINGANI:
  * ish bandlari (`vehicle_repair_work_items`) va `work_performed`;
  * so'ralgan ehtiyot qismlar;
  * mashina keyin SHU TUGUN bilan qaytganmi — qaytgan bo'lsa, o'sha ta'mir
    nosozlikni bartaraf etmagan bo'lishi mumkin.
Sabab va tekshiruvni LLM yozadi (`explain.py`); qaysi bandi tarixga
tayanishini kod tekshiradi — oqibati yozilgan ta'mirgagina tayanish mumkin.

SHABLON TASHLANADI. Bitta matn bir nechta naryadda so'zma-so'z takrorlansa,
u hech narsa aytmaydi ("Barcha ta'mirlash ishlari to'liq va sifatli
bajarildi...": 31.10.2026 da `work_performed` 16 tadan 7 tasida). Qoida
bazadan o'lchanadi — ro'yxat o'ylab topilmagan. So'zsiz matn ("----") ham
tashlanadi.

QISM NARYADGA MOS KELMASLIGI MUMKIN: 31.10.2026 da qism so'ralgan 9 ta
yopilgan naryaddan 6 tasida qism tugunga aloqasiz (shina ta'mirida tormoz
kolodkasi, tormozda akkumulyator). Kod buni ajrata olmaydi — LLM ga qoida
bilan beriladi (`explain.DIAGNOSIS_PROMPT`).

VAQT TARTIBI: faqat `now` gacha bo'lgan narsa — chiqqan ta'mir, qaytish,
shablon. `eval.py` dagi orqaga qarab sinash shu funksiyani naryad ochilgan
paytga qo'yib chaqiradi.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from breakdown_report import labels as br_labels
from breakdown_report.metrics import model_name
from repair_assistant import similar
from repair_assistant.common import EXCLUDED_PART_STATUSES, EXCLUDED_REPAIR_STATUSES, exit_of

_DAY = 86400.0


def _norm(text: str | None) -> str:
    """Solishtirish uchun: kichik harf, apostrof bitta, bo'shliqlar bitta."""
    return " ".join(similar.normalize(text).split())


def _texts(repair: dict[str, Any], items: list[dict[str, Any]]) -> list[str]:
    """Naryadda nima qilingani — `work_performed` va ish bandlari, takrorsiz."""
    out: dict[str, str] = {}
    for text in (repair.get("work_performed"), *(i.get("description") for i in items)):
        if text and text.strip():
            out.setdefault(_norm(text), " ".join(text.split()))
    return list(out.items())


def templates(repairs: list[dict[str, Any]], items_by: dict[str, list[dict[str, Any]]]) -> frozenset[str]:
    """Bir nechta naryadda so'zma-so'z uchraydigan matnlar (`_norm` ko'rinishida)."""
    counts: Counter[str] = Counter()
    for repair in repairs:
        counts.update({key for key, _text in _texts(repair, items_by.get(repair["id"]) or [])})
    return frozenset(key for key, n in counts.items() if n > 1)


def work_done(repair: dict[str, Any], items: list[dict[str, Any]], skip: frozenset[str]) -> list[str]:
    """Shablon va so'zsiz matnlarsiz — nima qilingani."""
    return [text for key, text in _texts(repair, items)
            if key not in skip and similar.words(text)]


DIAGNOSTIC_CHECKLISTS: dict[str, dict[str, list[str]]] = {
    "BRAKES": {
        "uz": [
            "Tormoz suyuqligi sathi va sizib chiqishini tekshirish",
            "Tormoz kolodkalari va disk/baraban qalinligini o'lchash",
            "Tormoz shlanglari va trubkalarining butunligini ko'rikdan o'tkazish",
            "ABS va gidravlik/pnevmatik bosim tizimini sinash",
        ],
        "ru": [
            "Проверка уровня и утечек тормозной жидкости",
            "Замер толщины тормозных колодок и дисков/барабанов",
            "Осмотр целостности тормозных шлангов и магистралей",
            "Тестирование датчиков ABS и гидравлического/пневматического контура",
        ],
        "en": [
            "Check brake fluid level and inspect for leaks",
            "Measure brake pad and rotor/drum thickness",
            "Inspect brake hoses and lines for wear or cracking",
            "Test ABS sensors and hydraulic/pneumatic pressure circuit",
        ],
    },
    "ENGINE": {
        "uz": [
            "Moy va sovutish suyuqligi sathi hamda sifatini tekshirish",
            "Yoqilg'i ta'minoti va bosim tizimini diagnostika qilish",
            "Shamlar, forsunka va o't oldirish tizimini tekshirish",
            "Havo filtri va drossel tozaligini ko'rikdan o'tkazish",
        ],
        "ru": [
            "Проверка уровня и состояния моторного масла и охлаждающей жидкости",
            "Диагностика топливной системы и давления подачи",
            "Проверка свечей зажигания, форсунок и системы зажигания",
            "Осмотр воздушного фильтра и чистоты дроссельной заслонки",
        ],
        "en": [
            "Check engine oil and coolant levels and condition",
            "Diagnose fuel delivery and fuel rail pressure",
            "Inspect spark plugs, fuel injectors, and ignition system",
            "Check air filter element and throttle body cleanliness",
        ],
    },
    "CHASSIS": {
        "uz": [
            "Sharovoy tayanchlar va saylentbloklar lyuftini tekshirish",
            "Amortizatorlar va prujinalar holatini ko'zdan kechirish",
            "Rul tyagalari va uchliklarining erkin harakatini tekshirish",
            "G'ildirak stupitsa podshipniklari holatini diagnostika qilish",
        ],
        "ru": [
            "Проверка люфтов шаровых опор и сайлентблоков",
            "Осмотр амортизаторов и пружин подвески на предмет течи и трещин",
            "Проверка рулевых тяг и наконечников",
            "Диагностика ступичных подшипников колес",
        ],
        "en": [
            "Inspect ball joints, control arms, and suspension bushings for play",
            "Check shock absorbers and springs for leaks and damage",
            "Inspect steering tie rods and linkage for tightness",
            "Check wheel hub bearings for noise and play",
        ],
    },
    "ELECTRICAL": {
        "uz": [
            "Akkumulyator klemmalari va kuchlanishini (V) tekshirish",
            "Generator quvvati va zaryadlash zanjirini o'lchash",
            "Saqlagichlar va relelarning butunligini tekshirish",
            "Simlar izolatsiyasi va massaga ulanishlarni ko'rikdan o'tkazish",
        ],
        "ru": [
            "Проверка клемм аккумулятора и выходного напряжения (В)",
            "Замер отдачи генератора и цепи зарядки под нагрузкой",
            "Проверка целостности предохранителей и реле",
            "Осмотр изоляции проводки и точек массы",
        ],
        "en": [
            "Check battery terminals, state of charge, and open circuit voltage",
            "Measure alternator output and charging circuit under load",
            "Verify condition of fuses and relays in power distribution boxes",
            "Inspect wiring harness insulation and chassis grounds",
        ],
    },
    "TIRES": {
        "uz": [
            "Shinalardagi havo bosimini (bar) o'lchash",
            "Protektor chuqurligi va bir tekis yeyilishini tekshirish",
            "Disklar geometriyasi va yoriqlarni ko'zdan kechirish",
            "G'ildirak gaykalari tortilish momentini tekshirish",
        ],
        "ru": [
            "Замер давления воздуха в шинах (бар)",
            "Проверка остаточной глубины протектора и равномерности износа",
            "Осмотр дисков на отсутствие трещин и деформаций",
            "Контроль момента затяжки колесных гаек",
        ],
        "en": [
            "Measure tire inflation pressure (bar/psi)",
            "Inspect tread depth and look for irregular tire wear patterns",
            "Inspect wheel rims for bends, cracks, or damage",
            "Check and torque wheel lug nuts to specification",
        ],
    },
    "BATTERY": {
        "uz": [
            "Akkumulyator kuchlanishini (V) va elektrolit zichligini o'lchash",
            "Yuklama vilkasi bilan zaryad ushlashini sinash",
            "Klemmalarni oksidlanishdan tozalash va mustahkamligini tekshirish",
            "Generator zaryadlash oqimini tekshirish",
        ],
        "ru": [
            "Замер напряжения (В) и плотности электролита аккумулятора",
            "Тестирование нагрузочной вилкой под нагрузкой",
            "Очистка клемм от окислов и проверка надежности затяжки",
            "Проверка тока заряда от генератора",
        ],
        "en": [
            "Measure battery open-circuit voltage and electrolyte density",
            "Perform carbon-pile or conductance battery load test",
            "Clean terminal oxidation and ensure secure clamping",
            "Check alternator charging rate under load",
        ],
    },
}


def diagnostic_checklist(component_category: str | None, lang: str = "uz") -> list[str]:
    """Tugun toifasi bo'yicha mexanikka tavsiya etiladigan diagnostika nazorat ro'yxati."""
    category = (component_category or "").upper()
    lang = lang if lang in ("uz", "ru", "en") else "uz"
    items = DIAGNOSTIC_CHECKLISTS.get(category, {}).get(lang)
    if items:
        return list(items)
    default_items = {
        "uz": [
            "Vizual ko'rik: agregat va birikmalarning tashqi holatini tekshirish",
            "Suyuqliklar va moy sizib chiqishini ko'zdan kechirish",
            "Biriktiruvchi elementlar va mahkamlagichlar tortilishini tekshirish",
            "Funktsional sinov: agregat ishlashidagi begona shovqin va tebranishlarni baholash",
        ],
        "ru": [
            "Визуальный осмотр внешнего состояния узлов и соединений",
            "Осмотр на предмет утечек эксплуатационных жидкостей и смазки",
            "Проверка затяжки крепежных элементов",
            "Функциональное тестирование: оценка шумов и вибраций при работе узла",
        ],
        "en": [
            "Visual inspection of assembly and connection integrity",
            "Check for fluid leaks and seepage around seals and gaskets",
            "Verify torque on mounting bolts and fasteners",
            "Functional test: evaluate abnormal noise, vibration, or harshness",
        ],
    }
    return list(default_items.get(lang, default_items["uz"]))


def came_back_days(candidate: dict[str, Any], repairs: list[dict[str, Any]], *,
                   now: datetime, exclude_id: str) -> float | None:
    """Mashina shu tugun bilan keyin qaytganmi: chiqishdan keyingi kirishgacha, kun."""
    exited, _source = exit_of(candidate)
    later = [r["opened_at"] for r in repairs
             if r["id"] not in (candidate["id"], exclude_id)
             and r.get("status") not in EXCLUDED_REPAIR_STATUSES
             and r.get("vehicle_id") == candidate.get("vehicle_id")
             and r.get("component_category") == candidate.get("component_category")
             and exited <= r["opened_at"] <= now]
    return round((min(later) - exited).total_seconds() / _DAY, 1) if later else None


def build(
    target: dict[str, Any],
    repairs: list[dict[str, Any]],
    parts: list[dict[str, Any]],
    work_items: list[dict[str, Any]],
    *,
    now: datetime,
    top: int,
    lang: str,
) -> dict[str, Any]:
    """Naryad va unga o'xshash ta'mirlar faktlari. `target` — `repairs` dagi qator."""
    items_by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in work_items:
        items_by[item["repair_id"]].append(item)
    parts_by: dict[str, list[str]] = defaultdict(list)
    for part in parts:
        if part.get("status") not in EXCLUDED_PART_STATUSES and part.get("item_name") \
                and part["item_name"] not in parts_by[part["repair_id"]]:
            parts_by[part["repair_id"]].append(part["item_name"])

    history = similar.closed_before(repairs, now=now, exclude_id=target["id"])
    # Shablon ham faqat shu paytgacha ma'lum bo'lgan naryadlardan.
    skip = templates(history, items_by)
    rows = []
    for index, match in enumerate(similar.rank(target, history, top=top), start=1):
        candidate = match["repair"]
        exited, _source = exit_of(candidate)
        same_vehicle = candidate.get("vehicle_id") == target.get("vehicle_id")
        row = {
            "code": f"O{index}",
            "repair_id": candidate["id"],
            "repair_number": candidate.get("repair_number"),
            "plate_number": candidate.get("plate_number"),
            "model_name": model_name(candidate) or None,
            "component_name": br_labels.label("component", candidate.get("component_category"), lang),
            "symptom": (candidate.get("initial_diagnosis") or "").strip() or None,
            "area": (candidate.get("defect_area") or "").strip() or None,
            "match": match["match"],
            "work": work_done(candidate, items_by.get(candidate["id"]) or [], skip),
            "parts": parts_by.get(candidate["id"]) or [],
            "came_back_days": came_back_days(candidate, repairs, now=now, exclude_id=target["id"]),
            # Shu mashina: oldingi ta'mirdan bu naryadgacha — oldingi ish yetmagan bo'lishi mumkin.
            "days_before_target": (round((target["opened_at"] - exited).total_seconds() / _DAY, 1)
                                   if same_vehicle and exited <= target["opened_at"] else None),
        }
        row["has_outcome"] = bool(row["work"] or row["parts"] or row["came_back_days"] is not None
                                  or row["days_before_target"] is not None)
        rows.append(row)

    symptom = (target.get("initial_diagnosis") or "").strip() or None
    area = (target.get("defect_area") or "").strip() or None
    return {
        "repair_id": target["id"],
        "repair_number": target.get("repair_number"),
        "vehicle_id": target.get("vehicle_id"),
        "plate_number": target.get("plate_number"),
        "model_name": model_name(target) or None,
        "component_name": br_labels.label("component", target.get("component_category"), lang),
        "symptom": symptom,
        "area": area,
        "now": now,
        "outcome": "ADVISED" if symptom or area else "NO_SYMPTOM",
        "similar": rows,
        "checklist": diagnostic_checklist(target.get("component_category"), lang),
        "basis": {"similar_repairs": len(rows),
                  "with_outcome": sum(r["has_outcome"] for r in rows)},
    }
