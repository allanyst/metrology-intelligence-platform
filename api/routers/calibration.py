"""
Calibration endpoints — reads from Gold layer (public_gold schema).

GET /calibration/                        → latest status per instrument
GET /calibration/{instrument_id}         → detail with uncertainty for one instrument
GET /calibration/{instrument_id}/chart   → Levey-Jennings data (XRF only)
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db import query

router = APIRouter(prefix="/calibration", tags=["calibration"])


# ── Response models ───────────────────────────────────────────────────────────

class InstrumentSummary(BaseModel):
    instrument_id:       str
    instrument_type:     str
    analyte_or_element:  str
    calibration_status:  str
    n_readings:          int
    mean_value:          float | None
    cv_pct:              float | None
    u_combined:          float | None
    u_expanded_k2:       float | None
    coverage_lower:      float | None
    coverage_upper:      float | None
    rel_u_expanded_pct:  float | None
    r_squared:           float | None
    dominant_rule:       str | None
    measurement_date:    str | None


class InstrumentDetail(InstrumentSummary):
    batch_id:            str
    sd_value:            float | None
    n_rejected:          int
    n_warnings:          int
    dominant_rule:       str | None
    uqaas_distribution:  str | None
    coverage_lower:      float | None
    coverage_upper:      float | None
    uqaas_calc_id:       int | None


class ControlChartPoint(BaseModel):
    measured_at:       str
    reading_cps:       float
    batch_mean:        float
    batch_sd:          float
    z_score:           float
    qc_status:         str
    violation_rule:    str | None
    violation_severity: str | None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[InstrumentSummary])
def list_calibration_status(
    instrument_type: str | None = Query(None, description="Filter: XRF | HPLC | Balance"),
    status: str | None = Query(None, description="Filter: in_control | warning | out_of_control"),
):
    """Latest calibration status for all instruments (from fact_uncertainty Gold table)."""
    conditions = []
    params: list = []
    if instrument_type:
        conditions.append("instrument_type = %s")
        params.append(instrument_type)
    if status:
        conditions.append("calibration_status = %s")
        params.append(status)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = query(f"""
        SELECT instrument_id, instrument_type, analyte_or_element,
               calibration_status, n_readings,
               CAST(mean_value AS float)          AS mean_value,
               CAST(cv_pct AS float)              AS cv_pct,
               u_combined, u_expanded_k2,
               coverage_lower, coverage_upper,
               CAST(rel_u_expanded_pct AS float)  AS rel_u_expanded_pct,
               r_squared, dominant_rule,
               measurement_date::text             AS measurement_date
        FROM public_gold.fact_uncertainty
        {where}
        ORDER BY instrument_type, analyte_or_element
    """, params or None)

    return rows


@router.get("/{instrument_id}", response_model=list[InstrumentDetail])
def get_instrument_detail(instrument_id: str):
    """Full detail (uncertainty + QC) for one instrument, all analytes/elements."""
    rows = query("""
        SELECT batch_id, instrument_id, instrument_type, analyte_or_element,
               calibration_status, n_readings,
               CAST(mean_value AS float)         AS mean_value,
               CAST(sd_value AS float)           AS sd_value,
               CAST(cv_pct AS float)             AS cv_pct,
               n_rejected, n_warnings, dominant_rule,
               u_combined, u_expanded_k2,
               CAST(rel_u_expanded_pct AS float) AS rel_u_expanded_pct,
               r_squared, uqaas_distribution,
               coverage_lower, coverage_upper,
               uqaas_calc_id,
               measurement_date::text            AS measurement_date
        FROM public_gold.fact_uncertainty
        WHERE instrument_id = %s
        ORDER BY analyte_or_element
    """, (instrument_id,))

    if not rows:
        raise HTTPException(status_code=404, detail=f"Instrument '{instrument_id}' not found")
    return rows


@router.get("/{instrument_id}/chart", response_model=list[ControlChartPoint])
def get_control_chart(
    instrument_id: str,
    element: str = Query(..., description="Element symbol, e.g. Fe"),
):
    """
    Levey-Jennings data for a specific XRF instrument + element.
    Returns individual readings with z-scores and Westgard rule violations.
    """
    rows = query("""
        SELECT
            measured_at::text   AS measured_at,
            reading_cps,
            batch_mean,
            batch_sd,
            z_score,
            qc_status,
            violation_rule,
            violation_severity
        FROM public_gold.fact_control_charts
        WHERE instrument_id = %s AND element = %s
        ORDER BY measured_at
    """, (instrument_id, element))

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No chart data for instrument '{instrument_id}', element '{element}'",
        )
    return rows
