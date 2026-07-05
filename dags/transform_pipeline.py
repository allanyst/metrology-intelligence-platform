"""
Transform pipeline DAG — Metrology Intelligence Platform.

Runs dbt Bronze → Silver → Gold after calibration data is ingested, snapshots
the calibration status history (SCD Type 2), raises QC alerts, and triggers the
uncertainty enrichment.

Tasks
-----
dbt_run       : materialize all models (bronze view → silver views → gold tables)
dbt_test      : 44 data quality tests across all layers
dbt_snapshot  : SCD Type 2 snapshot of fact_calibration_status
notify_qc     : alert on any instrument that is out_of_control
trigger_...   : kick off uncertainty_enrichment (UQaaS)
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator

sys.path.insert(0, "/opt/airflow/dags")
from mip_notify import check_qc_alerts, notify_failure   # noqa: E402

DBT_DIR      = "/opt/airflow/dbt"
PROFILES_DIR = "/opt/airflow/dbt_profiles"
_DBT = (
    f"dbt {{cmd}} --project-dir {DBT_DIR} --profiles-dir {PROFILES_DIR} "
    "--target prod --log-path /tmp/dbt_logs --target-path /tmp/dbt_target"
)

with DAG(
    dag_id="transform_pipeline",
    start_date=datetime(2026, 1, 1),
    schedule_interval="30 7 * * *",   # 30 min after ingest_calibration (07:00)
    catchup=False,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(seconds=20),
        "on_failure_callback": notify_failure,
    },
    tags=["mip", "dbt", "silver", "gold"],
) as dag:

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=_DBT.format(cmd="run"),
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=_DBT.format(cmd="test"),
    )

    dbt_snapshot = BashOperator(
        task_id="dbt_snapshot",
        bash_command=_DBT.format(cmd="snapshot"),
    )

    notify_qc = PythonOperator(
        task_id="notify_qc",
        python_callable=check_qc_alerts,
    )

    trigger_enrichment = TriggerDagRunOperator(
        task_id="trigger_uncertainty_enrichment",
        trigger_dag_id="uncertainty_enrichment",
        wait_for_completion=False,
    )

    dbt_run >> dbt_test >> dbt_snapshot >> notify_qc >> trigger_enrichment
