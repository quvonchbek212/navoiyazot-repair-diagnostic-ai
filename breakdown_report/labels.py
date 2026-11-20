"""Ta'mirga xos enum qiymatlarining nomlari — uch tilda (uz, ru, en).

Transport turi nomlari `vehicle_selection/labels.py` dan olinadi — bitta
lug'at ikki joyda yozilmaydi. Bu yerda faqat ta'mir va texnik xizmatga
xos qiymatlar.

Kalitlar `atil_chatbot/ddl.sql` dagi CHECK ro'yxatidan ko'chirilgan;
`tests/test_breakdown_report.py` ikkalasini solishtirib turadi.
"""

from __future__ import annotations

from atil_ai_dispetcher.vehicle_selection import labels as vs_labels

#: `vehicle_repair.component_category`
COMPONENT = {
    "ENGINE": {"uz": "motor", "ru": "двигатель", "en": "engine"},
    "BRAKES": {"uz": "tormoz tizimi", "ru": "тормозная система", "en": "brakes"},
    "TIRES": {"uz": "shinalar", "ru": "шины", "en": "tyres"},
    "BATTERY": {"uz": "akkumulyator", "ru": "аккумулятор", "en": "battery"},
    "ELECTRICAL": {
        "uz": "elektr jihozlari", "ru": "электрооборудование", "en": "electrical system"},
    "CHASSIS": {"uz": "yurish qismi", "ru": "ходовая часть", "en": "chassis"},
    "OTHER": {"uz": "boshqa", "ru": "прочее", "en": "other"},
}

#: `vehicle_repair.inspection_context`. DIQQAT: CHECK cheklovida qiymatlar
#: kichik harfda (`in_trip`), bazada esa katta harfda (`IN_TRIP`) yozilgan
#: (14.09.2026) — shuning uchun qidiruv katta harfga keltirib qilinadi.
CONTEXT = {
    "PRE_TRIP": {
        "uz": "reysdan oldingi ko'rikda", "ru": "на предрейсовом осмотре",
        "en": "at the pre-trip inspection"},
    "IN_TRIP": {"uz": "reys vaqtida", "ru": "в рейсе", "en": "during a trip"},
    "POST_TRIP": {
        "uz": "reysdan keyingi ko'rikda", "ru": "на послерейсовом осмотре",
        "en": "at the post-trip inspection"},
    "DIRECT": {
        "uz": "to'g'ridan-to'g'ri murojaatda", "ru": "при прямом обращении",
        "en": "reported directly"},
}

#: `maintenance_plan.kind`
MAINTENANCE_KIND = {
    "OIL_CHANGE": {"uz": "moy almashtirish", "ru": "замена масла", "en": "oil change"},
    "TIRE_ROTATION": {
        "uz": "shinalar almashinuvi", "ru": "перестановка шин", "en": "tyre rotation"},
    "BRAKE_INSPECTION": {
        "uz": "tormoz tekshiruvi", "ru": "проверка тормозов", "en": "brake inspection"},
    "TIMING_BELT": {
        "uz": "taqsimlash tasmasi", "ru": "ремень ГРМ", "en": "timing belt"},
    "TECH_INSPECTION": {"uz": "texnik ko'rik", "ru": "техосмотр", "en": "technical inspection"},
    "OTHER": {"uz": "boshqa xizmat", "ru": "прочее обслуживание", "en": "other service"},
}

#: `maintenance_plan.maintenance_type`
MAINTENANCE_TYPE = {
    "TO_1": {"uz": "TXK-1", "ru": "ТО-1", "en": "service 1"},
    "TO_2": {"uz": "TXK-2", "ru": "ТО-2", "en": "service 2"},
    "SEASONAL": {"uz": "mavsumiy xizmat", "ru": "сезонное обслуживание", "en": "seasonal service"},
    "DIAGNOSTIC": {"uz": "diagnostika", "ru": "диагностика", "en": "diagnostics"},
}

#: Maydon nomi -> (jadval, ustun, xarita). Test shu ro'yxat bo'yicha
#: `ddl.sql` bilan solishtiradi. `CONTEXT` bu yerda yo'q: uning CHECK'i
#: `in (...)` emas, `any(array[...])` ko'rinishida.
GROUPS: dict[str, tuple[str, str, dict[str, dict[str, str]]]] = {
    "component": ("vehicle_repair", "component_category", COMPONENT),
    "maintenance_kind": ("maintenance_plan", "kind", MAINTENANCE_KIND),
    "maintenance_type": ("maintenance_plan", "maintenance_type", MAINTENANCE_TYPE),
}

_TABLES = {
    "component": COMPONENT,
    "context": CONTEXT,
    "maintenance_kind": MAINTENANCE_KIND,
    "maintenance_type": MAINTENANCE_TYPE,
}


def label(group: str, value: str | None, lang: str = "uz") -> str:
    """Enum qiymatini tanlangan tilga o'giradi.

    Noma'lum qiymat XOM qaytariladi, tarjima o'ylab topilmaydi — xuddi
    `atil_ai_dispetcher.vehicle_selection.labels.label` dagidek.
    """
    if group == "transport_type" or value is None:
        return vs_labels.label("transport_type", value, lang)
    table = _TABLES[group]
    row = table.get(value) or table.get(str(value).upper())
    if not row:
        return value
    return row.get(lang) or row["uz"]
