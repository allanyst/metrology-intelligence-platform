-- Gold: Levey-Jennings control chart with Westgard rules applied in SQL.
--
-- Rules implemented (Westgard JO, Clin Chem 1981 / ISO 17511):
--   1_3s  |z| > 3                          → REJECT
--   2_2s  2 consecutive z same side > ±2   → REJECT
--   R_4s  |z[i] - z[i-1]| > 4             → REJECT
--   4_1s  4 consecutive z same side > ±1   → WARNING
--   10x   10 consecutive z same side       → WARNING
--
-- Only XRF readings are evaluated here; balance QC is in fact_calibration_status.
-- Window partitioned by (instrument_id, element, batch_id) ordered by measured_at.

WITH xrf AS (
    SELECT
        id,
        batch_id,
        instrument_id,
        element,
        measurement_date,
        measured_at,
        reading_cps,
        batch_mean,
        batch_sd,
        z_score
    FROM {{ ref("stg_xrf") }}
    WHERE z_score IS NOT NULL
),

rules AS (
    SELECT
        *,
        -- ── 1₃s ─────────────────────────────────────────────────────────────
        ABS(z_score) > 3
            AS rule_1_3s,

        -- ── 2₂s ─────────────────────────────────────────────────────────────
        (
            z_score > 2  AND LAG(z_score) OVER w > 2
         OR z_score < -2 AND LAG(z_score) OVER w < -2
        )   AS rule_2_2s,

        -- ── R₄s ─────────────────────────────────────────────────────────────
        ABS(z_score - LAG(z_score) OVER w) > 4
            AS rule_R_4s,

        -- ── 4₁s: all 4 in window beyond ±1s on same side ────────────────────
        (
            SUM(CASE WHEN z_score >  1 THEN 1 ELSE 0 END)
                OVER (PARTITION BY instrument_id, element, batch_id
                      ORDER BY measured_at
                      ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) = 4
         OR SUM(CASE WHEN z_score < -1 THEN 1 ELSE 0 END)
                OVER (PARTITION BY instrument_id, element, batch_id
                      ORDER BY measured_at
                      ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) = 4
        )   AS rule_4_1s,

        -- ── 10ₓ: all 10 in window on same side of mean ───────────────────────
        (
            SUM(CASE WHEN z_score > 0 THEN 1 ELSE 0 END)
                OVER (PARTITION BY instrument_id, element, batch_id
                      ORDER BY measured_at
                      ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) = 10
         OR SUM(CASE WHEN z_score < 0 THEN 1 ELSE 0 END)
                OVER (PARTITION BY instrument_id, element, batch_id
                      ORDER BY measured_at
                      ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) = 10
        )   AS rule_10x

    FROM xrf
    WINDOW w AS (
        PARTITION BY instrument_id, element, batch_id
        ORDER BY measured_at
    )
),

classified AS (
    SELECT
        *,
        -- First triggered reject rule (priority: 1_3s > 2_2s > R_4s)
        CASE
            WHEN rule_1_3s THEN '1_3s'
            WHEN rule_2_2s THEN '2_2s'
            WHEN rule_R_4s THEN 'R_4s'
            ELSE NULL
        END AS reject_rule,
        -- First triggered warning rule
        CASE
            WHEN rule_4_1s THEN '4_1s'
            WHEN rule_10x  THEN '10x'
            ELSE NULL
        END AS warning_rule
    FROM rules
)

SELECT
    id,
    batch_id,
    instrument_id,
    element,
    measurement_date,
    measured_at,
    reading_cps,
    batch_mean,
    batch_sd,
    z_score,
    -- violation_rule: reject takes precedence over warning
    COALESCE(reject_rule, warning_rule)     AS violation_rule,
    CASE
        WHEN reject_rule  IS NOT NULL THEN 'reject'
        WHEN warning_rule IS NOT NULL THEN 'warning'
        ELSE NULL
    END                                     AS violation_severity,
    CASE
        WHEN reject_rule  IS NOT NULL THEN 'out_of_control'
        WHEN warning_rule IS NOT NULL THEN 'warning'
        ELSE 'in_control'
    END                                     AS qc_status
FROM classified
