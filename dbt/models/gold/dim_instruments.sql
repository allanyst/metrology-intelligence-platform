-- Gold: instrument dimension — one row per instrument, derived from Bronze.
-- Static attributes inferred from data; enriched manually in production.

SELECT DISTINCT ON (instrument_id)
    instrument_id,
    instrument_type,
    MIN(measured_at) OVER (PARTITION BY instrument_id) AS first_seen_at,
    MAX(measured_at) OVER (PARTITION BY instrument_id) AS last_seen_at,
    COUNT(*)         OVER (PARTITION BY instrument_id) AS total_readings
FROM {{ ref("raw_calibration") }}
ORDER BY instrument_id, measured_at DESC
