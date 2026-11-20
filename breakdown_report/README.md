# Buzilish hisoboti

Qaysi transport **ko'p** buzilyapti, qaysi biri **kam** va **nega**.

```
GET /breakdown-report/scan
GET /breakdown-report/scan?date_from=2026-08-01&date_to=2026-08-31&transport_type=PASSENGER_CAR
```

## Javobda nima bor

| Bo'lim | Nima |
|---|---|
| `summary` | jami mashina, buzilish, reys; tizim (tormoz, motor...), aniqlangan payt, tur, marka va model bo'yicha taqsimot |
| `most_broken` | eng ko'p buzilganlar — har biri ta'mirlar ro'yxati va o'lchangan faktlar (`signals`) bilan |
| `least_broken` | **ko'p ishlab** kam buzilganlar |
| `no_activity` | davrda reys ham, buzilish ham yo'q — bu "ishonchli" emas, "ma'lumot yo'q" |
| `cohorts` | bir xil modeldagi mashinalar: buzilganlari buzilmaganlari bilan solishtirilgan |
| `drivers` | buzilishlarda rulda bo'lgan haydovchilar va ularning buzilish tezligi |
| `analysis` | LLM: umumiy xulosa, eng ko'p buzilgan 5 mashinaga ehtimoliy sabab, tavsiyalar |
| `data_quality` | jadvallar hajmi, tekshirilmagan sabablar, ma'lumot sifati izohlari |

## Qoidalar

### 1. Chegara yo'q — solishtirish bor

Kodda "oyiga 3 martadan ko'p" yoki "5 reysdan oldin buzilsa erta" degan son
**yo'q**. Mashina guruhdoshlari bilan solishtiriladi:

* **ko'p buziladi** — buzilishlar soni bo'yicha ro'yxatda yuqorida (teng
  bo'lsa — necha reysga bitta buzilish kam bo'lgani oldinda);
* **erta buzildi** (`cohorts[].broken[].early`, `NEWER_THAN_PEERS`) —
  hayotida erta: chiqarilgan yili bir xil modeldagi **buzilmagan faol**
  mashinalarnikidan (mediana) yangi bo'lsa ham buzilgan;
* **tez qayta buzildi** (`REPEAT_BREAKDOWN`) — oldingi ta'mirdan keyin necha
  reysda yana buzilgan;
* "davr boshidan buzilishgacha necha reys" (`trips_before`) ertalik o'lchovi
  **emas**: reys yozuvlari 19.08.2026 dan boshlangan, o'sha kuni buzilgan
  mashinada u doim 0. U faqat ko'rsatiladi va LLM ga yuborilmaydi;
* **solishtirish guruhi** — avval bir xil model (marka + model); unda
  buzilmagan faol mashina bo'lmasa bir xil transport turi.

### 2. Ish hajmi — reys, km emas

Bazadagi km kiritish xatolariga to'la (14.09.2026: reysda 574 596 km, yo'l
varaqasida 2 499 956 km). Ish hajmi — yakunlangan reyslar soni
(`count(distinct route_id)`). Km javobda **umuman yo'q**: "faqat ma'lumot
uchun" ko'rsatilganda 162 ta tekshiruv so'rovining 72 holatida reysiga
5000 km dan oshib, chalg'itdi.

Motosoat (`engine_hours`) faqat `usage_mode` = `MOTOSOAT` /
`KM_AND_MOTOSOAT` mashinalarda: km bilan ishlaydigan avtobuslarning yo'l
varaqasida test qiymati ("5") turibdi.

### 3. Noma'lum — nol emas

* `trip` bo'sh bo'lsa `trips: null`, 0 emas — va "kam buzilayotganlar"
  reytingi tuzilmaydi;
* reysi yo'q, buzilmagan mashina `least_broken` ga emas, `no_activity` ga
  tushadi;
* sabab jadvali bo'sh bo'lsa u `factors_unchecked` da turadi va LLM
  "tekshirib bo'lmadi" deydi, "sabab yo'q" demaydi.

### 4. Rad etilgan so'rov — buzilish emas

`REJECTED` va `CANCELLED` ta'mirlar ro'yxatda `counted: false` bo'lib
ko'rinadi, lekin sanalmaydi.

## Jadvallar

| Jadval | 14.09.2026 | Vazifasi |
|---|---|---|
| `vehicle_repair` | 11 | buzilish: tizim, vaqt, haydovchi, ta'mir |
| `transport_vehicle` | 128 | model guruhi, chiqarilgan yil, tur |
| `trip` | 747 yakunlangan | ish hajmi, haydovchilar, buzilishgacha reys |
| `waybill` | 1363 | motosoat |
| `repair_order_part_request` | 5 | ishlatilgan ehtiyot qism |
| `driver` | 206 | haydovchi ismi |
| `speed_violation` | **0** | fakt: `SPEEDING` |
| `incident` | **0** | fakt: `HARSH_DRIVING` |
| `vehicle_accident` | **0** | fakt: `ACCIDENT` |
| `maintenance_plan` | **0** | fakt: `MAINTENANCE_OVERDUE` |
| `vehicle_part` | **0** | fakt: `PART_PAST_LIFE` (resurs muddati bazadan) |

Bo'sh jadvallar kod yo'li `tests/test_breakdown_report.py` da sintetik
ma'lumot bilan sinalgan — to'lganda o'zgartirish kerak emas.

**Ataylab o'qilmaydi:** `vehicle_technical_inspection` dagi `BLOCKED`
ko'riklar. 14.09.2026 da 153 ta edi, lekin izohida "soz", bir mashinada
soniyalar ichida BLOCKED/FIT almashadi, `inspected_at` 1970 yil va
ta'mirlarga bog'lanmaydi (11 dan 1). Sababi `queries.py` boshida.

## Faktlar (`signals[].code`)

| Kod | Nima o'lchanadi |
|---|---|
| `OLDER_THAN_PEERS` / `NEWER_THAN_PEERS` | chiqarilgan yili buzilmagan guruhdoshlarnikidan farqi |
| `MORE_TRIPS_THAN_PEERS` / `FEWER_TRIPS_THAN_PEERS` | davrdagi reys guruhdoshlarnikidan farqi |
| `MORE_DRIVERS_THAN_PEERS` | turli haydovchilar soni guruhdoshlarnikidan ko'p |
| `REPEATED_COMPONENT` | bitta tizim bir necha marta |
| `REPEAT_BREAKDOWN` | oldingi ta'mirdan keyin necha reysda yana buzildi |
| `SAME_DRIVER` | bir necha buzilishda rulda bitta haydovchi |
| `DRIVER_HIGH_RATE` | haydovchida 2+ buzilish va reys/buzilish nisbati butun parknikidan yomon (bitta hodisa tasodifdan farq qilmaydi) |
| `REWORK` | ta'mir qayta ishlangan yoki mexanik qayta tekshiruvidan o'tmagan |
| `NO_TRIPS_RECORDED` | buzilgan, lekin reys yozuvi yo'q — ish hajmi noma'lum |
| `SPEEDING`, `HARSH_DRIVING`, `ACCIDENT`, `MAINTENANCE_OVERDUE`, `PART_PAST_LIFE` | sabab jadvallaridan |

Fakt — **dalil**, sabab emas. Ularni bog'lab "nega" degan savolga javobni
LLM yozadi (`analysis.vehicles[].likely_causes`) va uni taxmin sifatida
aytadi.

## LLM

**Maqsad — javob 30 s ichida.** vLLM sekundiga 6.8 token yozadi, ya'ni
bitta so'rovda butun park tahlili 168 s olardi. Shuning uchun tahlil
**2 + N parallel qisqa so'rov**: umumiy xulosa, tavsiyalar va eng ko'p
buzilgan N (sukut 5) mashinaning har biriga sabab. vLLM ularni birga
dekodlaydi, javob vaqti eng uzun so'rovga teng.

| 14.09.2026 o'lchovi | Vaqt |
|---|---|
| bitta so'rov, butun park | 168 s |
| parallel, 1 mashina | 18 s |
| parallel, butun park, top 5 | 20 s |
| parallel, butun park, top 9 | 33 s |

Promptga **yuborilmaydi**: km (ishonchsiz), davr boshidan buzilishgacha
reys (kuzatuv artefakti), ehtiyot qismlar (prototipda LLM akkumulyatorni
tormozga bog'lagan). Prompt tekshirilmagan sababni taxmin qilishni va
haydovchini aybdor deb yozishni taqiqlaydi.

Bitta so'rov yiqilsa ham — 503 (yarim tahlil yo'q, shablonga tushish yo'q).
Davrda buzilish bo'lmasa LLM chaqirilmaydi va `analysis` bo'sh qaytadi.

Sozlamalar: `BR_LLM_ANALYZE_TOP`, `BR_LLM_MAX_TOKENS`, `BR_LLM_TIMEOUT_SECONDS`
(`.env.example`).
