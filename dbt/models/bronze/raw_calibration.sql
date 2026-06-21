-- Bronze view: expose raw_calibration exactly as ingested, no transformation.
-- Adds human-readable ingestion_date partition column for downstream filtering.

SELECT
    id,
    batch_id,
    instrument_id,
    instrument_type,
    measured_at,
    measured_at::date          AS measurement_date,
    unit,
    nominal_value,
    reading,
    payload,
    ingested_at
FROM {{ source("mip_raw", "raw_calibration") }}
