"""LLM chaqiruvi — FAQAT ICHKI server: chatbot bilan umumiy klient
(`VLLM_BASE_URL`, bo'sh bo'lsa Ollama).

Modul erkin matn (mexanik yozgan alomat, ish matni) yuboradi, shuning uchun
tashqi provayder yo'li umuman yo'q: sozlamani o'zgartirib ham so'rovni
tashqariga chiqarib bo'lmaydi.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_CHATBOT_DIR = Path(__file__).resolve().parent.parent / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

from repair_assistant import config  # noqa: E402


class LLMUnavailable(RuntimeError):
    """Model javob bermadi yoki sozlanmagan."""


def internal_model_name() -> str:
    """Ichki server modeli — javobda ochiq ko'rsatiladi."""
    from config import MODEL_NAME  # atil_chatbot/config.py

    return MODEL_NAME


async def ask_internal(
    prompt: str, *, max_tokens: int, json_schema: dict[str, Any] | None = None,
    timeout: int | None = None,
) -> str:
    """Bitta prompt -> matn. Har qanday muvaffaqiyatsizlik `LLMUnavailable`.

    `timeout` berilmasa — `RA_LLM_TIMEOUT_SECONDS`.
    """
    # Kech import: LLM serveri o'chiq bo'lsa ham modul yuklansin.
    from config import DEFAULT_NUM_CTX  # atil_chatbot/config.py
    from ollama_client import ask_llm

    llm_config: dict[str, Any] = {
        "options": {
            "temperature": 0.2,
            "num_predict": max_tokens,
            # Chatbotniki bilan bir xil — Ollama boshqa `num_ctx` da modelni
            # qayta yuklaydi (batafsil: vehicle_selection/explain.py).
            "num_ctx": DEFAULT_NUM_CTX,
        },
        "think": False,
        "timeout": timeout or config.LLM_TIMEOUT_SECONDS,
    }
    if json_schema:
        llm_config["response_json_schema"] = json_schema
    try:
        return (await ask_llm(prompt, llm_config) or "").strip()
    except Exception as exc:  # noqa: BLE001 — har qanday yiqilish "javob yo'q"
        raise LLMUnavailable(str(exc)[:200]) from exc
