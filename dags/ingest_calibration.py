"""
Bronze ingestion DAG — Metrology Intelligence Platform.

Generates synthetic calibration data for XRF (Fe, Cu, Pb), HPLC, and
Balance instruments, then upserts rows into the Bronze table raw_calibration.

Schedule: daily at 07:00 UTC (simulates overnight batch from instruments).
Idempotent: duplicate (batch_id, instrument_id, measured_at) rows are
ignored via ON CONFLICT DO NOTHING.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
from airflow import DAG
from airflow.operators.python import PythonOperator

sys.path.insert(0, "/opt/airflow")

DB_URL = os.environ.get("MIP_DB_URL", "postgresql://mip:mip_pass@postgres:5432/mip_db")


# ── Row mappers ───────────────────────────────────────────────────────────────

def _xrf_rows(df):
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "batch_id":        r["batch_id"],
            "instrument_id":   r["instrument_id"],
            "instrument_type": r["instrument_type"],
            "measured_at":     r["measured_at"].isoformat(),
            "unit":            r["unit"],
            "nominal_value":   float(r["nominal_value"]),
            "reading":         float(r["reading"]),
            "payload":         json.dumps({"element": r["element"]}),
        })
    return rows


def _hplc_rows(df):
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "batch_id":        r["batch_id"],
            "instrument_id":   r["instrument_id"],
            "instrument_type": r["instrument_type"],
            "measured_at":     r["measured_at"].isoformat(),
            "unit":            r["unit"],
            "nominal_value":   None,
            "reading":         float(r["peak_area"]),
            "payload":         json.dumps({
                "analyte":           r["analyte"],
                "concentration_mgL": float(r["concentration_mgL"]),
                "replicate":         int(r["replicate"]),
            }),
        })
    return rows


def _balance_rows(df):
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "batch_id":        r["batch_id"],
            "instrument_id":   r["instrument_id"],
            "instrument_type": r["instrument_type"],
            "measured_at":     r["measured_at"].isoformat(),
            "unit":            r["unit"],
            "nominal_value":   float(r["nominal_mass_g"]),
            "reading":         float(r["reading_g"]),
            "payload":         json.dumps({"bias_g": float(r["bias_g"])}),
        })
    return rows


# ── Main ingestion task ───────────────────────────────────────────────────────

def ingest_calibration_data(**context):
    from core.synthetic_data import generate_full_dataset

    logical_date = context["logical_date"]
    seed = int(logical_date.strftime("%Y%m%d")) % (2**31)

    print(f"Generating synthetic data for {logical_date.date()} (seed={seed})")
    datasets = generate_full_dataset(seed=seed)

    all_rows = (
        _xrf_rows(datasets["xrf_fe"])
        + _xrf_rows(datasets["xrf_cu"])
        + _xrf_rows(datasets["xrf_pb"])
        + _hplc_rows(datasets["hplc"])
        + _balance_rows(datasets["balance"])
    )

    insert_sql = """
        INSERT INTO raw_calibration
            (batch_id, instrument_id, instrument_type, measured_at,
             unit, nominal_value, reading, payload)
        VALUES
            (%(batch_id)s, %(instrument_id)s, %(instrument_type)s, %(measured_at)s,
             %(unit)s, %(nominal_value)s, %(reading)s, %(payload)s)
        ON CONFLICT (batch_id, instrument_id, measured_at) DO NOTHING
    """

    conn = psycopg2.connect(DB_URL)
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, insert_sql, all_rows, page_size=200)
            inserted = cur.rowcount
        conn.commit()
    finally:
        conn.close()

    print(f"Ingested {len(all_rows)} rows ({inserted} new) into raw_calibration")
    return {"total": len(all_rows), "inserted": inserted}


def verify_ingestion(**context):
    """Quick sanity check: count rows per instrument_type for today's batches."""
    conn = psycopg2.connect(DB_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT instrument_type, COUNT(*) AS n
                FROM raw_calibration
                WHERE ingested_at >= NOW() - INTERVAL '1 hour'
                GROUP BY instrument_type
                ORDER BY instrument_type
            """)
            rows = cur.fetchall()
    finally:
        conn.close()

    print("\nBronze ingestion summary (last hour):")
    total = 0
    for r in rows:
        print(f"  {r['instrument_type']:10s}: {r['n']:4d} rows")
        total += r["n"]
    print(f"  {'TOTAL':10s}: {total:4d} rows")

    if total == 0:
        raise ValueError("No rows found in raw_calibration after ingestion — pipeline failed.")


# ── DAG definition ────────────────────────────────────────────────────────────

with DAG(
    dag_id="ingest_calibration",
    start_date=datetime(2026, 1, 1),
    schedule_interval="0 7 * * *",
    catchup=False,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(seconds=20),
    },
    tags=["mip", "bronze", "ingestion"],
) as dag:

    ingest = PythonOperator(
        task_id="ingest_calibration_data",
        python_callable=ingest_calibration_data,
    )

    verify = PythonOperator(
        task_id="verify_ingestion",
        python_callable=verify_ingestion,
    )

    ingest >> verify
