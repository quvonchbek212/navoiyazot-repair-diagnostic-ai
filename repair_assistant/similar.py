"""O'xshash ta'mirlarni tanlash — sof funksiya, baza va LLM'siz.

QOIDA (30.10.2026 da kelishilgan):
  * Nomzod — `now` gacha CHIQQAN remont, naryadning o'zi emas. Rad etilgan
    va bekor qilingan (`REJECTED`, `CANCELLED`) naryad remont emas.
  * O'xshash = bir xil tugun (`component_category`). `OTHER` ("boshqa")
    tugun hech narsa aytmaydi — u yerda alomat matnida umumiy so'z ham shart.
  * Tartib: alomat matni mosligi -> bir xil model -> shu mashina -> yangirog'i.
  * Eng mos K tasi (`RA_SIMILAR_TOP`) — prompt hajmi, o'xshashlik chegarasi EMAS.

MATN MOSLIGI. So'z kichik harfga, apostrof variantlari (ʻ ‘ ’ `) bittaga
keltiriladi; 3 harfdan qisqa bo'lak so'z sanalmaydi ("va", "15"). O'zbekcha
so'z qo'shimcha oladi ("shina" — "shinasi", "shinalar"), shuning uchun biri
ikkinchisining boshi bo'lsa ham mos. Mos so'zning og'irligi — IDF: ko'p
alomatda uchraydigan so'z ("old", "tomon") kam narsa aytadi. Og'irlik
bazadan hisoblanadi — stop-so'zlar ro'yxati o'ylab topilmagan.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from breakdown_report.metrics import model_name
from repair_assistant.common import EXCLUDED_REPAIR_STATUSES, exit_of

#: Hech narsa aytmaydigan tugun — o'xshashlik uchun matn ham kerak.
VAGUE_COMPONENTS = ("OTHER", None)

_APOSTROPHES = re.compile(r"[ʻʼ‘’`´]")
_TOKEN = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")


def normalize(text: str | None) -> str:
    """Kichik harf, apostrof variantlari bitta (ʻ ‘ ’ ` -> ')."""
    return _APOSTROPHES.sub("'", (text or "").casefold())


def words(text: str | None) -> frozenset[str]:
    """Matndagi so'zlar: kichik harf, apostrof bitta, kamida 3 harf."""
    return frozenset(w for w in _TOKEN.findall(normalize(text)) if len(w.replace("'", "")) >= 3)


def symptom(repair: dict[str, Any]) -> str:
    """Alomat: mexanik yozgani va joy nomi."""
    return " ".join(part.strip() for part in (repair.get("initial_diagnosis"),
                                              repair.get("defect_area")) if part and part.strip())


def _same_word(a: str, b: str) -> bool:
    return a.startswith(b) or b.startswith(a)


def _has(word: str, bag: frozenset[str]) -> bool:
    return any(_same_word(word, other) for other in bag)


def _model(repair: dict[str, Any]) -> str:
    return " ".join(model_name(repair).casefold().split())


def closed_before(
    repairs: list[dict[str, Any]], *, now: datetime, exclude_id: str
) -> list[dict[str, Any]]:
    """Solishtirsa bo'ladigan remontlar: `now` gacha chiqqan, muddati ma'lum."""
    out = []
    for repair in repairs:
        if repair["id"] == exclude_id or repair.get("status") in EXCLUDED_REPAIR_STATUSES:
            continue
        exited, _source = exit_of(repair)
        if exited is None or exited > now or exited < repair["opened_at"]:
            continue
        out.append(repair)
    return out


def rank(target: dict[str, Any], candidates: list[dict[str, Any]], *, top: int) -> list[dict[str, Any]]:
    """Eng mos `top` ta: `[{"repair", "match", "score"}]`, eng mosi birinchi.

    `match` — nega tanlangani: `component`, `text`, `model`, `vehicle`.
    """
    component = target.get("component_category")
    target_words = words(symptom(target))
    bags = [words(symptom(c)) for c in candidates]
    # IDF naryadning o'zi bilan birga hisoblanadi: so'z faqat unda bo'lsa ham
    # og'irligi musbat qoladi.
    documents = len(bags) + 1
    idf = {w: math.log((1 + documents) / (1 + 1 + sum(_has(w, bag) for bag in bags))) + 1
           for w in target_words}
    model = _model(target)

    ranked = []
    for candidate, bag in zip(candidates, bags):
        if candidate.get("component_category") != component:
            continue
        score = sum(idf[w] for w in target_words if _has(w, bag))
        if component in VAGUE_COMPONENTS and not score:
            continue
        same_model = bool(model) and _model(candidate) == model
        same_vehicle = candidate.get("vehicle_id") == target.get("vehicle_id")
        ranked.append({
            "repair": candidate,
            "match": ["component"] + ["text"] * bool(score) + ["model"] * same_model
                     + ["vehicle"] * same_vehicle,
            "score": round(score, 3),
            "_key": (-score, not same_model, not same_vehicle,
                     -exit_of(candidate)[0].timestamp()),
        })
    ranked.sort(key=lambda m: m["_key"])
    return [{k: v for k, v in m.items() if k != "_key"} for m in ranked[:top]]
