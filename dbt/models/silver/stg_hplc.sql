-- Silver: HPLC calibration curve — typed with concentration levels and
-- per-level statistics for linearity assessment in Gold.

WITH base AS (
    SELECT
        id,
        batch_id,
        instrument_id,
        measurement_date,
        measured_at,
        unit,
        reading                                         AS peak_area,
        (payload->>'analyte')                           AS analyte,
        (payload->>'concentration_mgL')::double precision AS concentration_mgL,
        (payload->>'replicate')::int                   AS replicate
    FROM {{ ref("raw_calibration") }}
    WHERE instrument_type = 'HPLC'
),

level_stats AS (
    SELECT
        batch_id,
        analyte,
        concentration_mgL,
        AVG(peak_area)          AS level_mean_area,
        STDDEV_SAMP(peak_area)  AS level_sd_area,
        COUNT(*)                AS n_replicates
    FROM base
    GROUP BY batch_id, analyte, concentration_mgL
)

SELECT
    b.id,
    b.batch_id,
    b.instrument_id,
    b.analyte,
    b.measurement_date,
    b.measured_at,
    b.unit,
    b.concentration_mgL,
    b.replicate,
    b.peak_area,
    s.level_mean_area,
    s.level_sd_area,
    s.n_replicates,
    ROUND((s.level_sd_area / NULLIF(s.level_mean_area, 0) * 100)::numeric, 4)
                                AS rsd_pct
FROM base b
JOIN level_stats s USING (batch_id, analyte, concentration_mgL)
