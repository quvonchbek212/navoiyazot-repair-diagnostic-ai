"""Javobdagi kod yozgan matnlar — uch tilda (uz, ru, en).

`breakdown_report/texts.py` bilan bir xil tuzilma: kalit -> uchta til.
"N ta o'xshash ta'mir asosida" shu yerda — uni LLM emas, kod yozadi,
shuning uchun son doim to'g'ri.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_CHATBOT_DIR = Path(__file__).resolve().parent.parent / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

from core.lang import answer_instruction  # noqa: E402

LANGS = ("uz", "ru", "en")
DEFAULT_LANG = "uz"


def normalize(lang: str | None) -> str:
    """Noma'lum yoki bo'sh til sukut tilga tushadi."""
    value = (lang or "").strip().lower()
    return value if value in LANGS else DEFAULT_LANG


def llm_instruction(lang: str) -> str:
    """LLM promptiga qo'shiladigan til ko'rsatmasi — chatbotnikidan."""
    return answer_instruction(normalize(lang))


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Kalitni tanlangan tilda qaytaradi; topilmasa kalitning o'zi qaytadi."""
    row = MESSAGES.get(key)
    if row is None:
        return key
    text = row.get(normalize(lang)) or row[DEFAULT_LANG]
    return text.format(**kwargs) if kwargs else text


MESSAGES: dict[str, dict[str, str]] = {

    # ----------------------------------------------------------- Birliklar
    "unit.hours": {"uz": "{n} soat", "ru": "{n} ч", "en": "{n} h"},
    "unit.days": {"uz": "{n} kun", "ru": "{n} дн.", "en": "{n} days"},

    # ------------------------------------------- Hozirgi bosqich (/eta)
    "stage.ARM_ACCEPTANCE": {
        "uz": "ARM qabulini kutish", "ru": "ожидание приёмки в АРМ",
        "en": "waiting for workshop intake",
    },
    "stage.DIAGNOSIS": {
        "uz": "diagnostikani kutish", "ru": "ожидание диагностики",
        "en": "waiting for diagnosis",
    },
    "stage.REPAIR": {"uz": "ta'mir", "ru": "ремонт", "en": "repair"},

    # -------------------------------------------------------------- Asos
    "basis.ESTIMATED": {
        "uz": "{n} ta o'xshash ta'mir asosida",
        "ru": "На основе {n} похожих ремонтов",
        "en": "Based on {n} similar repairs",
    },
    "basis.ESTIMATED_EXCLUDED": {
        "uz": "{n} ta o'xshash ta'mir asosida; yana {m} tasi bundan tezroq tugagani uchun olinmadi",
        "ru": "На основе {n} похожих ремонтов; ещё {m} не учтены — они закончились быстрее",
        "en": "Based on {n} similar repairs; {m} more were left out because they finished sooner",
    },
    "basis.NO_HISTORY": {
        "uz": "O'xshash yopilgan ta'mir yo'q — muddatni tarixdan aytib bo'lmaydi",
        "ru": "Похожих закрытых ремонтов нет — срок по истории назвать нельзя",
        "en": "No similar closed repairs — the history cannot give a finish time",
    },
    "basis.LONGER_THAN_HISTORY": {
        "uz": "Naryad {n} ta o'xshash ta'mirning har biridan uzoq turibdi — tarix muddat "
              "bera olmaydi",
        "ru": "Наряд уже дольше каждого из {n} похожих ремонтов — история не даёт срока",
        "en": "The work order has already lasted longer than each of {n} similar repairs — "
              "the history cannot give a finish time",
    },

    # -------------------------------------------- Tavsiya asosi (/diagnosis)
    "basis.DIAG": {
        "uz": "{n} ta o'xshash ta'mir asosida",
        "ru": "На основе {n} похожих ремонтов",
        "en": "Based on {n} similar repairs",
    },
    "basis.DIAG_PARTIAL": {
        "uz": "{n} ta o'xshash ta'mir asosida; nima qilingani {k} tasida yozilgan",
        "ru": "На основе {n} похожих ремонтов; что было сделано, записано в {k} из них",
        "en": "Based on {n} similar repairs; what was done is recorded in {k} of them",
    },
    "basis.DIAG_NO_OUTCOME": {
        "uz": "{n} ta o'xshash ta'mir topildi, lekin ularda nima qilingani yozilmagan — "
              "tavsiya umumiy bilimdan, tarixdan emas",
        "ru": "Найдено похожих ремонтов: {n}, но что было сделано, не записано — "
              "рекомендация из общих знаний, не из истории",
        "en": "{n} similar repairs found, but what was done is not recorded — "
              "the advice is general knowledge, not history",
    },
    "basis.DIAG_NONE": {
        "uz": "O'xshash ta'mir topilmadi — tavsiya umumiy bilimdan, tarixdan emas",
        "ru": "Похожих ремонтов не найдено — рекомендация из общих знаний, не из истории",
        "en": "No similar repairs found — the advice is general knowledge, not history",
    },
    "basis.NO_SYMPTOM": {
        "uz": "Naryadda alomat yozilmagan — tavsiya berib bo'lmaydi",
        "ru": "В наряде не описан симптом — рекомендацию дать нельзя",
        "en": "The work order has no symptom — no advice can be given",
    },
    # ------------------------------------------- Takror asosi (/recurrence)
    "basis.REC": {
        "uz": "{groups} ta tugunda {repairs} ta ta'mir asosida",
        "ru": "На основе {repairs} ремонтов по {groups} узлам",
        "en": "Based on {repairs} repairs in {groups} components",
    },
    "basis.REC_NONE": {
        "uz": "{n} ta ta'mir, hech bir tugunda takror yo'q",
        "ru": "Ремонтов: {n}, повторов ни по одному узлу нет",
        "en": "{n} repairs, no component repeated",
    },
    "basis.REC_NONE_COMPONENT": {
        "uz": "Tugun \"{component}\" bo'yicha takror yo'q; mashinada jami {n} ta ta'mir",
        "ru": "По узлу «{component}» повторов нет; всего ремонтов у машины: {n}",
        "en": "No repeats for \"{component}\"; the vehicle has {n} repairs in total",
    },
    "basis.REC_EMPTY": {
        "uz": "Bu mashinada ta'mir yo'q",
        "ru": "У этой машины ремонтов нет",
        "en": "This vehicle has no repairs",
    },
    "wear.km": {"uz": "probeg bo'yicha", "ru": "по пробегу", "en": "by mileage"},
    "wear.months": {"uz": "muddat bo'yicha", "ru": "по сроку", "en": "by age"},
    "error.vehicle_not_found": {
        "uz": "Mashina topilmadi: {vehicle_id}",
        "ru": "Машина не найдена: {vehicle_id}",
        "en": "Vehicle not found: {vehicle_id}",
    },

    "disclaimer": {
        "uz": "Bu taxmin. Yakuniy qarorni mexanik qiladi.",
        "ru": "Это предположение. Окончательное решение принимает механик.",
        "en": "This is a suggestion. The mechanic makes the final decision.",
    },

    # --------------------------------------------- Nega o'xshash (LLM ga)
    "match.component": {"uz": "bir xil tugun", "ru": "тот же узел", "en": "same component"},
    "match.text": {"uz": "alomat matni o'xshash", "ru": "похожее описание симптома",
                   "en": "similar symptom text"},
    "match.model": {"uz": "bir xil model", "ru": "та же модель", "en": "same model"},
    "match.vehicle": {"uz": "shu mashina", "ru": "та же машина", "en": "the same vehicle"},

    "measured.stage": {
        "uz": "hozirgi bosqich boshidan", "ru": "с начала текущего этапа",
        "en": "from the start of the current stage",
    },
    "measured.opened": {
        "uz": "naryad ochilganidan", "ru": "с открытия наряда", "en": "from the work order opening",
    },

    "plan.PASSED": {"uz": "o'tib ketgan", "ru": "уже прошёл", "en": "already passed"},
    "plan.BEFORE": {"uz": "oraliqdan oldin", "ru": "раньше интервала", "en": "before the range"},
    "plan.INSIDE": {"uz": "oraliq ichida", "ru": "внутри интервала", "en": "inside the range"},
    "plan.AFTER": {"uz": "oraliqdan keyin", "ru": "позже интервала", "en": "after the range"},

    # ------------------------------------------------------------- Xatolar
    "error.data": {
        "uz": "Bazadan o'qib bo'lmadi: {error}",
        "ru": "Не удалось прочитать базу: {error}",
        "en": "Could not read the database: {error}",
    },
    "error.analysis": {
        "uz": "Tahlil olinmadi: LLM serveri javob bermadi. Keyinroq urinib ko'ring",
        "ru": "Анализ не получен: LLM-сервер не ответил. Попробуйте позже",
        "en": "No analysis: the LLM server did not respond. Please try again later",
    },
    "error.not_found": {
        "uz": "Naryad topilmadi: {repair_id}",
        "ru": "Наряд не найден: {repair_id}",
        "en": "Work order not found: {repair_id}",
    },
    "error.closed": {
        "uz": "Naryad yopilgan — taxmin faqat ochiq naryadga beriladi{exit}",
        "ru": "Наряд закрыт — прогноз даётся только для открытого наряда{exit}",
        "en": "The work order is closed — the estimate is only for open work orders{exit}",
    },
    "error.closed_diagnosis": {
        "uz": "Naryad yopilgan — tavsiya faqat ochiq naryadga beriladi{exit}",
        "ru": "Наряд закрыт — рекомендация даётся только для открытого наряда{exit}",
        "en": "The work order is closed — advice is only for open work orders{exit}",
    },
    "error.closed_exit": {
        "uz": " (mashina {date} da ta'mirdan chiqqan)",
        "ru": " (машина вышла из ремонта {date})",
        "en": " (the vehicle left repair on {date})",
    },
}
