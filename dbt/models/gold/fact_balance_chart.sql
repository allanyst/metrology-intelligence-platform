-- Gold: Levey-Jennings control chart for balance check-weight readings.
--
-- A balance calibration is a repeated measurement of a single nominal mass,
-- so the Levey-Jennings / Westgard framework applies directly. The z-score is
-- the bias-corrected deviation scaled by the robust Laplace repeatability
-- u_rep = b·√2 (from stg_balances):
--     z = (reading - nominal - bias) / u_rep
--
-- Applicable Westgard rules for a single control level:
--   1_3s  |z| > 3                        → REJECT   (matches balance QC in
--                                           fact_calibration_status)
--   2_2s  2 consecutive z same side > ±2  → REJECT
-- (4_1s/10x/R_4s are multi-level/paired-control rules — not applied here.)

WITH z AS (
    SELECT
        id,
        batch_id,
        instrument_id,
        measurement_date,
        measured_at,
        reading_g,
        nominal_mass_g,
        u_rep_g,
        corrected_deviation_g,
        CASE
            WHEN u_rep_g > 0
            THEN ROUND((corrected_deviation_g / u_rep_g)::numeric, 4)
            ELSE NULL
        END                                 AS z_score
    FROM {{ ref("stg_balances") }}
),

rules AS (
    SELECT
        *,
        ABS(z_score) > 3                    AS rule_1_3s,
        (
            z_score >  2 AND LAG(z_score) OVER w >  2
         OR z_score < -2 AND LAG(z_score) OVER w < -2
        )                                   AS rule_2_2s
    FROM z
    WHERE z_score IS NOT NULL
    WINDOW w AS (PARTITION BY instrument_id, batch_id ORDER BY measured_at)
)

SELECT
    id,
    batch_id,
    instrument_id,
    measurement_date,
    measured_at,
    reading_g,
    nominal_mass_g,
    u_rep_g,
    z_score,
    CASE
        WHEN rule_1_3s THEN '1_3s'
        WHEN rule_2_2s THEN '2_2s'
        ELSE NULL
    END                                     AS violation_rule,
    CASE
        WHEN rule_1_3s OR rule_2_2s THEN 'reject'
        ELSE NULL
    END                                     AS violation_severity,
    CASE
        WHEN rule_1_3s OR rule_2_2s THEN 'out_of_control'
        ELSE 'in_control'
    END                                     AS qc_status
FROM rules
