"""Backfill several days of synthetic calibration data to demonstrate the
temporal features: incremental Gold fact tables and the SCD Type 2 snapshot.

For each day it inserts one distinct batch (batch_id carries the date), runs dbt
(the incremental control-chart models append only the new day) and dbt snapshot
(the check strategy opens a new SCD version whenever an instrument's status
changes). Starts from a clean slate so the history builds chronologically.

Run inside the Airflow container (dbt + core on path):

    docker exec <airflow> python /opt/airflow/ci/backfill_demo.py 7

Env (container defaults shown):
    MIP_DB_URL        postgresql://mip:mip_pass@postgres:5432/mip_db
    DBT_PROJECT_DIR   /opt/airflow/dbt
    DBT_PROFILES_DIR  /opt/airflow/dbt_profiles
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, "/opt/airflow")  # container: core is at /opt/airflow/core

from core.synthetic_data import generate_full_dataset   # noqa: E402
from core.bronze_rows import dataset_to_rows            # noqa: E402

DB_URL       = os.environ.get("MIP_DB_URL", "postgresql://mip:mip_pass@postgres:5432/mip_db")
PROJECT_DIR  = os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/dbt")
PROFILES_DIR = os.environ.get("DBT_PROFILES_DIR", "/opt/airflow/dbt_profiles")
END_DATE     = datetime(2026, 7, 4, 8, 0)   # most recent batch date

INSERT_SQL = """
    INSERT INTO raw_calibration
        (batch_id, instrument_id, instrument_type, measured_at,
         unit, nominal_value, reading, payload)
    VALUES
        (%(batch_id)s, %(instrument_id)s, %(instrument_type)s, %(measured_at)s,
         %(unit)s, %(nominal_value)s, %(reading)s, %(payload)s)
    ON CONFLICT (batch_id, instrument_id, measured_at) DO NOTHING
"""


def _dbt(command: str) -> None:
    subprocess.run(
        ["dbt", command,
         "--project-dir", PROJECT_DIR,
         "--profiles-dir", PROFILES_DIR,
         "--target", "prod",
         "--target-path", "/tmp/dbt_target",
         "--log-path", "/tmp/dbt_logs"],
        check=True,
    )


def _reset(conn) -> None:
    """Clean slate so the multi-day history builds chronologically."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE raw_calibration RESTART IDENTITY")
        cur.execute("TRUNCATE calibration_uncertainty RESTART IDENTITY")
        cur.execute("DROP TABLE IF EXISTS public_gold.fact_control_charts")
        cur.execute("DROP TABLE IF EXISTS public_gold.fact_balance_chart")
        cur.execute("DROP TABLE IF EXISTS snapshots.scd_calibration_status")
    conn.commit()


def _insert_day(conn, start: datetime) -> int:
    seed = int(start.strftime("%Y%m%d")) % (2**31)
    rows = dataset_to_rows(generate_full_dataset(seed=seed, start=start))
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, INSERT_SQL, rows, page_size=200)
    conn.commit()
    return len(rows)


def main(n_days: int = 7) -> None:
    dates = [END_DATE - timedelta(days=d) for d in range(n_days - 1, -1, -1)]

    conn = psycopg2.connect(DB_URL)
    try:
        print(f"Resetting Bronze/Gold/snapshot for a {n_days}-day backfill...")
        _reset(conn)

        for start in dates:
            n = _insert_day(conn, start)
            print(f"\n=== {start.date()}  (+{n} Bronze rows) ===")
            _dbt("run")        # incremental models append only this day
            _dbt("snapshot")   # SCD Type 2 versions any status change
    finally:
        conn.close()

    print(f"\nBackfill complete: {len(dates)} days "
          f"({dates[0].date()} … {dates[-1].date()}).")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
