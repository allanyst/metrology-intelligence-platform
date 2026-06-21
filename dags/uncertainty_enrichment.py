"""
Uncertainty enrichment DAG — Metrology Intelligence Platform.

Reads calibration batch statistics from Gold (via PostgreSQL views),
calls UQaaS FastAPI at /calculate/ for each instrument/batch, and
persists u_combined + coverage interval in calibration_uncertainty.

This task demonstrates the microservice pattern: Gold dbt models compute
QC statistics; a separate service (UQaaS) owns the uncertainty physics.

UQaaS models used
-----------------
XRF     : Normal(loc=batch_mean, scale=batch_sd/sqrt(n))
          → uncertainty of the mean (Type A, GUM §4.2)
Balance : Laplace(loc=batch_median, scale=laplace_b)
          → u_rep = b*sqrt(2), MLE for Laplace (robust to vibration outliers)
HPLC    : Normal(loc=level_mean_area, scale=level_sd_area)
          at the highest concentration level (most sensitive linearity test)

Schedule: runs after transform_pipeline DAG (set via depends_on_past=False,
          triggered externally). Standalone: daily at 08:00 UTC.
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
from airflow import DAG
from airflow.operators.python import PythonOperator

DB_URL      = os.environ.get("MIP_DB_URL",    "postgresql://mip:mip_pass@postgres:5432/mip_db")
UQAAS_URL   = os.environ.get("UQAAS_API_URL", "http://host.docker.internal:8003")
N_SIM       = 100_000
K           = 2.0


# ── UQaaS HTTP client ─────────────────────────────────────────────────────────

def _call_uqaas(model: str, inputs: list[dict], n: int = N_SIM, k: float = K) -> dict:
    payload = json.dumps({"model": model, "inputs": inputs,
                          "n_simulations": n, "k": k}).encode()
    req = urllib.request.Request(
        f"{UQAAS_URL}/calculate/",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"UQaaS unreachable at {UQAAS_URL}: {e}") from e


# ── Per-instrument payloads ───────────────────────────────────────────────────

def _xrf_payload(batch_mean: float, batch_sd: float, n: int) -> tuple[str, str, list]:
    """Type A uncertainty of the XRF mean: u = SD/sqrt(n)."""
    u_mean = batch_sd / math.sqrt(n)
    model  = "x_xrf"
    dist   = "norm"
    inputs = [{"name": "x_xrf", "distribution": "norm",
               "params": {"loc": batch_mean, "scale": u_mean}}]
    return model, dist, inputs


def _balance_payload(batch_median: float, laplace_b: float) -> tuple[str, str, list]:
    """Laplace repeatability: u_rep = b*sqrt(2)."""
    model  = "x_bal"
    dist   = "laplace"
    inputs = [{"name": "x_bal", "distribution": "laplace",
               "params": {"loc": batch_median, "scale": laplace_b}}]
    return model, dist, inputs


def _hplc_payload(level_mean: float, level_sd: float) -> tuple[str, str, list]:
    """Type A uncertainty of peak area at highest concentration level."""
    model  = "x_hplc"
    dist   = "norm"
    inputs = [{"name": "x_hplc", "distribution": "norm",
               "params": {"loc": level_mean, "scale": level_sd}}]
    return model, dist, inputs


# ── Main enrichment task ──────────────────────────────────────────────────────

def enrich_uncertainty(**context):
    conn = psycopg2.connect(DB_URL)
    results = []

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # ── XRF: one row per (batch, element) ────────────────────────────
            cur.execute("""
                SELECT DISTINCT batch_id, instrument_id, element,
                       batch_mean, batch_sd, batch_n
                FROM public_silver.stg_xrf
            """)
            xrf_rows = cur.fetchall()

            for r in xrf_rows:
                model, dist, inputs = _xrf_payload(
                    r["batch_mean"], r["batch_sd"], r["batch_n"]
                )
                try:
                    res = _call_uqaas(model, inputs)
                    results.append({
                        "batch_id":          r["batch_id"],
                        "instrument_id":     r["instrument_id"],
                        "instrument_type":   "XRF",
                        "analyte_or_element": r["element"],
                        "uqaas_model":       model,
                        "distribution":      dist,
                        "u_combined":        res["u_combined"],
                        "u_expanded_k2":     res["u_expanded_k2"],
                        "coverage_lower":    res["coverage_lower"],
                        "coverage_upper":    res["coverage_upper"],
                        "k":                 res["k"],
                        "n_simulations":     res["n_simulations"],
                        "uqaas_calc_id":     res["id"],
                    })
                    print(f"XRF {r['element']}: u_combined={res['u_combined']:.6f} "
                          f"U(k=2)={res['u_expanded_k2']:.6f}")
                except Exception as e:
                    print(f"WARNING: UQaaS call failed for XRF {r['element']}: {e}")

            # ── Balance: one row per batch ────────────────────────────────────
            cur.execute("""
                SELECT DISTINCT batch_id, instrument_id,
                       batch_median_g, laplace_b
                FROM public_silver.stg_balances
            """)
            bal_rows = cur.fetchall()

            for r in bal_rows:
                model, dist, inputs = _balance_payload(
                    r["batch_median_g"], float(r["laplace_b"])
                )
                try:
                    res = _call_uqaas(model, inputs)
                    results.append({
                        "batch_id":          r["batch_id"],
                        "instrument_id":     r["instrument_id"],
                        "instrument_type":   "Balance",
                        "analyte_or_element": "mass",
                        "uqaas_model":       model,
                        "distribution":      dist,
                        "u_combined":        res["u_combined"],
                        "u_expanded_k2":     res["u_expanded_k2"],
                        "coverage_lower":    res["coverage_lower"],
                        "coverage_upper":    res["coverage_upper"],
                        "k":                 res["k"],
                        "n_simulations":     res["n_simulations"],
                        "uqaas_calc_id":     res["id"],
                    })
                    print(f"Balance: u_combined={res['u_combined']:.8f} "
                          f"U(k=2)={res['u_expanded_k2']:.8f}")
                except Exception as e:
                    print(f"WARNING: UQaaS call failed for Balance: {e}")

            # ── HPLC: highest concentration level per batch ───────────────────
            cur.execute("""
                SELECT DISTINCT ON (batch_id, analyte)
                    batch_id, instrument_id, analyte,
                    level_mean_area, level_sd_area
                FROM public_silver.stg_hplc
                ORDER BY batch_id, analyte, concentration_mgL DESC
            """)
            hplc_rows = cur.fetchall()

            for r in hplc_rows:
                model, dist, inputs = _hplc_payload(
                    float(r["level_mean_area"]), float(r["level_sd_area"])
                )
                try:
                    res = _call_uqaas(model, inputs)
                    results.append({
                        "batch_id":          r["batch_id"],
                        "instrument_id":     r["instrument_id"],
                        "instrument_type":   "HPLC",
                        "analyte_or_element": r["analyte"],
                        "uqaas_model":       model,
                        "distribution":      dist,
                        "u_combined":        res["u_combined"],
                        "u_expanded_k2":     res["u_expanded_k2"],
                        "coverage_lower":    res["coverage_lower"],
                        "coverage_upper":    res["coverage_upper"],
                        "k":                 res["k"],
                        "n_simulations":     res["n_simulations"],
                        "uqaas_calc_id":     res["id"],
                    })
                    print(f"HPLC {r['analyte']}: u_combined={res['u_combined']:.4f} "
                          f"U(k=2)={res['u_expanded_k2']:.4f}")
                except Exception as e:
                    print(f"WARNING: UQaaS call failed for HPLC {r['analyte']}: {e}")

    finally:
        conn.close()

    if not results:
        print("No UQaaS results to persist — UQaaS may be offline.")
        return

    # ── Upsert into calibration_uncertainty ──────────────────────────────────
    upsert_sql = """
        INSERT INTO calibration_uncertainty
            (batch_id, instrument_id, instrument_type, analyte_or_element,
             uqaas_model, distribution, u_combined, u_expanded_k2,
             coverage_lower, coverage_upper, k, n_simulations, uqaas_calc_id)
        VALUES
            (%(batch_id)s, %(instrument_id)s, %(instrument_type)s,
             %(analyte_or_element)s, %(uqaas_model)s, %(distribution)s,
             %(u_combined)s, %(u_expanded_k2)s, %(coverage_lower)s,
             %(coverage_upper)s, %(k)s, %(n_simulations)s, %(uqaas_calc_id)s)
        ON CONFLICT (batch_id, instrument_id, analyte_or_element)
        DO UPDATE SET
            u_combined     = EXCLUDED.u_combined,
            u_expanded_k2  = EXCLUDED.u_expanded_k2,
            coverage_lower = EXCLUDED.coverage_lower,
            coverage_upper = EXCLUDED.coverage_upper,
            uqaas_calc_id  = EXCLUDED.uqaas_calc_id,
            computed_at    = NOW()
    """
    conn2 = psycopg2.connect(DB_URL)
    try:
        with conn2.cursor() as cur:
            psycopg2.extras.execute_batch(cur, upsert_sql, results)
        conn2.commit()
    finally:
        conn2.close()

    print(f"\nPersisted {len(results)} uncertainty records into calibration_uncertainty")
    return {"enriched": len(results)}


# ── DAG ───────────────────────────────────────────────────────────────────────

with DAG(
    dag_id="uncertainty_enrichment",
    start_date=datetime(2026, 1, 1),
    schedule_interval="0 8 * * *",
    catchup=False,
    default_args={
        "retries": 1,
        "retry_delay": timedelta(seconds=30),
    },
    tags=["mip", "gold", "uqaas", "uncertainty"],
) as dag:

    enrich = PythonOperator(
        task_id="enrich_uncertainty",
        python_callable=enrich_uncertainty,
    )
