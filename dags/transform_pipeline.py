"""
Transform pipeline DAG — Metrology Intelligence Platform.

Runs dbt Bronze → Silver → Gold after calibration data is ingested.
Triggered automatically after ingest_calibration completes (TriggerDagRunOperator),
or on its own daily schedule as a fallback.

Tasks
-----
dbt_run      : materialize all models (bronze view → silver views → gold tables)
dbt_test     : 37 data quality tests across all layers
dbt_snapshot : SCD Type 2 snapshot of fact_calibration_status (future use)
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator

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

    trigger_enrichment = TriggerDagRunOperator(
        task_id="trigger_uncertainty_enrichment",
        trigger_dag_id="uncertainty_enrichment",
        wait_for_completion=False,
    )

    dbt_run >> dbt_test >> trigger_enrichment
