"""Map synthetic instrument DataFrames to Bronze `raw_calibration` row dicts.

Shared by the `ingest_calibration` Airflow DAG and the CI/local seed script
(`ci/seed_db.py`) so the Bronze mapping lives in exactly one place.
"""
from __future__ import annotations

import json


def xrf_rows(df) -> list[dict]:
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


def hplc_rows(df) -> list[dict]:
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


def balance_rows(df) -> list[dict]:
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


def dataset_to_rows(datasets: dict) -> list[dict]:
    """Flatten a `generate_full_dataset()` result into Bronze row dicts."""
    return (
        xrf_rows(datasets["xrf_fe"])
        + xrf_rows(datasets["xrf_cu"])
        + xrf_rows(datasets["xrf_pb"])
        + hplc_rows(datasets["hplc"])
        + balance_rows(datasets["balance"])
    )
