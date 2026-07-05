{% snapshot scd_calibration_status %}
-- SCD Type 2 history of each instrument's calibration status.
--
-- The `check` strategy opens a new version only when calibration_status or the
-- dominant Westgard rule changes — daily re-runs with an unchanged status do
-- not create noise. This answers the metrological audit question ISO 17025
-- reviewers ask: "since when has this instrument been out of control?"
--
-- unique_key is stable across days: instrument + analyte/element (batch_id
-- carries the date and would otherwise open a new version every run).
{{ config(
    target_schema           = "snapshots",
    unique_key              = "scd_key",
    strategy                = "check",
    check_cols              = ["calibration_status", "dominant_rule"],
    invalidate_hard_deletes = true,
) }}

SELECT
    instrument_id || '-' || analyte_or_element AS scd_key,
    instrument_id,
    instrument_type,
    analyte_or_element,
    calibration_status,
    dominant_rule,
    n_rejected,
    n_warnings,
    measurement_date
FROM {{ ref("fact_calibration_status") }}

{% endsnapshot %}
