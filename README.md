# Navoiyazot Logistics · Repair Assistant API

Intelligent repair duration forecasting (ETA) and diagnostic guidance system built for the central repair workshops of the **Navoiyazot industrial chemical complex**.

---

## Key Capabilities

* **Statistical Repair ETA**: Predicts realistic completion timestamps based on historical work orders for identical defects and vehicle models.
* **Component-Level Diagnostic Checklists**: Provides mechanics with structured, step-by-step diagnostic checklists tailored to the reported defect category (Brakes, Engine, Chassis, Electrical, Tires, Battery).
* **Defect Recurrence Analysis**: Identifies repeated failures within short operational cycles, highlighting potential root-cause misdiagnoses.
* **Historical Repair Matching**: Ranks past similar repairs to reveal parts consumed and successful corrective procedures.

---

## Tech Stack

* **Language**: Python 3.12+
* **Framework**: FastAPI / Pydantic v2
* **Algorithms**: Similar repair TF-IDF ranking, median duration estimators
* **Database Driver**: Psycopg2-binary (PostgreSQL)

---

## Core Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/repair-assistant/eta` | Calculate predicted completion ETA and remaining hours for open repair |
| `GET` | `/repair-assistant/diagnosis` | Retrieve diagnostic recommendations and structured inspection checklist |
| `GET` | `/repair-assistant/recurrence` | Analyze repeat breakdown history for specific vehicle and component |
| `GET` | `/healthz` | Service health status |

---

## Quick Start

### 1. Installation
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configuration
```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=atil_navoiyazot
DB_USER=postgres
DB_PASSWORD=your_password
```

### 3. Run Service
```bash
python main.py
# Server runs on http://localhost:8004 (Docs: http://localhost:8004/docs)
```
