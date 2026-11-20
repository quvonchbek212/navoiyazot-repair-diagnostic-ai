"""Ta'mir yordamchisi sozlamalari.

BU YERDA HAM MEYOR YO'Q. "O'xshashlik necha foizdan", "necha kundan keyin
takror" kabi chegara kodga yozilmagan. Quyidagilar — prompt hajmi va resurs
himoyasi.

LLM PROVAYDERI SOZLANMAYDI: modul erkin matn (mexanik yozgan alomat)
yuboradi, shuning uchun so'rov faqat ichki serverga boradi (`llm.py`).
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


def _flag(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    return default if not raw else raw not in ("0", "false", "off", "no")


#: Bitta so'rovda bazadan o'qiladigan eng ko'p naryad — eng yangilari.
MAX_ROWS = _int("RA_MAX_ROWS", 20000)

#: Nechta eng o'xshash ta'mir olinadi — hisobga ham, promptga ham. Bu
#: o'xshashlik chegarasi EMAS: butun tarix promptga solinmasin degan himoya.
SIMILAR_TOP = _int("RA_SIMILAR_TOP", 5)

#: BITTA LLM javobining eng ko'p tokeni.
LLM_MAX_TOKENS = _int("RA_LLM_MAX_TOKENS", 320)

#: Muddat izohi so'rovi muhlati (soniya). Tavsiya va takror tahlili —
#: `RA_DIAGNOSIS_TIMEOUT_SECONDS`.
LLM_TIMEOUT_SECONDS = _int("RA_LLM_TIMEOUT_SECONDS", 60)

#: Tavsiya javobi (JSON: 3 sabab + 4 tekshiruv) — kattaroq. Kesilsa JSON
#: o'qilmaydi va javob 503 bo'ladi.
DIAGNOSIS_MAX_TOKENS = _int("RA_DIAGNOSIS_MAX_TOKENS", 640)

#: Tavsiya so'rovi muhlati (soniya). 31.10.2026: bitta so'rov 33-40 s (vLLM,
#: ~300 token JSON) — `RA_LLM_TIMEOUT_SECONDS` (60) ga yaqin, GPU chatbot bilan
#: umumiy. Muddat izohi qisqa (9 s) va umumiy muhlatda qoladi.
DIAGNOSIS_TIMEOUT_SECONDS = _int("RA_DIAGNOSIS_TIMEOUT_SECONDS", 90)

#: Javoblar jurnali (`log.py`) — suhbat tarixi serverida. `CHAT_DB_*`
#: sozlanmagan bo'lsa baribir yozilmaydi.
LOG_ENABLED = _flag("RA_LOG", True)
