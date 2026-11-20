"""Javobdagi hamma matn — uch tilda (uz, ru, en).

`vehicle_selection/texts.py` bilan bir xil tuzilma: kalit -> uchta til.
Kodlar (`signals[].code`, jadval nomlari) tarjima qilinmaydi — ularni
dastur o'qiydi. Raqam va sana chaqiruvchi tomonda tayyorlanadi.
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

    # ------------------------------------------------------------ Faktlar
    # Har biri O'LCHANGAN solishtirish. Sabab haqida xulosa yo'q — uni LLM
    # faktlarni bog'lab yozadi.
    "signal.NO_TRIPS_RECORDED": {
        "uz": "Davrda yakunlangan reys yozuvi yo'q — ish hajmi noma'lum",
        "ru": "За период нет завершённых рейсов — объём работы неизвестен",
        "en": "No completed trips recorded in the period — workload unknown",
    },
    "signal.OLDER_THAN_PEERS": {
        "uz": "Chiqarilgan yili {year}; {group} guruhidagi buzilmaganlar — {peer_year} "
              "(mediana), ya'ni {years} yil eski",
        "ru": "Год выпуска {year}; у исправных машин группы «{group}» — {peer_year} "
              "(медиана), то есть старше на {years} г.",
        "en": "Built in {year}; vehicles in the {group} group that did not break — "
              "{peer_year} (median), i.e. {years} year(s) older",
    },
    "signal.NEWER_THAN_PEERS": {
        "uz": "Chiqarilgan yili {year}; {group} guruhidagi buzilmaganlar — {peer_year} "
              "(mediana), ya'ni {years} yil yangi bo'lsa ham buzilgan",
        "ru": "Год выпуска {year}; у исправных машин группы «{group}» — {peer_year} "
              "(медиана), то есть сломалась, будучи новее на {years} г.",
        "en": "Built in {year}; vehicles in the {group} group that did not break — "
              "{peer_year} (median), i.e. it broke despite being {years} year(s) newer",
    },
    "signal.MORE_TRIPS_THAN_PEERS": {
        "uz": "Davrda {trips} reys qilgan; {group} guruhidagi buzilmaganlar — {peer_trips} "
              "(mediana)",
        "ru": "За период {trips} рейс(ов); у исправных машин группы «{group}» — "
              "{peer_trips} (медиана)",
        "en": "Made {trips} trip(s) in the period; vehicles in the {group} group that "
              "did not break — {peer_trips} (median)",
    },
    "signal.FEWER_TRIPS_THAN_PEERS": {
        "uz": "Davrda {trips} reys qilgan — {group} guruhidagi buzilmaganlardan kam "
              "({peer_trips}, mediana)",
        "ru": "За период {trips} рейс(ов) — меньше, чем у исправных машин группы "
              "«{group}» ({peer_trips}, медиана)",
        "en": "Made {trips} trip(s) in the period — fewer than vehicles in the {group} "
              "group that did not break ({peer_trips}, median)",
    },
    "signal.MORE_DRIVERS_THAN_PEERS": {
        "uz": "{drivers} xil haydovchi haydagan; {group} guruhidagi buzilmaganlarda — "
              "{peer_drivers} (mediana)",
        "ru": "Управляли {drivers} разных водителей; у исправных машин группы "
              "«{group}» — {peer_drivers} (медиана)",
        "en": "Driven by {drivers} different drivers; vehicles in the {group} group that "
              "did not break — {peer_drivers} (median)",
    },
    "signal.REPEATED_COMPONENT": {
        "uz": "{component} {count} marta buzilgan",
        "ru": "{component}: {count} поломки",
        "en": "{component} broke {count} times",
    },
    "signal.REPEAT_BREAKDOWN": {
        "uz": "{previous} ta'miridan keyin {trips} reysda yana buzildi ({current})",
        "ru": "После ремонта {previous} снова сломалась через {trips} рейс(ов) ({current})",
        "en": "Broke again {trips} trip(s) after repair {previous} ({current})",
    },
    "signal.SAME_DRIVER": {
        "uz": "{count} ta buzilishning {same} tasida rulda bitta haydovchi: {driver}",
        "ru": "В {same} из {count} поломок за рулём один водитель: {driver}",
        "en": "The same driver was at the wheel in {same} of {count} breakdowns: {driver}",
    },
    "signal.DRIVER_HIGH_RATE": {
        "uz": "Haydovchi {driver}: davrda {trips} reys va {breakdowns} buzilish; butun "
              "park bo'yicha {fleet} reysga 1 buzilish",
        "ru": "Водитель {driver}: за период {trips} рейс(ов) и {breakdowns} поломок; по "
              "всему парку 1 поломка на {fleet} рейс(ов)",
        "en": "Driver {driver}: {trips} trip(s) and {breakdowns} breakdown(s) in the "
              "period; fleet-wide 1 breakdown per {fleet} trip(s)",
    },
    "signal.REWORK": {
        "uz": "{number} ta'miri qayta ishlangan yoki mexanik qayta tekshiruvidan o'tmagan",
        "ru": "Ремонт {number} переделывался или не прошёл повторную проверку механика",
        "en": "Repair {number} was reworked or failed the mechanic's recheck",
    },
    "signal.SPEEDING": {
        "uz": "Tezlikni oshirish: {count} marta, eng ko'pi +{max} km/soat",
        "ru": "Превышение скорости: {count} раз, максимум +{max} км/ч",
        "en": "Speeding: {count} time(s), at most +{max} km/h",
    },
    "signal.HARSH_DRIVING": {
        "uz": "Keskin tormoz yoki keskin tezlanish hodisalari: {count}",
        "ru": "Резкие торможения или ускорения: {count}",
        "en": "Harsh braking or acceleration events: {count}",
    },
    "signal.ACCIDENT": {
        "uz": "Avariyalar: {count}, shundan ta'mir talab qilgani: {repair}",
        "ru": "ДТП: {count}, из них требовали ремонта: {repair}",
        "en": "Accidents: {count}, of which required repair: {repair}",
    },
    "signal.MAINTENANCE_OVERDUE": {
        "uz": "{number} buzilgan kuni texnik xizmat muddati o'tgan edi ({kind}, muddat {due})",
        "ru": "На дату поломки {number} обслуживание было просрочено ({kind}, срок {due})",
        "en": "Maintenance was overdue on the day of breakdown {number} ({kind}, due {due})",
    },
    "signal.PART_PAST_LIFE": {
        "uz": "Resursi tugagan yoki eskirgan qismlar: {parts}",
        "ru": "Детали с исчерпанным ресурсом или изношенные: {parts}",
        "en": "Parts past their service life or worn: {parts}",
    },

    # ---------------------------------------------------- Sabab omillari
    "factor.speed_violation": {
        "uz": "tezlikni oshirish", "ru": "превышение скорости", "en": "speeding"},
    "factor.incident": {
        "uz": "keskin haydash hodisalari", "ru": "резкое вождение", "en": "harsh driving events"},
    "factor.vehicle_accident": {"uz": "avariyalar", "ru": "ДТП", "en": "accidents"},
    "factor.maintenance_plan": {
        "uz": "texnik xizmat muddati", "ru": "сроки техобслуживания",
        "en": "maintenance schedule"},
    "factor.vehicle_part": {
        "uz": "ehtiyot qism resursi", "ru": "ресурс запчастей", "en": "part service life"},

    # ------------------------------------------------- data_quality.notes
    "note.factors_unchecked": {
        "uz": "Tekshirib bo'lmagan sabablar (jadval bo'sh): {items}. Bu \"sabab yo'q\" "
              "degani emas",
        "ru": "Не удалось проверить причины (таблица пуста): {items}. Это не значит, "
              "что причины нет",
        "en": "Causes that could not be checked (table is empty): {items}. This does not "
              "mean the cause is absent",
    },
    "note.no_trip_data": {
        "uz": "Reys yozuvlari yo'q (`trip` bo'sh) — ish hajmi noma'lum, shuning uchun "
              "kam buzilayotganlar reytingi tuzilmadi",
        "ru": "Нет записей о рейсах (`trip` пуста) — объём работы неизвестен, рейтинг "
              "редко ломающихся не построен",
        "en": "No trip records (`trip` is empty) — workload is unknown, so the "
              "least-broken ranking was not built",
    },
    "note.excluded_repairs": {
        "uz": "{count} ta ta'mir so'rovi rad etilgan yoki bekor qilingan — buzilish "
              "sifatida sanalmadi (ro'yxatda `counted: false`)",
        "ru": "Заявок на ремонт отклонено или отменено: {count} — как поломки не "
              "считались (в списке `counted: false`)",
        "en": "{count} repair request(s) were rejected or cancelled — not counted as "
              "breakdowns (`counted: false` in the list)",
    },
    "note.broken_without_trips": {
        "uz": "Buzilgan, lekin davrda reys yozuvi yo'q mashinalar ({count}): {plates} — "
              "ularning buzilish tezligi hisoblanmadi",
        "ru": "Сломавшиеся машины без рейсов за период ({count}): {plates} — частота "
              "поломок не рассчитана",
        "en": "Broken vehicles with no trips in the period ({count}): {plates} — their "
              "breakdown rate was not calculated",
    },
    "note.no_release_year": {
        "uz": "{count} ta mashinada chiqarilgan yili yo'q — yoshi solishtirilmadi",
        "ru": "У {count} машин не указан год выпуска — возраст не сравнивался",
        "en": "{count} vehicle(s) have no production year — age was not compared",
    },
    "note.no_cost": {
        "uz": "Ta'mir narxi (`estimated_cost`) birorta buzilishda yozilmagan — narx "
              "bo'yicha solishtirilmadi",
        "ru": "Стоимость ремонта (`estimated_cost`) не записана ни в одной поломке — "
              "по стоимости не сравнивалось",
        "en": "Repair cost (`estimated_cost`) is not recorded for any breakdown — cost "
              "was not compared",
    },
    "note.max_rows": {
        "uz": "Yozuvlar chegarasiga yetildi ({limit}) — natija qirqilgan bo'lishi mumkin "
              "(`BR_MAX_ROWS`)",
        "ru": "Достигнут лимит записей ({limit}) — результат мог быть обрезан "
              "(`BR_MAX_ROWS`)",
        "en": "The record limit was reached ({limit}) — the result may be truncated "
              "(`BR_MAX_ROWS`)",
    },
    "note.no_breakdowns": {
        "uz": "Tanlangan davr va filtr bo'yicha buzilish yozuvi yo'q",
        "ru": "За выбранный период и фильтр записей о поломках нет",
        "en": "No breakdown records for the selected period and filter",
    },

    # ------------------------------------------------------ 400 xatolari
    "error.dates": {
        "uz": "`date_from` `date_to` dan katta bo'lmasligi kerak",
        "ru": "`date_from` не должна быть больше `date_to`",
        "en": "`date_from` must not be later than `date_to`",
    },
    "error.no_vehicles_for_type": {
        "uz": "`transport_type='{given}'` bo'yicha bazada mashina yo'q{unknown}. Bazadagi turlar: {types}",
        "ru": "По `transport_type='{given}'` в базе нет машин{unknown}. Типы в базе: {types}",
        "en": "There are no vehicles for `transport_type='{given}'` in the database{unknown}. "
              "Types in the database: {types}",
    },
    "error.unknown_type": {
        "uz": " (bunday tur umuman yo'q)",
        "ru": " (такого типа не существует)",
        "en": " (no such type exists)",
    },
}
