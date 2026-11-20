"""Naryad bo'yicha umumiy qoidalar — `similar`, `estimate`, `diagnosis`,
`recurrence` va `service` shu yerdan oladi.

1. CHIQDI = `repaired_at` — ARM ta'mirni tugatgan payt; bazada u har doim
   `final_arm_approved_at` ga teng (28.10.2026: 16/16). `completed_at` —
   naryad YOPILGAN payt, u chiqishdan bir necha kun keyin bo'lishi mumkin
   (ARM-0006 va ARM-0008 29.08 da ta'mirdan chiqqan, 04.09 da bitta vaqtda
   yopilgan), shuning uchun faqat oxirgi zaxira manba (`EXIT_COLUMNS`).
2. RAD ETILGAN / BEKOR QILINGAN NARYAD TA'MIR EMAS — o'xshash ta'mirga ham,
   takrorga ham kirmaydi.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from repair_assistant.texts import t

#: Ta'mir sifatida SANALMAYDIGAN naryadlar.
EXCLUDED_REPAIR_STATUSES = ("REJECTED", "CANCELLED")

#: Mashina ta'mirdan chiqqan vaqt — birinchi to'lgani olinadi.
EXIT_COLUMNS = ("repaired_at", "final_arm_approved_at", "completed_at")

#: Hali berilmagan ehtiyot qism so'rovi holatlari.
PENDING_PART_STATUSES = ("REQUESTED", "WAITING_PARTS_APPROVAL", "PARTS_APPROVED")
EXCLUDED_PART_STATUSES = ("REJECTED",)

_DAY = 86400.0
_HOUR = 3600.0


def exit_of(repair: dict[str, Any]) -> tuple[datetime | None, str | None]:
    """(chiqish vaqti, qaysi ustundan)."""
    for column in EXIT_COLUMNS:
        if repair.get(column):
            return repair[column], column
    return None, None


def parts_wait_seconds(parts: list[dict[str, Any]], start: datetime, end: datetime) -> float:
    """Ehtiyot qism kutilgan vaqt — so'rovlar ORALIQLARINING birlashmasi.

    Ikki qism bir vaqtda kutilgan bo'lsa vaqt ikki marta sanalmaydi. Kutish
    so'rovdan berilgunga qadar; berilmagan bo'lsa naryad oxirigacha.
    """
    intervals = []
    for part in parts:
        requested = part.get("requested_at")
        if not requested or part.get("status") in EXCLUDED_PART_STATUSES:
            continue
        a, b = max(requested, start), min(part.get("issued_at") or end, end)
        if b > a:
            intervals.append((a, b))
    total, current_start, current_end = 0.0, None, None
    for a, b in sorted(intervals):
        if current_end is None or a > current_end:
            if current_end is not None:
                total += (current_end - current_start).total_seconds()
            current_start, current_end = a, b
        else:
            current_end = max(current_end, b)
    if current_end is not None:
        total += (current_end - current_start).total_seconds()
    return total


def _number(value: float) -> str:
    """10.0 -> "10", 0.43 -> "0.4"."""
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def span(lang: str, seconds: float) -> str:
    """Odam o'qiydigan davomiylik: bir kundan kami soatda, qolgani kunda.

    Rejalar soatlab yoziladi (28.10.2026: "diagnostikadan 1-3 soat keyin"),
    ta'mirlar esa kunlab cho'ziladi — ikkalasi bitta birlikda o'qilmaydi.
    """
    if seconds < _DAY:
        return t(lang, "unit.hours", n=_number(seconds / _HOUR))
    return t(lang, "unit.days", n=_number(seconds / _DAY))
