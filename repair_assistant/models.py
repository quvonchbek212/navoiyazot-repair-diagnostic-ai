"""Javob sxemasi — Swagger shu modellardan chiziladi.

Kod hisoblagan sonlar ham qaytadi — o'xshash ta'mirlar (soni va
`repair_id` lari), muddat oralig'i. Ularni backend o'zi hisoblay olmaydi;
LLM matni esa faqat izoh.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SimilarRepair(BaseModel):
    repair_id: str = Field(..., description="`vehicle_repair.id`")
    repair_number: str | None = Field(None, examples=["ARM-20260819-0007"])
    plate_number: str | None = Field(None, examples=["85312EBA"])
    match: list[Literal["component", "text", "model", "vehicle"]] = Field(
        ..., examples=[["component", "text", "model"]],
        description="Nega tanlangan: `component` — bir xil tugun, `text` — alomat matnida "
                    "umumiy so'z, `model` — bir xil model, `vehicle` — shu mashina")
    duration_hours: float = Field(..., description="Ta'mir muddati: ochilishdan chiqishgacha")
    measured_from: Literal["stage", "opened"] = Field(
        ..., description="`stage` — naryadning hozirgi bosqichi boshlangan belgidan "
                         "chiqishgacha o'lchandi; `opened` — bu belgi yozilmagan, ochilishdan")
    used: bool = Field(..., description="`false` — naryad bundan allaqachon uzoq turibdi, "
                                        "taxminga olinmadi")


class RemainingHours(BaseModel):
    min: float
    median: float
    max: float


class Estimate(BaseModel):
    ready_from: datetime = Field(..., description="Eng erta — eng tez tugagan o'xshash ta'mir bo'yicha")
    ready_median: datetime
    ready_to: datetime = Field(..., description="Eng kech — eng uzoq o'xshash ta'mir bo'yicha")
    remaining_hours: RemainingHours


class Basis(BaseModel):
    similar_repairs: int = Field(..., description="Tanlangan o'xshash ta'mirlar")
    used: int = Field(..., description="Shulardan taxminga olingani")
    excluded_shorter: int = Field(..., description="Naryad ulardan allaqachon uzoq turgani "
                                                   "uchun olinmagani")
    text: str = Field(..., examples=["4 ta o'xshash ta'mir asosida"],
                      description="Kod yozgan jumla — LLM emas")


class CurrentStage(BaseModel):
    code: Literal["ARM_ACCEPTANCE", "DIAGNOSIS", "REPAIR"]
    name: str
    since: datetime


class Plan(BaseModel):
    planned_exit_at: datetime = Field(..., description="`estimated_completion_time`")
    passed: bool
    position: Literal["PASSED", "BEFORE", "INSIDE", "AFTER"] | None = Field(
        None, description="Reja muddat oralig'iga nisbatan qayerda; taxmin yo'q bo'lsa `null`")


class EtaAnalysis(BaseModel):
    """MATN FAQAT LLM DAN; LLM javob bermasa 503."""

    explanation: str
    provider: str = Field("vllm", description="Faqat ichki server")
    model: str | None = Field(None, examples=["gemma4-31b"])
    prompt_version: str | None = Field(None, description="Prompt matnining xeshi — prompt "
                                                         "o'zgarsa o'zgaradi")


class AdviceItem(BaseModel):
    text: str
    source: Literal["history", "general_knowledge"] = Field(
        ..., description="`history` — o'xshash ta'mirda AMALDA qilingan ish yoki qaytishga "
                         "tayanadi; `general_knowledge` — umumiy bilim, tarixdan emas")
    repair_ids: list[str] = Field(
        default_factory=list, description="`history` bandi tayangan o'xshash ta'mirlar "
                                          "(`similar_repairs[].repair_id`)")


class DiagnosisAnalysis(BaseModel):
    """MATN FAQAT LLM DAN; LLM javob bermasa 503. `source` ni kod tekshiradi."""

    likely_causes: list[AdviceItem]
    check_points: list[AdviceItem] = Field(..., description="Nimadan boshlash kerakligi birinchi")
    relabeled: int = Field(0, description="LLM \"tarix\" degan, lekin oqibati yozilgan o'xshash "
                                          "ta'mirga tayanmagani uchun kod `general_knowledge` "
                                          "ga tushirgan bandlar")
    disclaimer: str = Field(..., examples=["Bu taxmin. Yakuniy qarorni mexanik qiladi."])
    provider: str = "vllm"
    model: str | None = Field(None, examples=["gemma4-31b"])
    prompt_version: str | None = None


class DiagnosisBasis(BaseModel):
    similar_repairs: int
    with_outcome: int = Field(..., description="Shulardan nima qilingani (ish, qism, qaytish) "
                                               "yozilgani — faqat ularga `history` tayanadi")
    text: str = Field(..., examples=["3 ta o'xshash ta'mir asosida"],
                      description="Kod yozgan jumla — LLM emas")


class DiagnosisSimilar(BaseModel):
    repair_id: str
    repair_number: str | None = None
    plate_number: str | None = None
    match: list[Literal["component", "text", "model", "vehicle"]]
    has_outcome: bool = Field(..., description="Nima qilingani yozilganmi")
    came_back_days: float | None = Field(
        None, description="Mashina shu tugun bilan necha kundan keyin qaytgan; qaytmagan — `null`")
    days_before_target: float | None = Field(
        None, description="Shu mashina: o'sha ta'mirdan bu naryadgacha, kun")


class RepairDiagnosis(BaseModel):
    repair_id: str
    repair_number: str | None = None
    plate_number: str | None = None
    outcome: Literal["ADVISED", "NO_SYMPTOM"] = Field(
        ..., description="`NO_SYMPTOM` — naryadda alomat ham, joy ham yozilmagan; "
                         "`analysis: null`, LLM chaqirilmaydi")
    basis: DiagnosisBasis
    similar_repairs: list[DiagnosisSimilar] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list, description="Tugun bo'yicha diagnostika nazorat ro'yxati")
    analysis: DiagnosisAnalysis | None = None
    generated_at: datetime
    elapsed_seconds: float = Field(0.0, description="BUTUN javob vaqti: baza + LLM")
    timings: dict[str, float] = Field(default_factory=dict, examples=[{"db": 0.2, "llm": 36.0}])


class RecurrenceRepair(BaseModel):
    repair_id: str
    repair_number: str | None = None
    opened_at: datetime
    exited_at: datetime | None = Field(None, description="Ochiq naryadda `null`")
    is_open: bool


class RecurrenceInterval(BaseModel):
    from_repair_id: str
    to_repair_id: str
    days: float | None = Field(None, description="Oldingi ta'mirdan chiqishdan keyingisiga "
                                                 "kirishgacha, kun; oldingisi yopilmagan yoki "
                                                 "ikkalasi bir vaqtda ochiq bo'lsa `null`")
    overlap: bool = Field(..., description="Keyingisi oldingisi yopilmasdan ochilgan")
    trips: int | None = Field(None, description="Oraliqda yo'l varaqasi bilan reyslar (`waybill`)")
    inspections_passed: int | None = Field(
        None, description="Oraliqda texnik ko'rikdan \"soz\" (`FIT`) deb o'tgani")


class PartWear(BaseModel):
    name: str | None = Field(None, examples=["Shina 155/70R12 (0065B07138548)"])
    category: Literal["TIRE", "BATTERY"]
    used_pct: int = Field(..., description="Xizmat muddatining necha foizi ishlatilgan")
    measured_by: Literal["km", "months"] = Field(
        ..., description="`km` — o'rnatilgandan beri probeg / `expected_life_km`; "
                         "`months` — yoshi / `expected_life_months`")


class RepeatGroup(BaseModel):
    component: str | None = Field(None, examples=["BRAKES"])
    component_name: str
    repairs: list[RecurrenceRepair] = Field(..., description="Eski -> yangi")
    intervals: list[RecurrenceInterval]
    parts: list[PartWear] = Field(default_factory=list,
                                  description="Faqat `TIRES` va `BATTERY` tugunida")
    same_model_vehicles_with_component: int = Field(
        ..., description="Shu modeldagi BOSHQA mashinalardan shu tugunda ta'mirlangani")
    same_model_vehicles_with_repeat: int = Field(
        ..., description="Shulardan shu tugun takrorlangani")


class RecurrenceGroupAnalysis(BaseModel):
    component: str | None = None
    hypotheses: list[AdviceItem] = Field(..., description="Nega qaytyapti — asoslangan taxmin")
    check_points: list[AdviceItem]


class RecurrenceAnalysis(BaseModel):
    """MATN FAQAT LLM DAN; LLM javob bermasa 503. `source` ni kod tekshiradi."""

    groups: list[RecurrenceGroupAnalysis] = Field(..., description="Har takrorlangan tugunga")
    relabeled: int = 0
    disclaimer: str
    provider: str = "vllm"
    model: str | None = None
    prompt_version: str | None = None


class RecurrenceBasis(BaseModel):
    groups: int
    repairs: int
    text: str = Field(..., examples=["1 ta tugunda 2 ta ta'mir asosida"],
                      description="Kod yozgan jumla — LLM emas")


class VehicleRecurrence(BaseModel):
    vehicle_id: str
    plate_number: str | None = None
    outcome: Literal["REPEATS", "NO_REPEATS"] = Field(
        ..., description="`NO_REPEATS` — hech bir tugun takrorlanmagan; `analysis: null`, "
                         "LLM chaqirilmaydi")
    repairs_total: int = Field(..., description="Mashinaning hamma ta'mirlari (rad etilgan va "
                                                "bekor qilinganisiz)")
    repeats: list[RepeatGroup] = Field(default_factory=list)
    basis: RecurrenceBasis
    analysis: RecurrenceAnalysis | None = None
    generated_at: datetime
    elapsed_seconds: float = Field(0.0, description="BUTUN javob vaqti: baza + LLM")
    timings: dict[str, float] = Field(default_factory=dict)


class RepairEta(BaseModel):
    repair_id: str
    repair_number: str | None = None
    plate_number: str | None = None
    outcome: Literal["ESTIMATED", "NO_HISTORY", "LONGER_THAN_HISTORY"] = Field(
        ..., description="`NO_HISTORY` — o'xshash yopilgan ta'mir yo'q; "
                         "`LONGER_THAN_HISTORY` — naryad ularning har biridan uzoq turibdi. "
                         "Ikkalasida `estimate` va `analysis` — `null`")
    opened_at: datetime
    current_stage: CurrentStage
    estimate: Estimate | None = None
    basis: Basis
    similar_repairs: list[SimilarRepair] = Field(default_factory=list)
    plan: Plan | None = Field(None, description="Naryadda rejadagi tugash vaqti kiritilgan bo'lsa")
    analysis: EtaAnalysis | None = None
    generated_at: datetime
    elapsed_seconds: float = Field(0.0, description="BUTUN javob vaqti: baza + LLM")
    timings: dict[str, float] = Field(default_factory=dict, examples=[{"db": 1.2, "llm": 9.8}])
