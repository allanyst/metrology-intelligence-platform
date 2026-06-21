"""
Alerts endpoint — instruments currently out_of_control or warning.

GET /alerts/          → all active alerts with dominant Westgard rule
GET /alerts/summary   → count by severity and instrument type
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from db import query

router = APIRouter(prefix="/alerts", tags=["alerts"])


class Alert(BaseModel):
    instrument_id:      str
    instrument_type:    str
    analyte_or_element: str
    calibration_status: str          # "out_of_control" | "warning"
    n_rejected:         int
    n_warnings:         int
    dominant_rule:      str | None
    mean_value:         float | None
    cv_pct:             float | None
    u_expanded_k2:      float | None
    measurement_date:   str | None


class AlertSummary(BaseModel):
    total_alerts:       int
    out_of_control:     int
    warnings:           int
    by_instrument_type: dict[str, int]
    by_rule:            dict[str, int]


@router.get("/", response_model=list[Alert])
def list_alerts():
    """All instruments not in_control, ordered by severity then instrument."""
    rows = query("""
        SELECT
            instrument_id,
            instrument_type,
            analyte_or_element,
            calibration_status,
            n_rejected,
            n_warnings,
            dominant_rule,
            CAST(mean_value AS float)    AS mean_value,
            CAST(cv_pct AS float)        AS cv_pct,
            u_expanded_k2,
            measurement_date::text       AS measurement_date
        FROM public_gold.fact_uncertainty
        WHERE calibration_status IN ('out_of_control', 'warning')
        ORDER BY
            CASE calibration_status
                WHEN 'out_of_control' THEN 1
                WHEN 'warning'        THEN 2
            END,
            instrument_type,
            analyte_or_element
    """)
    return rows


@router.get("/summary", response_model=AlertSummary)
def alert_summary():
    """Aggregated alert counts by severity, instrument type, and Westgard rule."""
    rows = query("""
        SELECT calibration_status, instrument_type, dominant_rule, COUNT(*) n
        FROM public_gold.fact_uncertainty
        WHERE calibration_status IN ('out_of_control', 'warning')
        GROUP BY calibration_status, instrument_type, dominant_rule
    """)

    total = sum(r["n"] for r in rows)
    oc    = sum(r["n"] for r in rows if r["calibration_status"] == "out_of_control")
    warn  = sum(r["n"] for r in rows if r["calibration_status"] == "warning")

    by_type: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    for r in rows:
        by_type[r["instrument_type"]] = by_type.get(r["instrument_type"], 0) + r["n"]
        rule = r["dominant_rule"] or "none"
        by_rule[rule] = by_rule.get(rule, 0) + r["n"]

    return AlertSummary(
        total_alerts=total,
        out_of_control=oc,
        warnings=warn,
        by_instrument_type=by_type,
        by_rule=by_rule,
    )
