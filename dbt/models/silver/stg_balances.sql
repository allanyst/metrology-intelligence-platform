-- Silver: balance repeatability — typed with error model statistics.
--
-- Deviation = reading - nominal_value (includes systematic bias).
-- Corrected deviation = reading - (nominal_value + bias) — pure random error.
-- MAD and Laplace scale b = MAD/ln(2) are pre-computed here so Gold
-- can call UQaaS directly with these parameters.

WITH base AS (
    SELECT
        id,
        batch_id,
        instrument_id,
        measurement_date,
        measured_at,
        unit,
        nominal_value                                   AS nominal_mass_g,
        reading                                         AS reading_g,
        reading - nominal_value                         AS deviation_g,
        (payload->>'bias_g')::double precision          AS bias_g,
        reading - nominal_value
            - (payload->>'bias_g')::double precision    AS corrected_deviation_g
    FROM {{ ref("raw_calibration") }}
    WHERE instrument_type = 'Balance'
),

batch_median AS (
    -- PostgreSQL: PERCENTILE_CONT(0.5) is the median
    SELECT
        batch_id,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY reading_g) AS batch_median_g,
        COUNT(*)                                                 AS batch_n
    FROM base
    GROUP BY batch_id
),

batch_mad AS (
    -- MAD = median of |xi - median|
    -- Two-step: join median, compute abs deviations, then take median again
    SELECT
        b.batch_id,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY ABS(b.reading_g - m.batch_median_g)
        )                                               AS mad_g
    FROM base b
    JOIN batch_median m USING (batch_id)
    GROUP BY b.batch_id
)

SELECT
    b.id,
    b.batch_id,
    b.instrument_id,
    b.measurement_date,
    b.measured_at,
    b.unit,
    b.nominal_mass_g,
    b.reading_g,
    b.bias_g,
    b.deviation_g,
    b.corrected_deviation_g,
    m.batch_median_g,
    m.batch_n,
    d.mad_g,
    -- Laplace scale b = MAD / ln(2); u_rep = b * sqrt(2)
    ROUND((d.mad_g / LN(2))::numeric, 8)               AS laplace_b,
    ROUND((d.mad_g / LN(2) * SQRT(2))::numeric, 8)     AS u_rep_g
FROM base b
JOIN batch_median m USING (batch_id)
JOIN batch_mad    d USING (batch_id)
