"""Aniqlikni o'lchash — qo'lda ishga tushiriladi, ilovaga ulanmaydi.

    python -m repair_assistant.eval backtest
    python -m repair_assistant.eval eta --runs 3 --cases 4 --lang uz
    python -m repair_assistant.eval diagnosis --runs 3 --repairs ARM-20260902-0011,...
    python -m repair_assistant.eval recurrence --runs 3

BACKTEST (LLM'siz). Har yopilgan naryad uchun "o'sha paytda nima degan
bo'lardik": naryad ochilgan payt va har yozilgan belgi (ARM qabuli,
diagnostika) payti. Naryad shu paytdagi holatiga qaytariladi — keyingi
belgilar va chiqish yo'q, keyin so'ralgan qism yo'q, keyin berilgani
berilmagan. Tarix — faqat shu paytgacha chiqqan remontlar (`estimate.build`
o'zi shunday). Haqiqiy chiqish bilan solishtiriladi:
  * oraliqqa tushdimi;
  * mediana bo'yicha xato (soat);
  * ODDIY MEDIANA: shu tugundagi (bo'lmasa butun park) shu paytgacha chiqqan
    remontlar muddati medianasi, naryad ochilganidan.

ETA. Izoh promptini haqiqiy holatlarda N marta ishga tushiradi (8-tamoyil:
prompt o'zgarishidan oldin va keyin kamida 3 marta). Holatlar — backtest
nuqtalari, taxmin chiqqanlari. Har javobda faktlarda yo'q sonlar sanaladi;
qolganini o'qib baholash kerak.

RECURRENCE. Takrori bor har mashina bugun va oxirgi takror endi ochilgan
paytda, oxirida bitta SUN'IY shina holati (`recurrence_cases`).

DIAGNOSIS. Yopilgan naryad OCHILGAN paytga qaytariladi, tavsiya N marta
olinadi va yonida o'sha naryadda AMALDA nima qilingani chiqadi — baholash
qo'lda. Avtomatik sanaladi: "tarix" bandlari, kod "umumiy bilim"ga tushirgan
bandlar, matnga tushgan O1 kabi kodlar, faktlarda yo'q sonlar.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
for _path in (_ROOT, _ROOT / "atil_chatbot"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from repair_assistant import config, diagnosis, estimate, explain, llm, queries, recurrence, similar  # noqa: E402,E501
from repair_assistant.common import EXCLUDED_REPAIR_STATUSES, EXIT_COLUMNS, exit_of  # noqa: E402

_HOUR = 3600.0


def as_of(repair: dict[str, Any], at: datetime) -> dict[str, Any]:
    """Naryad `at` paytidagi holatida: ochiq, keyingi belgilarsiz."""
    masked = dict(repair, status="REPAIR_IN_PROGRESS", **{c: None for c in EXIT_COLUMNS})
    for column, _stage in estimate.ANCHORS[1:]:
        if masked.get(column) and masked[column] > at:
            masked[column] = None
    return masked


def parts_as_of(parts: list[dict[str, Any]], repair_id: str, at: datetime) -> list[dict[str, Any]]:
    """Naryadning qismlari `at` paytidagidek; boshqa naryadlarniki o'zgarmaydi."""
    out = []
    for part in parts:
        if part["repair_id"] == repair_id:
            if not part.get("requested_at") or part["requested_at"] > at:
                continue
            if part.get("issued_at") and part["issued_at"] > at:
                part = dict(part, issued_at=None, status="REQUESTED")
        out.append(part)
    return out


def points(repair: dict[str, Any]) -> list[tuple[str, datetime]]:
    """Taxmin so'raladigan paytlar: ochildi va har yozilgan belgi (tartib bilan)."""
    exited, _source = exit_of(repair)
    out = [("opened_at", repair["opened_at"])]
    for column, _stage in estimate.ANCHORS[1:]:
        value = repair.get(column)
        if value is not None and out[-1][1] <= value < exited:
            out.append((column, value))
    return out


def baseline(target: dict[str, Any], repairs: list[dict[str, Any]], at: datetime) -> float | None:
    """Oddiy mediana: shu tugun (bo'lmasa butun park), ochilishdan chiqishgacha, soat."""
    history = similar.closed_before(repairs, now=at, exclude_id=target["id"])
    same = [h for h in history if h.get("component_category") == target.get("component_category")]
    group = same or history
    if not group:
        return None
    return median((exit_of(h)[0] - h["opened_at"]).total_seconds() for h in group) / _HOUR


def backtest(repairs: list[dict[str, Any]], parts: list[dict[str, Any]], *,
             middle: bool = False) -> list[dict[str, Any]]:
    """`middle` — ta'mir o'rtasi ham (LLM holatlari uchun): tezroq tugagan
    o'xshash ta'mir va kutilayotgan qism belgi paytida emas, shu yerda chiqadi."""
    cases = []
    closed = [r for r in repairs if r.get("status") not in EXCLUDED_REPAIR_STATUSES
              and exit_of(r)[0] is not None and exit_of(r)[0] >= r["opened_at"]]
    for repair in sorted(closed, key=lambda r: r["opened_at"]):
        exited, _source = exit_of(repair)
        at_points = points(repair)
        if middle:
            at_points.append(("middle", repair["opened_at"] + (exited - repair["opened_at"]) / 2))
        for column, at in at_points:
            target = as_of(repair, at)
            pool = [target if r["id"] == repair["id"] else r for r in repairs]
            result = estimate.build(target, pool, parts_as_of(parts, repair["id"], at),
                                    now=at, top=config.SIMILAR_TOP, lang="uz")
            est = result["estimate"]
            base = baseline(repair, repairs, at)
            cases.append({
                "repair": repair, "point": column, "at": at, "result": result,
                "actual_h": (exited - at).total_seconds() / _HOUR,
                "hit": est is not None and est["ready_from"] <= exited <= est["ready_to"],
                "error_h": (abs((est["ready_median"] - exited).total_seconds()) / _HOUR
                            if est else None),
                "baseline_error_h": (abs((repair["opened_at"] - exited).total_seconds() / _HOUR
                                         + base) if base is not None else None),
            })
    return cases


def _f(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def print_backtest(cases: list[dict[str, Any]]) -> None:
    print(f"{'naryad':<20}{'nuqta':<29}{'haqiqiy':>8}  {'taxmin [min med max]':<24}"
          f"{'n':>5}  {'tushdi':<7}{'xato':>7}{'mediana xatosi':>16}")
    for c in cases:
        est = c["result"]["estimate"]
        basis = c["result"]["basis"]
        rng = (f"[{_f(est['remaining_hours']['min'])} {_f(est['remaining_hours']['median'])} "
               f"{_f(est['remaining_hours']['max'])}]" if est else c["result"]["outcome"])
        print(f"{(c['repair'].get('repair_number') or '?')[-20:]:<20}{c['point']:<29}"
              f"{_f(c['actual_h']):>8}  {rng:<24}{basis['used']:>2}/{basis['similar_repairs']:<2}  "
              f"{('ha' if c['hit'] else 'yo`q') if est else '':<7}{_f(c['error_h']):>7}"
              f"{_f(c['baseline_error_h']):>16}")
    with_est = [c for c in cases if c["result"]["estimate"]]
    both = [c for c in with_est if c["baseline_error_h"] is not None]
    print(f"\nnuqtalar: {len(cases)}; taxmin chiqdi: {len(with_est)}; "
          f"oraliqqa tushdi: {sum(c['hit'] for c in with_est)}/{len(with_est)}")
    if both:
        print(f"mediana xatosi (soat, {len(both)} ta umumiy nuqtada): "
              f"taxmin {median(c['error_h'] for c in both):.1f}, "
              f"oddiy mediana {median(c['baseline_error_h'] for c in both):.1f}")
        # Ochilish nuqtasida bosqich hisobi yo'q — farq faqat o'xshashlarni tanlashdan.
        for point, _stage in estimate.ANCHORS:
            group = [c for c in both if c["point"] == point]
            if group:
                print(f"   {point:<29}{len(group):>3} ta: taxmin "
                      f"{median(c['error_h'] for c in group):.1f}, oddiy mediana "
                      f"{median(c['baseline_error_h'] for c in group):.1f}")
    if with_est:
        widths = [c["result"]["estimate"]["remaining_hours"]["max"]
                  - c["result"]["estimate"]["remaining_hours"]["min"] for c in with_est]
        print(f"oraliq kengligi (soat): mediana {median(widths):.1f}, eng kengi {max(widths):.1f}")


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def unknown_numbers(text: str, facts: str) -> list[str]:
    """Javobdagi faktlarda yo'q sonlar (vergul nuqtaga keltiriladi)."""
    known = {n.replace(",", ".") for n in _NUMBER.findall(facts)}
    return [n for n in _NUMBER.findall(text) if n.replace(",", ".") not in known]


async def run_llm(cases: list[dict[str, Any]], runs: int, lang: str) -> None:
    for case in cases:
        result = case["result"]
        facts = explain._json(explain.eta_facts(result, lang))
        print("=" * 100)
        print(f"{result['repair_number']} ({case['point']}), haqiqiy qolgan: {_f(case['actual_h'])} soat")
        print(facts)
    prompts = [explain.eta_prompt(c["result"], lang) for c in cases]
    for run in range(1, runs + 1):
        answers = await asyncio.gather(
            *(llm.ask_internal(p, max_tokens=config.LLM_MAX_TOKENS) for p in prompts),
            return_exceptions=True)
        for case, answer in zip(cases, answers):
            print("-" * 100)
            print(f"[{run}] {case['result']['repair_number']} ({case['point']})")
            if isinstance(answer, BaseException):
                print(f"   XATO: {answer}")
                continue
            text = explain._complete(answer)
            facts = explain._json(explain.eta_facts(case["result"], lang))
            print(f"   {text}")
            unknown = unknown_numbers(text, facts)
            print(f"   so'zlar: {len(text.split())}; faktlarda yo'q sonlar: {unknown or 'yo`q'}")


def _pick(cases: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Promptning har bandi sinalsin — har guruhdan navbat bilan, har xil naryaddan:
    kutilayotgan qism, tezroq tugaganlar, ikkalasi ham yo'q. Oxirida reja bandi
    uchun SUN'IY holat: 30.10.2026 da reja 3 naryadda va ularga tarix yo'q."""
    pool = [c for c in cases if c["result"]["estimate"]]
    groups = [
        [c for c in pool if c["result"]["pending_parts"]],
        [c for c in pool if c["result"]["basis"]["excluded_shorter"]],
        [c for c in pool if not c["result"]["pending_parts"]
         and not c["result"]["basis"]["excluded_shorter"]],
    ]
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    while len(picked) < count and any(groups):
        for group in groups:
            while group and group[0]["repair"]["id"] in seen:
                group.pop(0)
            if group and len(picked) < count:
                case = group.pop(0)
                seen.add(case["repair"]["id"])
                picked.append(case)
    if picked:
        base = picked[-1]
        result = base["result"]
        now, ready_from = result["now"], result["estimate"]["ready_from"]
        if ready_from > now:
            plan = {"planned_exit_at": now + (ready_from - now) / 2, "passed": False,
                    "position": "BEFORE"}
            picked.append(dict(base, point=f"{base['point']} + sun'iy reja",
                               result=dict(result, plan=plan)))
    return picked


# ------------------------------------------------------------ Nosozlik bo'yicha tavsiya

_CODE_IN_TEXT = re.compile(r"\bO\d+\b")


def diagnosis_cases(repairs: list[dict[str, Any]], parts: list[dict[str, Any]],
                    items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Har yopilgan naryad OCHILGAN paytda: tavsiya faktlari va aslida nima qilingani.

    Naryadning o'z ish bandlari va qismlari faktlarga kirmaydi (`diagnosis.build`
    ularni faqat o'xshash ta'mirlardan oladi) — ular javob bilan solishtirish uchun.
    """
    items_by: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        items_by.setdefault(item["repair_id"], []).append(item)
    cases = []
    closed = [r for r in repairs if r.get("status") not in EXCLUDED_REPAIR_STATUSES
              and exit_of(r)[0] is not None]
    for repair in sorted(closed, key=lambda r: r["opened_at"]):
        at = repair["opened_at"]
        target = as_of(repair, at)
        pool = [target if r["id"] == repair["id"] else r for r in repairs]
        cases.append({
            "repair": repair,
            "result": diagnosis.build(target, pool, parts, items, now=at,
                                      top=config.SIMILAR_TOP, lang="uz"),
            "actual_work": diagnosis.work_done(repair, items_by.get(repair["id"]) or [],
                                               frozenset()),
            "actual_parts": sorted({p["item_name"] for p in parts
                                    if p["repair_id"] == repair["id"] and p.get("item_name")}),
        })
    return cases


def _pick_diagnosis(cases: list[dict[str, Any]], count: int,
                    numbers: list[str] | None) -> list[dict[str, Any]]:
    """Berilgan naryadlar yoki har guruhdan navbat bilan: shu tugun bilan qaytgan
    mashina, oqibati yozilgan tarix, oqibatsiz tarix, tarix yo'q."""
    pool = [c for c in cases if c["result"]["outcome"] == "ADVISED"]
    if numbers:
        return [c for n in numbers for c in pool if c["repair"].get("repair_number") == n]

    def back(case: dict[str, Any]) -> bool:
        return any(r["came_back_days"] is not None or r["days_before_target"] is not None
                   for r in case["result"]["similar"])

    groups = [
        [c for c in pool if back(c)],
        [c for c in pool if not back(c) and c["result"]["basis"]["with_outcome"]],
        [c for c in pool if c["result"]["similar"] and not c["result"]["basis"]["with_outcome"]],
        [c for c in pool if not c["result"]["similar"]],
    ]
    picked: list[dict[str, Any]] = []
    while len(picked) < count and any(groups):
        for group in groups:
            if group and len(picked) < count:
                picked.append(group.pop(0))
    return picked


async def run_diagnosis(cases: list[dict[str, Any]], runs: int, lang: str) -> None:
    for case in cases:
        result = case["result"]
        print("=" * 100)
        print(f"{result['repair_number']} [{result['component_name']}] alomat: "
              f"{result['symptom']!r}; joy: {result['area']!r}")
        print(f"   ASLIDA: ish {case['actual_work'] or '-'}; qismlar {case['actual_parts'] or '-'}")
        for r in result["similar"]:
            print(f"   {r['code']} {r['repair_number']} {r['match']} alomat={r['symptom']!r} "
                  f"ish={r['work']} qismlar={r['parts']} qaytgan={r['came_back_days']} "
                  f"oldin={r['days_before_target']}")
    prompts = [explain.diagnosis_prompt(c["result"], lang) for c in cases]
    totals = {"bandlar": 0, "tarix": 0, "tushirilgan": 0, "kod_matnda": 0, "soxta_son": 0,
              "xato": 0}
    for run in range(1, runs + 1):
        started = time.perf_counter()
        answers = await asyncio.gather(
            *(llm.ask_internal(p, max_tokens=config.DIAGNOSIS_MAX_TOKENS,
                               json_schema=explain.DIAGNOSIS_SCHEMA) for p in prompts),
            return_exceptions=True)
        print("-" * 100)
        print(f"[{run}] {time.perf_counter() - started:.1f} s")
        for case, answer in zip(cases, answers):
            result = case["result"]
            print(f"  {result['repair_number']}")
            if isinstance(answer, BaseException):
                totals["xato"] += 1
                print(f"     XATO: {answer}")
                continue
            data = explain._parse(answer)
            codes = {r["code"]: r["repair_id"] for r in result["similar"] if r["has_outcome"]}
            by_id = {r["repair_id"]: r["code"] for r in result["similar"]}
            facts = explain._json(explain.diagnosis_facts(result, lang))
            for key, limit in (("sabablar", explain.CAUSES_MAX), ("tekshirish", explain.CHECKS_MAX)):
                items, relabeled = explain.advice(data.get(key), codes, limit)
                totals["tushirilgan"] += relabeled
                if not items:
                    totals["xato"] += 1
                print(f"     {key}:{f' (tarixdan tushirilgan: {relabeled})' if relabeled else ''}")
                for item in items:
                    totals["bandlar"] += 1
                    totals["tarix"] += item["source"] == "history"
                    in_text = _CODE_IN_TEXT.findall(item["text"])
                    numbers = unknown_numbers(item["text"], facts)
                    totals["kod_matnda"] += bool(in_text)
                    totals["soxta_son"] += bool(numbers)
                    source = ("tarix " + ",".join(by_id[i] for i in item["repair_ids"])
                              if item["source"] == "history" else "umumiy")
                    flags = "".join([f" [kod matnda: {in_text}]" if in_text else "",
                                     f" [faktlarda yo'q son: {numbers}]" if numbers else ""])
                    print(f"       ({source}) {item['text']}{flags}")
    print("=" * 100)
    print("JAMI:", totals)


# ------------------------------------------------------------- Takroriy nosozlik

def recurrence_cases(repairs: list[dict[str, Any]], parts: list[dict[str, Any]],
                     items: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Takrori bor har mashina: bugun va oxirgi takror endi ochilgan payt (ishi hali
    yozilmagan). Oxirida SUN'IY shina holati — 31.10.2026 da haqiqiy takror faqat
    tormozda, qism eskirishi bandini sinash uchun ikki mashinaning oxirgi shina
    ta'miri qismlari yozilgan bitta mashinaga ko'chiriladi."""
    def case(label: str, vehicle_id: str, pool: list[dict[str, Any]], at: datetime) -> dict[str, Any]:
        vehicle = queries.fetch_vehicle(vehicle_id)
        mine = [r for r in pool if r["vehicle_id"] == vehicle_id]
        history = queries.fetch_vehicle_history(vehicle_id, since=min(r["opened_at"] for r in mine))
        return {"label": label, "result": recurrence.build(vehicle, pool, parts, items, history,
                                                           now=at, lang="uz")}

    cases = []
    for vehicle_id in sorted({r["vehicle_id"] for r in repairs if r.get("vehicle_id")}):
        found = recurrence.groups(repairs, vehicle_id, now=now)
        if not found:
            continue
        cases.append(case("bugun", vehicle_id, repairs, now))
        last = max(r["opened_at"] for g in found.values() for r in g)
        cases.append(case("oxirgi takror endi ochilgan", vehicle_id, repairs,
                          last + timedelta(minutes=1)))
    tires = sorted((r for r in repairs if r.get("component_category") == "TIRES"
                    and exit_of(r)[0] is not None), key=lambda r: r["opened_at"])[-2:]
    host = next((c["result"]["vehicle_id"] for c in cases), None)
    if len(tires) == 2 and host:
        moved = {r["id"] for r in tires}
        pool = [dict(r, vehicle_id=host) if r["id"] in moved else r for r in repairs]
        cases.append(case("SUN'IY: ikki shina ta'miri bitta mashinada", host, pool, now))
    return cases


async def run_recurrence(cases: list[dict[str, Any]], runs: int, lang: str) -> None:
    # Har takrorlangan tugun — alohida so'rov, `explain.explain_recurrence` dagidek.
    pairs = [(case, group) for case in cases for group in case["result"]["groups"]]
    for case, group in pairs:
        print("=" * 100)
        print(f"{case['result']['plate_number']} — {case['label']} — {group['component_name']}")
        print(explain._json(explain.recurrence_facts(case["result"], group, lang))[:1500])
    prompts = [explain.recurrence_prompt(c["result"], g, lang) for c, g in pairs]
    totals = {"bandlar": 0, "tarix": 0, "tushirilgan": 0, "kod_matnda": 0, "soxta_son": 0,
              "xato": 0}
    for run in range(1, runs + 1):
        started = time.perf_counter()
        answers = await asyncio.gather(
            *(llm.ask_internal(p, max_tokens=config.DIAGNOSIS_MAX_TOKENS,
                               json_schema=explain.RECURRENCE_SCHEMA) for p in prompts),
            return_exceptions=True)
        print("-" * 100)
        print(f"[{run}] {time.perf_counter() - started:.1f} s")
        for (case, group), answer in zip(pairs, answers):
            print(f"  {case['result']['plate_number']} — {case['label']} — {group['component_name']}")
            if isinstance(answer, BaseException):
                totals["xato"] += 1
                print(f"     XATO: {answer}")
                continue
            hypotheses, checks, relabeled = explain.recurrence_items(answer, group)
            totals["tushirilgan"] += relabeled
            by_id = {e["repair_id"]: e["code"] for e in group["episodes"]}
            facts = explain._json(explain.recurrence_facts(case["result"], group, lang))
            for key, found in (("taxminlar", hypotheses), ("tekshirish", checks)):
                if not found:
                    totals["xato"] += 1
                print(f"     {key}:")
                for item in found:
                    totals["bandlar"] += 1
                    totals["tarix"] += item["source"] == "history"
                    in_text = re.findall(r"\bR\d+\b", item["text"])
                    numbers = unknown_numbers(item["text"], facts)
                    totals["kod_matnda"] += bool(in_text)
                    totals["soxta_son"] += bool(numbers)
                    source = ("tarix " + ",".join(by_id[i] for i in item["repair_ids"])
                              if item["source"] == "history" else "umumiy")
                    flags = "".join([f" [kod matnda: {in_text}]" if in_text else "",
                                     f" [faktlarda yo'q son: {numbers}]" if numbers else ""])
                    print(f"       ({source}) {item['text']}{flags}")
    print("=" * 100)
    print("JAMI:", totals)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("backtest", "eta", "diagnosis", "recurrence"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cases", type=int, default=4)
    parser.add_argument("--repairs", default="",
                        help="diagnosis: vergul bilan naryad raqamlari (ARM-20260902-0011,...)")
    parser.add_argument("--lang", default="uz")
    args = parser.parse_args()

    repairs = queries.fetch_repairs(limit=config.MAX_ROWS)
    ids = [r["id"] for r in repairs]
    parts = queries.fetch_parts(ids)
    print(f"{datetime.now(timezone.utc):%d.%m.%Y %H:%M} UTC; naryadlar: {len(repairs)}; "
          f"qism so'rovlari: {len(parts)}\n")
    if args.mode == "backtest":
        print_backtest(backtest(repairs, parts))
        return

    from ollama_client import check_ollama_alive_sync  # atil_chatbot/ollama_client.py

    if not check_ollama_alive_sync():
        sys.exit("vLLM javob bermayapti — VLLM_BASE_URL va tunnelni tekshiring")
    if args.mode == "eta":
        cases = backtest(repairs, parts, middle=True)
        asyncio.run(run_llm(_pick(cases, args.cases), args.runs, args.lang))
        return
    if args.mode == "recurrence":
        cases = recurrence_cases(repairs, parts, queries.fetch_work_items(ids),
                                 datetime.now(timezone.utc))
        asyncio.run(run_recurrence(cases, args.runs, args.lang))
        return
    cases = diagnosis_cases(repairs, parts, queries.fetch_work_items(ids))
    numbers = [n.strip() for n in args.repairs.split(",") if n.strip()]
    asyncio.run(run_diagnosis(_pick_diagnosis(cases, args.cases, numbers), args.runs, args.lang))


if __name__ == "__main__":
    main()
