# Metrology Intelligence Platform (MIP)

Calibration QC pipeline for analytical instruments (XRF, HPLC, balance) following a **Bronze → Silver → Gold Medallion architecture** with Airflow orchestration, dbt transformations, and uncertainty quantification via a dedicated **UQaaS microservice** (GUM Supplement 1 / CIPM-2007 Monte Carlo).

Designed to demonstrate the intersection of metrological expertise (ISO 17025 / GUM) and modern data engineering patterns (Medallion, Airflow, dbt, microservices).

---

## Background

The **Guide to the Expression of Uncertainty in Measurement (GUM)** defines the standard framework for analytical instrument QC. Two complementary quality controls are implemented here:

| Control | Standard | Implementation |
|---|---|---|
| **Levey-Jennings charts** | ISO 17511 / Westgard (1981) | SQL window functions in Gold dbt model |
| **Uncertainty budget** | GUM §5 / GUM Supl. 1 | UQaaS microservice via HTTP (Monte Carlo) |

Westgard rules implemented: **1₃s** (reject), **2₂s** (reject), **R₄s** (reject), **4₁s** (warning), **10ₓ** (warning).

---

## Architecture

```
                         ┌──────────────────────────────────────┐
                         │         Apache Airflow  :8081        │
                         │                                      │
                         │  ingest_calibration (07:00 UTC)      │
                         │    └─▶ transform_pipeline (07:30)    │
                         │          └─▶ uncertainty_enrichment  │
                         └──────────────┬───────────────────────┘
                                        │
              ┌─────────────────────────▼──────────────────────────┐
              │                  PostgreSQL  :5436                  │
              │                                                     │
              │  BRONZE          raw_calibration                    │
              │  (dbt view)      ↓ instrument_id · reading · JSONB │
              │                                                     │
              │  SILVER          stg_xrf · stg_hplc · stg_balances │
              │  (dbt views)     z_score · laplace_b · rsd_pct     │
              │                                                     │
              │  GOLD            fact_control_charts (Westgard SQL) │
              │  (dbt tables)    fact_calibration_status            │
              │                  fact_uncertainty  ←── UQaaS join  │
              │                  dim_instruments                    │
              │                                                     │
              │  EXTERNAL        calibration_uncertainty (Airflow)  │
              └────────────────────────────┬────────────────────────┘
                                           │ LEFT JOIN
                           ┌───────────────▼──────────┐
                           │   UQaaS  :8003            │
                           │   POST /calculate/        │
                           │   GUM Supl. 1 Monte Carlo │
                           │   (separate microservice) │
                           └───────────────────────────┘
                                           │
                           ┌───────────────▼──────────┐
                           │   MIP API  :8004          │
                           │   GET /calibration/       │
                           │   GET /calibration/{id}   │
                           │   GET /calibration/chart  │
                           │   GET /alerts/            │
                           │   GET /alerts/summary     │
                           └───────────────┬───────────┘
                                           │
                           ┌───────────────▼──────────┐
                           │   Dashboard  :8502        │
                           │   Streamlit + Plotly      │
                           │   Overview · Levey-Jennings│
                           │   Alerts · Uncertainty    │
                           └───────────────────────────┘
```

### Daily pipeline chain

```
07:00  ingest_calibration      Bronze: synthetic XRF/HPLC/Balance data → raw_calibration
07:30  transform_pipeline      dbt run (Silver + Gold) → dbt test (37 tests)
                                └─▶ trigger uncertainty_enrichment
08:00  uncertainty_enrichment  calls UQaaS /calculate/ × 5 → calibration_uncertainty
```

---

## Directory layout

```
metrology-intelligence-platform/
├── core/
│   ├── synthetic_data.py       # XRF (drift + outliers), HPLC (curve), Balance (Laplace)
│   └── control_charts.py       # Westgard rules (Python) + annotate_dataframe
├── dags/
│   ├── ingest_calibration.py   # Bronze: generate → upsert raw_calibration (idempotent)
│   ├── transform_pipeline.py   # dbt run → dbt test → trigger uncertainty_enrichment
│   └── uncertainty_enrichment.py # calls UQaaS, upserts calibration_uncertainty
├── dbt/
│   ├── dbt_project.yml
│   └── models/
│       ├── bronze/
│       │   ├── sources.yml
│       │   └── raw_calibration.sql        # view + measurement_date
│       ├── silver/
│       │   ├── stg_xrf.sql                # z_score, batch stats, rel_deviation
│       │   ├── stg_hplc.sql               # rsd_pct, level stats, R² input
│       │   └── stg_balances.sql           # MAD, Laplace b=MAD/ln(2), u_rep
│       └── gold/
│           ├── fact_control_charts.sql    # Westgard 1₃s/2₂s/R₄s/4₁s/10ₓ in SQL
│           ├── fact_calibration_status.sql # QC status per instrument/batch
│           ├── fact_uncertainty.sql        # JOIN with UQaaS results
│           └── dim_instruments.sql
├── api/
│   ├── main.py
│   ├── db.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── routers/
│       ├── calibration.py      # GET /calibration/, /{id}, /{id}/chart
│       └── alerts.py           # GET /alerts/, /alerts/summary
├── dashboard/
│   ├── app.py                  # Streamlit: Overview/Levey-Jennings/Alerts/Uncertainty
│   ├── Dockerfile
│   └── requirements.txt
├── docker/
│   └── init-db/
│       ├── 01_schema.sql       # raw_calibration Bronze table
│       └── 02_uncertainty.sql  # calibration_uncertainty (UQaaS results)
├── tests/
│   ├── test_synthetic_data.py  # 21 unit tests — XRF/HPLC/Balance generators
│   ├── test_control_charts.py  # 23 unit tests — each Westgard rule in isolation
│   └── smoke_api.py            # 6 endpoint assertions (health, calibration, alerts)
├── airflow/
│   ├── Dockerfile              # apache/airflow:2.8.1 + dbt + numpy/pandas/scipy
│   └── dbt_profiles/profiles.yml
├── requirements-dev.txt
└── docker-compose.yml
```

---

## Instruments and data model

| Instrument | Error model | Key statistic | u formula |
|---|---|---|---|
| **XRF** | Normal (Type A) | batch SD / √n | u = SD/√n |
| **Balance** | Laplace (robust) | MAD / ln(2) = b | u_rep = b√2 |
| **HPLC** | Normal (linearity) | peak area SD | u = SD (level) |

Balance uses a **Laplace error model** (robust to vibration-induced shock errors), estimated via `b = MAD/ln(2)`.

**Robust Levey-Jennings limits:** the XRF z-score uses `σ = 1.4826·MAD` (median absolute deviation), not the sample `STDDEV`. The sample SD is inflated by the very 3–5σ outliers the control chart is meant to catch, masking them so no Westgard rule fires. The MAD-based scale is insensitive to a minority of outliers, so genuine spikes and systematic drift correctly trigger `1₃s`/`2₂s`.

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/calibration/` | All instruments — latest QC status + uncertainty (filter by type/status) |
| `GET` | `/calibration/{id}` | Full detail for one instrument: u_combined, U(k=2), dominant Westgard rule |
| `GET` | `/calibration/{id}/chart?element=Fe` | Levey-Jennings data: 30 points with z_score + violation_rule |
| `GET` | `/alerts/` | Instruments not in_control, ordered by severity |
| `GET` | `/alerts/summary` | Counts by severity, instrument type, Westgard rule |

Interactive docs: **http://localhost:8004/docs**

---

## dbt models — 37 data tests

| Layer | Model | Materialization | Key tests |
|---|---|---|---|
| Bronze | `raw_calibration` | View | unique id, not_null, accepted_values instrument_type |
| Silver | `stg_xrf` | View | unique id, not_null element/reading/batch_mean |
| Silver | `stg_hplc` | View | unique id, not_null analyte/rsd_pct |
| Silver | `stg_balances` | View | unique id, not_null laplace_b/u_rep_g |
| Gold | `fact_control_charts` | Table | unique id, accepted_values qc_status |
| Gold | `fact_calibration_status` | Table | not_null calibration_status, accepted_values |
| Gold | `fact_uncertainty` | Table | LEFT JOIN fact_calibration_status + calibration_uncertainty |
| Gold | `dim_instruments` | Table | unique instrument_id |

---

## Setup

### Requirements

- Docker + Docker Compose
- [UQaaS](https://gitlab.com/plasmallan/uqaas) running on port 8003
- Conda env `uqaas` (for local tests)

### Run

```bash
git clone git@gitlab.com:plasmallan/metrology-intelligence-platform.git
cd metrology-intelligence-platform

# Start PostgreSQL + MIP API + Dashboard + Airflow
docker compose up -d

# Services:
#   Dashboard : http://localhost:8502   (Streamlit)
#   MIP API   : http://localhost:8004
#   Docs      : http://localhost:8004/docs
#   Airflow   : http://localhost:8081   (admin / admin)
#   PG        : localhost:5436
```

### Trigger the full pipeline manually

```bash
# 1. Ingest synthetic calibration data (Bronze)
docker exec <airflow-container> airflow dags unpause ingest_calibration
docker exec <airflow-container> airflow dags trigger ingest_calibration

# 2. Run dbt transformations (Silver + Gold)
docker exec <airflow-container> airflow dags unpause transform_pipeline
docker exec <airflow-container> airflow dags trigger transform_pipeline

# 3. Enrich with UQaaS uncertainty (requires UQaaS on :8003)
docker exec <airflow-container> airflow dags unpause uncertainty_enrichment
docker exec <airflow-container> airflow dags trigger uncertainty_enrichment
```

### Tests

```bash
conda activate uqaas
cd metrology-intelligence-platform
pytest tests/test_synthetic_data.py tests/test_control_charts.py -v   # 44 unit tests
python tests/smoke_api.py                                               # 6 API assertions
```

---

## Integration with UQaaS

The `uncertainty_enrichment` DAG calls [UQaaS](https://gitlab.com/plasmallan/uqaas) at `POST /calculate/` with instrument-specific distributions:

```
XRF     → Normal(loc=batch_mean, scale=batch_sd/√n)   # Type A, GUM §4.2
Balance → Laplace(loc=batch_median, scale=MAD/ln2)    # MLE Laplace, u=b√2
HPLC    → Normal(loc=level_mean, scale=level_sd)      # peak area uncertainty
```

Results (u_combined, u_expanded_k2, coverage interval) are persisted in `calibration_uncertainty` and joined into the `fact_uncertainty` Gold model by dbt. UQaaS failures are non-blocking — the pipeline continues with `u_combined = NULL`.


---

## Stack

| Layer | Technology |
|---|---|
| Orchestration | Apache Airflow 2.8.1, LocalExecutor |
| Transformations | dbt-postgres 1.8.2 (view + table, 37 data tests) |
| Persistence | PostgreSQL 15, psycopg2 |
| API | FastAPI 0.111, Pydantic v2, Uvicorn |
| Dashboard | Streamlit 1.35, Plotly 5.22 (Levey-Jennings, alerts) |
| Uncertainty | UQaaS microservice (GUM Supl. 1, Monte Carlo, Laplace/Normal) |
| Generators | NumPy, SciPy (Laplace MLE, Normal, HPLC linearity) |
| Containerisation | Docker Compose (4 services: postgres, api, dashboard, airflow) |
| Tests | pytest (44 unit tests), smoke_api.py (6 API assertions) |
