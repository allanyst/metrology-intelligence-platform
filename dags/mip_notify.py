"""Shared alerting helpers for MIP DAGs.

- ``send_alert``     posts to Slack if ``MIP_SLACK_WEBHOOK`` is set, otherwise
                     logs a structured line (so CI/dev works with no webhook).
- ``notify_failure`` is an Airflow ``on_failure_callback``.
- ``check_qc_alerts`` flags out_of_control instruments after a dbt run and
                     raises them through ``send_alert`` — closes the loop from
                     "compute QC" to "notify on QC breach".
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import psycopg2
import psycopg2.extras

DB_URL = os.environ.get("MIP_DB_URL", "postgresql://mip:mip_pass@postgres:5432/mip_db")
SLACK  = os.environ.get("MIP_SLACK_WEBHOOK")


def send_alert(text: str, level: str = "warning") -> None:
    line = f"[MIP:{level.upper()}] {text}"
    print(line)
    if SLACK:
        try:
            req = urllib.request.Request(
                SLACK,
                data=json.dumps({"text": line}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
        except urllib.error.URLError as e:
            print(f"[MIP] Slack notify failed (non-blocking): {e}")


def notify_failure(context) -> None:
    """on_failure_callback: announce which task failed."""
    ti  = context.get("task_instance")
    dag = context.get("dag")
    send_alert(
        f"Task failed: {getattr(dag, 'dag_id', '?')}."
        f"{getattr(ti, 'task_id', '?')} (run {context.get('run_id')})",
        level="error",
    )


def check_qc_alerts(**context) -> dict:
    """Query Gold for out_of_control instruments and raise one alert each."""
    conn = psycopg2.connect(DB_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT instrument_id, instrument_type, analyte_or_element,
                       calibration_status, dominant_rule
                FROM public_gold.fact_calibration_status
                WHERE calibration_status = 'out_of_control'
                ORDER BY instrument_type, analyte_or_element
            """)
            offenders = cur.fetchall()
    finally:
        conn.close()

    if not offenders:
        print("[MIP] All instruments in control — no alerts.")
        return {"out_of_control": 0}

    for r in offenders:
        rule = r["dominant_rule"] or "tolerance"
        send_alert(
            f"{r['instrument_type']} {r['instrument_id']}/"
            f"{r['analyte_or_element']} OUT OF CONTROL (rule={rule})",
            level="warning",
        )
    return {"out_of_control": len(offenders)}
