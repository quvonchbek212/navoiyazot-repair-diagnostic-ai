"""Buzilish hisoboti sozlamalari.

BU YERDA MEYOR YO'Q — bu ataylab shunday. "Oyiga 3 martadan ko'p buzilsa
yomon" yoki "5 reysdan oldin buzilsa erta" degan chegara kodga yozilmagan,
chunki bazadagi hech narsa bunday raqamni aytmaydi. Mashinalar bir-biri
bilan SOLISHTIRILADI:

    ko'p buziladi   -> buzilishlar soni bo'yicha ro'yxatda yuqorida
    kam buziladi    -> ko'p ishlagan (reys), lekin kam buzilgan
    erta buzildi    -> bir xil modeldagi buzilmagan mashinalardan (mediana
                       chiqarilgan yili) yangi bo'lsa ham buzilgan

Quyidagi qiymatlar resurs himoyasi va javob hajmi, hukm chegarasi emas.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


# --------------------------------------------------------------- Resurs himoyasi
#: Bitta so'rovda bazadan o'qiladigan eng ko'p mashina/ta'mir yozuvi.
#: Chegaraga yetilsa javobning `data_quality.notes` ida ochiq yoziladi —
#: natija jimgina qirqilib qolmaydi.
MAX_ROWS = _int("BR_MAX_ROWS", 20000)

#: Har ro'yxatda (`most_broken`, `least_broken`, ...) qaytadigan qatorlar
#: soni. So'rovdagi `limit` bekor qiladi. Jami sonlar `summary` da doim
#: to'liq turadi — bu faqat ro'yxat uzunligi.
DEFAULT_LIMIT = _int("BR_DEFAULT_LIMIT", 10)
MAX_LIMIT = _int("BR_MAX_LIMIT", 500)

# ------------------------------------------------------------------ LLM tahlili
# Hisobni ARIFMETIKA quradi, LLM esa "nega" degan savolga javob yozadi.
# Tahlil 2 + N PARALLEL so'rov: umumiy xulosa, tavsiyalar va eng ko'p
# buzilgan N mashinaning har biriga sabab (nega parallel — `explain.py`).
#
# TAHLIL DOIM YOZILADI, o'chirgich yo'q (qolgan modullardagidek). LLM javob
# bermasa SHABLONGA TUSHILMAYDI — endpoint 503 qaytaradi.

#: Nechta eng ko'p buzilgan mashinaga LLM sabab yozadi. Maqsad — javob
#: 30 s ichida. 14.09.2026 prototip o'lchovi (butun park, parallel):
#:     top 5 -> 7 so'rov  -> 20 s
#:     top 9 -> 11 so'rov -> 33 s
#: Qolgan mashinalarda LLM matni yo'q, lekin `signals` (faktlar) bor.
LLM_ANALYZE_TOP = _int("BR_LLM_ANALYZE_TOP", 5)

#: BITTA so'rov javobining eng ko'p tokeni. Model qisqa yozishni promptdan
#: oladi; bu faqat "to'xtamay yozib ketsa" himoyasi.
#: 160 -> 240 (15.09.2026): butun park tavsiyalari 160 ga urilib chala
#: kesildi ("...Ashrabovichning hay"). Kesilgan jumla baribir `explain.
#: _complete` bilan olib tashlanadi, lekin zaxira kesilishning o'zini kamaytiradi.
LLM_MAX_TOKENS = _int("BR_LLM_MAX_TOKENS", 240)

#: Har so'rov muhlati (soniya). 0 — chatbotniki
#: (`CHATBOT_OLLAMA_TIMEOUT_SECONDS`, 150). 60: prototipda eng uzun parallel
#: so'rov 20 s (top 5) va 33 s (top 9) oldi — muhlat ikki barobardan ko'p
#: zaxira beradi, lekin server qotsa foydalanuvchi 150 s kutib qolmaydi.
LLM_TIMEOUT_SECONDS = _int("BR_LLM_TIMEOUT_SECONDS", 60)
