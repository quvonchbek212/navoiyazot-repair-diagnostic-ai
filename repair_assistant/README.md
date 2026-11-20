# Ta'mir yordamchisi

Naryad va mashina bo'yicha LLM tavsiyalari: ta'mir muddatini taxminlash,
nosozlik bo'yicha tavsiya va takroriy nosozlik tahlili.

```
GET /repair-assistant/eta?repair_id=<vehicle_repair.id>
GET /repair-assistant/diagnosis?repair_id=<vehicle_repair.id>&lang=ru
GET /repair-assistant/recurrence?vehicle_id=<transport_vehicle.id>&component=BRAKES
```

## Kelishilgan qoidalar (30.10.2026)

1. Kodda o'ylab topilgan chegara yo'q. Javobda doim nechta o'xshash ta'mir
   asosida yozilgani ko'rsatiladi (`basis.text`, uni kod yozadi).
2. Tarix bo'lmasa javob buni ochiq aytadi.
3. O'xshash ta'mirlarni kod tanlaydi — eng mos K tasini. Butun tarix
   promptga solinmaydi.
4. Sonni kod hisoblaydi, LLM faqat izohlaydi.
5. Har vazifa — alohida endpoint.
6. Modul erkin matn (alomat) o'qiydi, shuning uchun FAQAT ichki vLLM'da
   ishlaydi: LLM so'rovi `llm.ask_internal` orqali ketadi, tashqi provayder
   yo'li yo'q.
7. LLM javob bermasa yoki bo'sh javob bersa — 503.

## `/eta` — mashina qachon tayyor bo'ladi

| Maydon | Nima |
|---|---|
| `outcome` | `ESTIMATED`, `NO_HISTORY` (o'xshash yopilgan ta'mir yo'q), `LONGER_THAN_HISTORY` (naryad har biridan uzoq turibdi) |
| `estimate` | `ready_from` / `ready_median` / `ready_to` va `remaining_hours`; taxmin yo'q bo'lsa `null` |
| `basis` | `similar_repairs`, `used`, `excluded_shorter`, `text` — "4 ta o'xshash ta'mir asosida" |
| `similar_repairs[]` | `repair_id`, `match` (nega tanlangan), `duration_hours`, `measured_from`, `used` |
| `current_stage` | ARM qabulini kutish / diagnostikani kutish / ta'mir — oxirgi yozilgan belgidan |
| `plan` | naryadda `estimated_completion_time` bo'lsa; `position` — oraliqqa nisbatan qayerda |
| `analysis` | LLM izohi, `model`, `prompt_version`; taxmin yo'q bo'lsa `null` |

Ochiq bo'lmagan naryad — 409, yo'q naryad — 404, `repair_id` UUID emas — 422.

### O'xshash ta'mir (`similar.py`)

- Nomzod — hozirgacha chiqqan remont. Naryadning o'zi, `REJECTED` va
  `CANCELLED` nomzod emas.
- O'xshash = bir xil tugun (`component_category`). `OTHER` tugunida alomat
  matnida umumiy so'z ham bo'lishi shart.
- Tartib: alomat matni mosligi, keyin bir xil model, keyin shu mashina,
  keyin yangirog'i. Eng mosi `RA_SIMILAR_TOP` (5) ta.
- Matn: `initial_diagnosis` + `defect_area`. So'zlar kichik harfga,
  apostroflar bittaga keltiriladi; biri ikkinchisining boshi bo'lsa ham mos
  ("shina" — "shinasi"). So'z og'irligi — IDF, bazadan hisoblanadi;
  stop-so'zlar ro'yxati yo'q.

Alomat qayerda (30.10.2026): `initial_diagnosis` 20 tadan 19 tasida, joy
nomi `defect_area` 19 tasida. `arm_diagnosis` — uning nusxasi,
`description` — 15 tasida "Nosozlik aniqlandi"; ular o'qilmaydi.

### Oraliq (`estimate.py`)

Oddiy medianadan farqi — naryadning hozirgi holati hisobga olinadi:

1. Har o'xshash ta'mirda naryadning oxirgi yozilgan belgisidan (ARM qabul
   qildi / diagnostika qilindi) chiqishgacha ketgan vaqt olinadi. U yerda
   bu belgi yozilmagan bo'lsa — ochilishdan, naryadning ochilganidan beri
   o'tgan vaqt bilan solishtiriladi (`measured_from`).
2. Naryad allaqachon uzoq turgan ta'mirlar olinmaydi (`used: false`).
3. Qolganlaridan: eng qisqa, mediana, eng uzun qolgan vaqt. Kvartil emas —
   tugunda yopilgan ta'mir 1–7 ta.

Ehtiyot qism omborda bor-yo'qligi hisobga olinmaydi: 30.10.2026 da qism
so'rovi ombor bilan bog'lanmagan (`item_id` bo'yicha 0/11, `stock_id`
0/11). Berilmagan qism faqat izohda aytiladi.

### Orqaga qarab sinash (31.10.2026)

`python -m repair_assistant.eval backtest` — har yopilgan naryad uchun
ochilgan payt va har belgi paytida "o'sha paytdagi tarix bilan nima degan
bo'lardik", keyin haqiqiy chiqish bilan solishtiriladi:

| Nuqta | Soni | Mediana xatosi, soat: taxmin | oddiy mediana (tugun, ochilishdan) |
|---|---|---|---|
| ochildi | 9 | 100.0 | 156.8 |
| ARM qabul qildi | 8 | 84.8 | 128.4 |
| diagnostika qilindi | 9 | 4.4 | 156.8 |
| hammasi | 26 | 70.6 | 156.8 |

47 nuqtadan 26 tasida taxmin chiqdi (qolganida o'xshash tarix yo'q).
Haqiqiy chiqish oraliqqa 5/26 da tushdi: o'xshash ta'mir 1–5 ta, eng
qisqa–eng uzun oraliq bunday kam namunada tor. Diagnostikadagi katta farq
bazadagi odatdan: ko'p naryadda diagnostika vaqti chiqishdan bir necha
daqiqa oldin yoziladi — hisob buni tarixdan o'zi ko'radi.

### LLM izohi

Izohga alomat matni bormaydi — faqat tugun, "o'xshashlik" sababi, qolgan
vaqt, berilmagan qism, tezroq tugaganlar soni va reja. 31.10.2026 da
(vLLM, gemma4-31b, 5 holat × 3 marta) alomat berilganda model xom matnni
izohga ko'chirdi, rus tilida esa o'zbekcha matnni rus jumlasi ichiga
qo'ydi. "Naryad alomati qaysi ta'mirlarga yaqin" degan band 15 javobdan
6 tasida xato xulosa berdi. Hozirgi prompt bilan uz va ru da 30 javobning
birortasida faktlarda yo'q son ham, xom matn ham chiqmadi. Batafsil —
`explain.py`, `ETA_PROMPT` izohi.

## `/diagnosis` — nosozlik bo'yicha tavsiya

Mexanik yozgan alomat (`initial_diagnosis`, `defect_area`) bo'yicha 1–3
ehtimoliy sabab va 2–4 tekshiriladigan joy. Yakuniy qarorni mexanik qiladi
(`analysis.disclaimer`).

| Maydon | Nima |
|---|---|
| `outcome` | `ADVISED`; `NO_SYMPTOM` — alomat ham, joy ham yozilmagan, LLM chaqirilmaydi |
| `basis` | `similar_repairs`, `with_outcome` (nima qilingani yozilgani), `text` |
| `similar_repairs[]` | `repair_id`, `match`, `has_outcome`, `came_back_days`, `days_before_target` |
| `analysis.likely_causes[]`, `check_points[]` | `text`, `source` (`history` / `general_knowledge`), `repair_ids` |
| `analysis.relabeled` | LLM "tarix" degan, lekin kod tasdiqlamagan bandlar soni |

O'xshash ta'mirlar `/eta` dagi bilan bir xil tanlanadi. Ulardan LLM ga
boradi: alomat, nima qilingani (ish bandlari va `work_performed`), so'ralgan
qism, mashina keyin shu tugun bilan qaytganmi, shu mashinada bu naryaddan
qancha oldin bo'lgan. Alomat va ish matni javobga chiqmaydi.

**Shablon tashlanadi.** Bitta matn bir nechta naryadda so'zma-so'z takrorlansa
u hech narsa aytmaydi: 31.10.2026 da "Barcha ta'mirlash ishlari to'liq va
sifatli bajarildi..." `work_performed` 16 tadan 7 tasida. Qoida bazadan
o'lchanadi, faqat shu paytgacha yopilgan naryadlardan.

**`history` ni kod tekshiradi.** Band nima qilingani (ish, qism, qaytish)
yozilgan o'xshash ta'mirga tayanmasa — `general_knowledge` ga tushadi.
Tarix bo'lmasa `basis.text` buni ochiq aytadi: "tavsiya umumiy bilimdan,
tarixdan emas".

**Qism naryadga mos kelmasligi mumkin.** 31.10.2026 da qism so'ralgan 9 ta
yopilgan naryaddan 6 tasida qism tugunga aloqasiz: shina ta'mirida KAMAZ
tormoz kolodkasi, tormozda akkumulyator yoki generator. Kod buni ajrata
olmaydi; promptda qoida bor va o'lchovda model bunday qismni 0 marta tilga
oldi.

**Prompt o'lchovi (31.10.2026, vLLM, 7 naryad × 3 marta)** — batafsil
`explain.py`, `DIAGNOSIS_PROMPT` izohida. Birinchi versiyada "tarix" bandlarining
6/21 tasi o'xshash ta'mirning alomatidan olingan edi. Hozirgisida "tarix" faqat
o'sha ta'mirda qilingan ish va qaytishga tayanadi. Shu mashina yaqinda shu
tugunda ta'mirlangan bo'lsa, "oldingi ish nosozlikni bartaraf etmagan bo'lishi
mumkin" 3/3 da aytiladi. To'qilgan son va matnga tushgan kod 0. Model imlo
xatosini tushunmadi: "balonlari tishildi" (teshildi) — "tishlanish, yeyilish".

**Vaqt.** Bitta so'rov 33–40 s (~300 token JSON); muhlat
`RA_DIAGNOSIS_TIMEOUT_SECONDS` (90).

## `/recurrence` — mashina nega bir xil tugun bilan qaytyapti

Takror — bitta mashinada bir xil tugun bo'yicha 2 va undan ko'p ta'mir
(rad etilgan va bekor qilinganisiz). Vaqt chegarasi yo'q: "30 kun ichida"
degan raqam bazadan chiqmaydi, oraliq kunlarda beriladi. `OTHER` tugunida
alomat matnida umumiy so'z ham shart. `component` berilsa — faqat shu tugun.

| Maydon | Nima |
|---|---|
| `outcome` | `REPEATS`; `NO_REPEATS` — LLM chaqirilmaydi |
| `repeats[]` | tugun, `repairs[]` (eski -> yangi), `intervals[]`, `parts[]`, shu modeldagi boshqa mashinalar |
| `intervals[]` | `days`, `overlap`, `trips` (`waybill`), `inspections_passed` (texnik ko'rikdan "soz" deb o'tgani) |
| `parts[]` | faqat `TIRES` (shina, probeg bo'yicha) va `BATTERY` (akkumulyator, oy bo'yicha) tugunida: `used_pct` |
| `analysis.groups[]` | har tugunga `hypotheses[]` va `check_points[]`, har bandda `source` |

**Har tugun — alohida so'rov.** 31.10.2026 da ikki tugun bitta promptda
berilganda model 3/3 da faqat birinchisini tahlil qildi.

**Eng qimmatli fakt — oraliq.** 85312EBA tormoz ta'miridan (29.08) keyin 2
reys va 3 ta texnik ko'rikdan "soz" deb o'tib, 3.6 kunda yana tormoz bilan
qaytgan. Birinchi promptda model buni 9/9 da e'tiborsiz qoldirdi; shartli
band bilan — 9/9 da "ko'rik nosozlikni aniqlamagan yoki u keyin paydo bo'lgan
bo'lishi mumkin". O'lchov batafsil — `explain.py`, `RECURRENCE_PROMPT` izohida.

**Haqiqiy takror bazada bitta** (31.10.2026, 85312EBA, tormoz). Shina
eskirishi bandi sun'iy holatda sinaldi: ikki mashinaning shina ta'miri bitta
mashinaga ko'chirildi (`eval.py recurrence`). 85471LBA bir kunda ikki naryad
bilan kelgan, lekin tugunlari boshqa (`OTHER` "balonlari tishildi" va `TIRES`
"shina teshildi"), matnda umumiy so'z yo'q — takror emas.

**Tuzalmagan:** o'zbek tilida tekshiruv bandida model "sizib chiqish" o'rniga
"srazini" yoki turkcha "sızıntısını" yozadi (8/9).

**Vaqt.** Bitta tugun 30–36 s; bir nechta tugun parallel so'raladi.

## Jurnal

Har muvaffaqiyatli javob suhbat tarixi serveridagi (`CHAT_DB_*`)
`repair_assistant_log` jadvaliga yoziladi: endpoint, naryad, til, prompt
versiyasi, model va butun javob. Jadval `CHAT_DB_AUTO_CREATE` yoqiq bo'lsa
o'zi yaratiladi. Yozish javob yuborilgandan keyin fonda bo'ladi va xatosi
javobni buzmaydi. O'chirish: `RA_LOG=off`.

Keyin `repair_id` bo'yicha ATIL bilan solishtiriladi: muddat — haqiqiy
chiqish vaqti bilan; tavsiya — naryadda aslida qilingan ish va qism bilan
(`python -m repair_assistant.eval diagnosis` shunday yonma-yon chiqaradi).

## Sozlamalar

```
RA_SIMILAR_TOP=5        # nechta o'xshash ta'mir: hisobga ham, promptga ham
RA_LLM_MAX_TOKENS=320
RA_LLM_TIMEOUT_SECONDS=60
RA_DIAGNOSIS_MAX_TOKENS=640
RA_DIAGNOSIS_TIMEOUT_SECONDS=90
RA_MAX_ROWS=20000       # eng yangi naryadlar o'qiladi
RA_LOG=on
```

## Fayllar

```
config.py    sozlamalar
queries.py   faqat SELECT; erkin matn faqat FREE_TEXT_COLUMNS va ish bandlari, ism yo'q
similar.py   o'xshash ta'mirni tanlash
estimate.py  muddat oralig'i
diagnosis.py tavsiya faktlari: o'xshash ta'mirda nima qilingani, shablon, qaytish
recurrence.py takrorlar: oraliqdagi reys va ko'rik, shina/akkumulyator eskirishi
common.py    chiqish vaqti, statuslar, qism kutish, davomiylik matni
explain.py   prompt
llm.py       LLM chaqiruvi; faqat ichki vLLM
texts.py     uch tildagi matnlar ("N ta o'xshash ta'mir asosida")
models.py    javob sxemasi
service.py   bazadan o'qish + hisob; 404 / 409
router.py    endpointlar
log.py       javoblar jurnali
eval.py      orqaga qarab sinash va promptlarni vLLM'da N marta ishga tushirish
```

Testlar: `tests/test_repair_assistant.py` — baza ham, model ham kerak emas.
