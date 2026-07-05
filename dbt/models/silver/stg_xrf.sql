-- Silver: XRF readings — typed, enriched with batch statistics and deviation.
--
-- Per-batch mean and SD are computed here (window function) so downstream
-- Gold models and UQaaS calls receive pre-computed QC statistics.
--
-- Levey-Jennings z-score uses ROBUST control limits (median + MAD-based SD),
-- not the raw sample SD. Rationale: injected outliers inflate STDDEV_SAMP and
-- mask themselves (z never exceeds ±3). The robust scale
-- σ_robust = 1.4826 · MAD is insensitive to a minority of outliers, so genuine
-- 3–5σ spikes and systematic drift correctly trigger Westgard rules.
--   z = (reading - batch_median) / (1.4826 · MAD)

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
        COUNT(*)                            AS batch_n,
        -- robust center: median
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY reading_cps)
                                            AS batch_median
    FROM base
    GROUP BY batch_id, element
),

batch_mad AS (
    -- MAD = median of |xi - median|; robust SD = 1.4826 · MAD
    SELECT
        b.batch_id,
        b.element,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY ABS(b.reading_cps - s.batch_median)
        )                                   AS mad
    FROM base b
    JOIN batch_stats s USING (batch_id, element)
    GROUP BY b.batch_id, b.element
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
    ROUND((1.4826 * d.mad)::numeric, 4)     AS robust_sd,
    -- robust z-score: (reading - median) / (1.4826 · MAD)
    -- fall back to sample SD if MAD collapses to 0 (degenerate batch)
    CASE
        WHEN d.mad > 0
        THEN ROUND(((b.reading_cps - s.batch_median) / (1.4826 * d.mad))::numeric, 4)
        WHEN s.batch_sd > 0
        THEN ROUND(((b.reading_cps - s.batch_mean) / s.batch_sd)::numeric, 4)
        ELSE NULL
    END                                     AS z_score,
    ROUND((ABS(b.deviation_cps) / NULLIF(b.nominal_cps, 0) * 100)::numeric, 4)
                                            AS rel_deviation_pct
FROM base b
JOIN batch_stats s USING (batch_id, element)
JOIN batch_mad   d USING (batch_id, element)
