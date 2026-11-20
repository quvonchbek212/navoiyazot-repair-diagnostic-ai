"""Javoblar jurnali — tavsiyaning aniqligini keyin o'lchash uchun (`eval.py`).

ATIL bazasi faqat o'qish uchun, shuning uchun jurnal suhbat tarixi
serverida (`CHAT_DB_*`, yozishga ochiq) alohida jadvalda turadi. Ulanish
pool'i ham o'shaniki (`chat_history_db`) — bitta serverga ikkinchi pool
ochilmasin. Jadval `CHAT_DB_AUTO_CREATE` yoqiq bo'lsa o'zi yaratiladi.

Nima yoziladi: endpoint, naryad va mashina, til, prompt versiyasi (prompt
matnining xeshi), model va butun javob. Javobda LLM matni bor va u alomatni
takrorlashi mumkin — u ichki serverda qoladi.

Keyin `repair_id` bo'yicha ATIL bilan solishtiriladi: muddat — haqiqiy
chiqish vaqti bilan; tavsiya — naryadda aslida qilingan ish va qism bilan.

JURNAL JAVOBNI BUZMAYDI: javob yuborilgandan keyin fonda yoziladi (FastAPI
`BackgroundTasks`), har qanday xato faqat logga tushadi.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any

_CHATBOT_DIR = Path(__file__).resolve().parent.parent / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

from psycopg2 import sql as pg_sql  # noqa: E402

from repair_assistant import config  # noqa: E402

logger = logging.getLogger(__name__)

TABLE = "repair_assistant_log"

_table_ready = False
_table_lock = threading.Lock()


def _table(schema: str) -> pg_sql.Composed:
    return pg_sql.SQL("{}.{}").format(pg_sql.Identifier(schema), pg_sql.Identifier(TABLE))


def _ensure_table(cur: Any, schema: str) -> None:
    global _table_ready
    with _table_lock:
        if _table_ready:
            return
        cur.execute(pg_sql.SQL(
            "CREATE TABLE IF NOT EXISTS {} ("
            " id BIGSERIAL PRIMARY KEY,"
            " created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            " endpoint TEXT NOT NULL,"
            " repair_id TEXT,"
            " vehicle_id TEXT,"
            " lang TEXT,"
            " prompt_version TEXT,"
            " model TEXT,"
            " response JSONB NOT NULL"
            ")").format(_table(schema)))
        cur.execute(pg_sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (repair_id, created_at)").format(
            pg_sql.Identifier(f"{TABLE}_repair_idx"), _table(schema)))
        _table_ready = True


def write(
    *,
    endpoint: str,
    repair_id: str | None,
    vehicle_id: str | None,
    lang: str,
    prompt_version: str | None,
    model: str | None,
    response: dict[str, Any],
) -> bool:
    """Bitta javobni yozadi. Xato bo'lsa `False` — hech qachon otilmaydi."""
    if not config.LOG_ENABLED:
        return False
    try:
        from config import CHAT_DB_AUTO_CREATE, CHAT_DB_SCHEMA  # atil_chatbot/config.py
        from db import chat_history_db

        if not chat_history_db.is_configured():
            return False
        with chat_history_db.write_cursor() as cur:
            if CHAT_DB_AUTO_CREATE:
                _ensure_table(cur, CHAT_DB_SCHEMA)
            cur.execute(
                pg_sql.SQL(
                    "INSERT INTO {} (endpoint, repair_id, vehicle_id, lang, prompt_version,"
                    " model, response) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)"
                ).format(_table(CHAT_DB_SCHEMA)),
                (endpoint, repair_id, vehicle_id, lang, prompt_version, model,
                 json.dumps(response, ensure_ascii=False, default=str)),
            )
        return True
    except Exception as exc:  # noqa: BLE001 — jurnal javobni buzmasin
        logger.warning("Ta'mir yordamchisi jurnali yozilmadi: %s", str(exc).strip()[:300])
        return False
