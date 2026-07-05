"""Seed a Postgres database with the Bronze schema + synthetic calibration data.

Used by CI (and available locally) so `dbt build` has data to transform without
running Airflow. Applies docker/init-db/*.sql, then inserts one day of synthetic
Bronze rows via the same mapping the ingest DAG uses.

    MIP_DB_URL=postgresql://mip:mip_pass@localhost:5432/mip_db python ci/seed_db.py [seed]
"""
from __future__ import annotations

import glob
import os
import sys
import time

import psycopg2
import psycopg2.extras

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core.synthetic_data import generate_full_dataset   # noqa: E402
from core.bronze_rows import dataset_to_rows            # noqa: E402

DB_URL   = os.environ.get("MIP_DB_URL", "postgresql://mip:mip_pass@localhost:5432/mip_db")
INIT_DIR = os.path.join(_ROOT, "docker", "init-db")

INSERT_SQL = """
    INSERT INTO raw_calibration
        (batch_id, instrument_id, instrument_type, measured_at,
         unit, nominal_value, reading, payload)
    VALUES
        (%(batch_id)s, %(instrument_id)s, %(instrument_type)s, %(measured_at)s,
         %(unit)s, %(nominal_value)s, %(reading)s, %(payload)s)
    ON CONFLICT (batch_id, instrument_id, measured_at) DO NOTHING
"""


def _connect(retries: int = 20, delay: float = 2.0):
    """Connect with retries — the DB service may still be starting up in CI."""
    last = None
    for attempt in range(1, retries + 1):
        try:
            return psycopg2.connect(DB_URL)
        except psycopg2.OperationalError as e:
            last = e
            print(f"  waiting for database ({attempt}/{retries})...")
            time.sleep(delay)
    raise RuntimeError(f"Could not connect to {DB_URL}: {last}")


def main(seed: int = 42) -> None:
    conn = _connect()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for path in sorted(glob.glob(os.path.join(INIT_DIR, "*.sql"))):
                print(f"applying {os.path.basename(path)}")
                with open(path, encoding="utf-8") as fh:
                    cur.execute(fh.read())

            rows = dataset_to_rows(generate_full_dataset(seed=seed))
            psycopg2.extras.execute_batch(cur, INSERT_SQL, rows, page_size=200)

            cur.execute("SELECT COUNT(*) FROM raw_calibration")
            print(f"seeded raw_calibration — {cur.fetchone()[0]} rows total")
    finally:
        conn.close()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 42)
