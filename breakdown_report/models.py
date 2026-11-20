"""Javob sxemasi — Swagger shu modellardan chiziladi.

`null` NOL EMAS: `trips: null` — "reys ma'lumoti yo'q" (`trip` bo'sh),
`trips: 0` — "yozuvlar bor, bu mashina reys qilmagan". `trips_per_breakdown`
reys noma'lum yoki nol bo'lsa `null`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class VehicleRef(BaseModel):
    id: str
    plate_number: str | None = Field(None, examples=["85312EBA"])
    brand: str | None = Field(None, examples=["Chevrolet"])
    model: str | None = Field(None, examples=["Damas"])
    transport_type: str | None = Field(None, examples=["PASSENGER_CAR"])
    transport_type_name: str | None = Field(None, examples=["yengil avtomobil"])
    usage_mode: str | None = Field(None, description="KM / MOTOSOAT / KM_AND_MOTOSOAT")
    current_status: str | None = None
    release_year: int | None = Field(None, description="`transport_vehicle.release_date` yili")
    age_years: int | None = Field(None, description="Davr oxiriga (yoki bugunga) yoshi, yil")


class PartUsed(BaseModel):
    item_name: str | None = None
    status: str | None = None
    quantity: float | None = None
    unit: str | None = None


class RepairItem(BaseModel):
    id: str
    repair_number: str | None = Field(None, examples=["ARM-20260902-0011"])
    occurred_at: datetime | None = Field(None, description="Aniqlangan vaqt (`detected_at`)")
    status: str | None = None
    is_open: bool = False
    counted: bool = Field(
        True, description="Buzilish sifatida sanaldimi. Rad etilgan/bekor qilingan — `false`")
    component: str | None = Field(None, examples=["BRAKES"])
    component_name: str | None = Field(None, examples=["tormoz tizimi"])
    context: str | None = Field(None, examples=["IN_TRIP"])
    context_name: str | None = Field(None, examples=["reys vaqtida"])
    defect_area: str | None = None
    defect_reason: str | None = None
    work_performed: str | None = None
    driver_name: str | None = None
    trips_before: int | None = Field(
        None,
        description="Davr boshidan shu buzilishgacha yakunlangan reyslar. ERTALIK O'LCHOVI "
                    "EMAS: kuzatuv boshida buzilgan mashinada doim kichik bo'ladi")
    trips_since_previous: int | None = Field(
        None, description="Oldingi buzilishdan keyin necha reysda yana buzildi")
    downtime_hours: float | None = Field(
        None, description="Ta'mirda turgan soat: bazadagi qiymat, bo'lmasa aniqlangan -> ta'mirlangan")
    estimated_cost: float | None = None
    parts: list[PartUsed] = Field(default_factory=list)


class Signal(BaseModel):
    """O'lchangan fakt — sabab haqida xulosa emas, dalil."""

    code: str = Field(..., examples=["EARLY_FAILURE"])
    text: str


class CodeCount(BaseModel):
    code: str | None = None
    name: str
    count: int
    share: float | None = Field(None, description="Jami buzilishdagi ulushi (0..1)")


class PeerGroup(BaseModel):
    """Solishtirish guruhidagi BUZILMAGAN FAOL mashinalar."""

    kind: Literal["model", "transport_type"]
    name: str = Field(..., examples=["Chevrolet Damas"])
    healthy_vehicles: int
    median_release_year: float | None = None
    median_trips: float | None = None
    median_drivers: float | None = None


class PredictiveRisk(BaseModel):
    risk_level: Literal["HIGH", "MEDIUM", "LOW"]
    score: int
    factors: list[str] = Field(default_factory=list)
    recommendation: str


class VehicleStat(BaseModel):
    rank: int
    vehicle: VehicleRef
    breakdowns: int = Field(..., description="Sanalgan buzilishlar")
    repairs_excluded: int = Field(0, description="Rad etilgan/bekor qilingan so'rovlar")
    breakdowns_open: int = 0
    trips: int | None = Field(None, description="Davrdagi yakunlangan reyslar")
    drivers: int | None = Field(None, description="Davrda haydagan turli haydovchilar")
    engine_hours: float | None = Field(
        None,
        description="Yo'l varaqasidagi motosoat yig'indisi. FAQAT `usage_mode` MOTOSOAT yoki "
                    "KM_AND_MOTOSOAT bo'lsa; km bilan ishlaydigan mashinada `null`")
    trips_per_breakdown: float | None = Field(
        None, description="Necha reysga bitta buzilish (kattasi yaxshi)")
    first_breakdown_after_trips: int | None = None
    avg_downtime_hours: float | None = None
    repair_cost: float | None = None
    last_breakdown_at: datetime | None = None
    components: list[CodeCount] = Field(default_factory=list)
    peer_group: PeerGroup | None = Field(
        None, description="Kim bilan solishtirildi: bir xil model, bo'lmasa bir xil tur")
    signals: list[Signal] = Field(default_factory=list)
    repairs: list[RepairItem] = Field(default_factory=list)
    predictive_risk: PredictiveRisk | None = None


class GroupStat(BaseModel):
    key: str
    name: str
    vehicles: int
    vehicles_active: int | None = None
    vehicles_broken: int
    breakdowns: int
    trips: int | None = None
    trips_per_breakdown: float | None = None


class CohortMember(BaseModel):
    vehicle_id: str
    plate_number: str | None = None
    breakdowns: int
    release_year: int | None = None
    trips: int | None = None
    drivers: int | None = None
    first_breakdown_after_trips: int | None = None
    early: bool | None = Field(
        None,
        description="Hayotida erta buzildimi: chiqarilgan yili buzilmagan guruhdoshlarining "
                    "medianasidan yangi. Yil noma'lum yoki sog'lom guruhdosh yo'q bo'lsa `null`")


class Cohort(BaseModel):
    """Bir xil modeldagi mashinalar: nega aynan shular buzildi."""

    model: str = Field(..., examples=["Chevrolet Damas"])
    transport_types: list[str] = Field(default_factory=list)
    vehicles: int
    vehicles_active: int | None = None
    vehicles_broken: int
    breakdowns: int
    healthy: PeerGroup | None = None
    broken: list[CohortMember] = Field(default_factory=list)


class DriverStat(BaseModel):
    driver_id: str | None = None
    full_name: str | None = None
    breakdowns: int
    vehicles: list[str] = Field(default_factory=list)
    trips: int | None = None
    trips_per_breakdown: float | None = None


class Summary(BaseModel):
    vehicles_total: int
    vehicles_active: int | None = Field(None, description="Davrda reys qilganlar")
    vehicles_broken: int
    vehicles_no_activity: int | None = Field(
        None, description="Reys ham, buzilish ham yo'q — ishonchli EMAS, ma'lumot yo'q")
    breakdowns_total: int
    breakdowns_open: int
    repairs_excluded: int
    trips_total: int | None = None
    trips_per_breakdown: float | None = None
    avg_downtime_hours: float | None = None
    downtime_measured: int = Field(0, description="Turib qolish vaqti o'lchangan buzilishlar")
    by_component: list[CodeCount] = Field(default_factory=list)
    by_context: list[CodeCount] = Field(default_factory=list)
    by_transport_type: list[GroupStat] = Field(default_factory=list)
    by_brand: list[GroupStat] = Field(default_factory=list)
    by_model: list[GroupStat] = Field(default_factory=list)


class VehicleCause(BaseModel):
    plate_number: str
    likely_causes: str


class Analysis(BaseModel):
    """"Nega" degan savolga javob — MATN FAQAT LLM DAN.

    Raqamlarni ARIFMETIKA hisoblaydi; LLM faktlarni bog'lab ehtimoliy
    sabab va tavsiya yozadi. LLM javob bermasa endpoint 503 qaytaradi.
    Bo'sh bo'lishi mumkin bo'lgan yagona holat — davrda buzilish yo'qligi.
    """

    overview: str = ""
    vehicles: list[VehicleCause] = Field(
        default_factory=list,
        description="`most_broken` dagi birinchi `vehicles_considered` ta mashina, o'sha tartibda")
    recommendations: list[str] = Field(default_factory=list)
    vehicles_considered: int = Field(
        0, description="Nechta mashinaga sabab yozildi (`BR_LLM_ANALYZE_TOP`)")


class Period(BaseModel):
    date_from: date | None = Field(None, description="`null` — bazaning boshidan")
    date_to: date | None = Field(None, description="`null` — bugungacha")
    first_breakdown_at: datetime | None = None
    last_breakdown_at: datetime | None = None


class Filters(BaseModel):
    transport_type: str | None = None


class DataQuality(BaseModel):
    row_counts: dict[str, int] = Field(default_factory=dict)
    factors_unchecked: list[str] = Field(
        default_factory=list, description="Jadvali bo'sh bo'lgani uchun tekshirilmagan sabablar")
    notes: list[str] = Field(default_factory=list)


class BreakdownReport(BaseModel):
    generated_at: datetime
    period: Period
    filters: Filters
    summary: Summary
    analysis: Analysis = Field(default_factory=Analysis)
    most_broken: list[VehicleStat] = Field(default_factory=list)
    least_broken: list[VehicleStat] = Field(
        default_factory=list, description="Ko'p ishlab kam buzilganlar; reysi yo'qlar KIRMAYDI")
    no_activity: list[VehicleRef] = Field(
        default_factory=list, description="Davrda reys ham, buzilish ham yo'q")
    cohorts: list[Cohort] = Field(default_factory=list)
    drivers: list[DriverStat] = Field(default_factory=list)
    data_quality: DataQuality
    elapsed_seconds: float = Field(0.0, description="BUTUN javob vaqti: baza + LLM")
    timings: dict[str, float] = Field(
        default_factory=dict,
        description="Qism bo'yicha vaqt: `db` — bazadan o'qish va hisob, `llm` — tahlil "
                    "(buzilish bo'lmasa LLM chaqirilmaydi va u ~0)",
        examples=[{"db": 0.8, "llm": 21.6}],
    )
