-- Silver: XRF readings — typed, enriched with batch statistics and deviation.
--
-- Per-batch mean and SD are computed here (window function) so downstream
-- Gold models and UQaaS calls receive pre-computed QC statistics.
-- z_score follows: z = (reading - batch_mean) / batch_sd

WITH base AS (
    SELECT
        id,
        batch_id,
        instrument_id,
        measurement_date,
        measured_at,
        unit,
        nominal_value                       AS nominal_cps,
        reading                             AS reading_cps,
        reading - nominal_value             AS deviation_cps,
        payload->>'element'                 AS element
    FROM {{ ref("raw_calibration") }}
    WHERE instrument_type = 'XRF'
),

batch_stats AS (
    SELECT
        batch_id,
        element,
        AVG(reading_cps)                    AS batch_mean,
        STDDEV_SAMP(reading_cps)            AS batch_sd,
        COUNT(*)                            AS batch_n
    FROM base
    GROUP BY batch_id, element
)

SELECT
    b.id,
    b.batch_id,
    b.instrument_id,
    b.element,
    b.measurement_date,
    b.measured_at,
    b.unit,
    b.nominal_cps,
    b.reading_cps,
    b.deviation_cps,
    s.batch_mean,
    s.batch_sd,
    s.batch_n,
    CASE
        WHEN s.batch_sd > 0
        THEN ROUND(((b.reading_cps - s.batch_mean) / s.batch_sd)::numeric, 4)
        ELSE NULL
    END                                     AS z_score,
    ROUND((ABS(b.deviation_cps) / NULLIF(b.nominal_cps, 0) * 100)::numeric, 4)
                                            AS rel_deviation_pct
FROM base b
JOIN batch_stats s USING (batch_id, element)
