-- Gold: one row per (instrument, batch, measurement_date) with:
--   · XRF  — QC status from control chart, CV%, violation counts
--   · HPLC — linearity R² (REGR_R2), max RSD%, pass/fail
--   · Balance — u_rep, Laplace b, QC status
--
-- u_combined column left NULL here; populated in Phase 5 by the
-- uncertainty_enrichment DAG calling UQaaS via HTTP.

-- ── XRF status ────────────────────────────────────────────────────────────────
WITH xrf_status AS (
    SELECT
        batch_id,
        instrument_id,
        'XRF'                               AS instrument_type,
        element                             AS analyte_or_element,
        measurement_date,
        COUNT(*)                            AS n_readings,
        ROUND(AVG(reading_cps)::numeric, 4) AS mean_value,
        ROUND(AVG(batch_sd)::numeric, 4)    AS sd_value,
        ROUND((AVG(batch_sd) / NULLIF(AVG(reading_cps), 0) * 100)::numeric, 4)
                                            AS cv_pct,
        SUM(CASE WHEN qc_status = 'out_of_control' THEN 1 ELSE 0 END)
                                            AS n_rejected,
        SUM(CASE WHEN qc_status = 'warning'         THEN 1 ELSE 0 END)
                                            AS n_warnings,
        -- dominant rule (most frequent violation)
        MODE() WITHIN GROUP (ORDER BY violation_rule)
                                            AS dominant_rule,
        CASE
            WHEN SUM(CASE WHEN qc_status = 'out_of_control' THEN 1 ELSE 0 END) > 0
                THEN 'out_of_control'
            WHEN SUM(CASE WHEN qc_status = 'warning' THEN 1 ELSE 0 END) > 0
                THEN 'warning'
            ELSE 'in_control'
        END                                 AS calibration_status,
        NULL::double precision              AS u_rep,
        NULL::double precision              AS r_squared,
        NULL::double precision              AS u_combined   -- filled by UQaaS in Phase 5
    FROM {{ ref("fact_control_charts") }}
    GROUP BY batch_id, instrument_id, element, measurement_date
),

-- ── HPLC status ───────────────────────────────────────────────────────────────
hplc_status AS (
    SELECT
        batch_id,
        instrument_id,
        'HPLC'                              AS instrument_type,
        analyte                             AS analyte_or_element,
        measurement_date,
        COUNT(*)                            AS n_readings,
        ROUND(AVG(level_mean_area)::numeric, 4) AS mean_value,
        ROUND(AVG(level_sd_area)::numeric,  4)  AS sd_value,
        ROUND(AVG(rsd_pct)::numeric, 4)         AS cv_pct,
        0                                   AS n_rejected,
        0                                   AS n_warnings,
        NULL                                AS dominant_rule,
        -- Pass if R² > 0.999 and max RSD < 5%
        CASE
            WHEN REGR_R2(level_mean_area, concentration_mgL) > 0.999
             AND MAX(rsd_pct) < 5.0
            THEN 'in_control'
            WHEN REGR_R2(level_mean_area, concentration_mgL) > 0.995
            THEN 'warning'
            ELSE 'out_of_control'
        END                                 AS calibration_status,
        NULL::double precision              AS u_rep,
        ROUND(REGR_R2(level_mean_area, concentration_mgL)::numeric, 6)
                                            AS r_squared,
        NULL::double precision              AS u_combined
    FROM {{ ref("stg_hplc") }}
    GROUP BY batch_id, instrument_id, analyte, measurement_date
),

-- ── Balance status ────────────────────────────────────────────────────────────
balance_status AS (
    SELECT
        batch_id,
        instrument_id,
        'Balance'                           AS instrument_type,
        'mass'                              AS analyte_or_element,
        measurement_date,
        COUNT(*)                            AS n_readings,
        ROUND(AVG(reading_g)::numeric, 6)   AS mean_value,
        ROUND(AVG(u_rep_g)::numeric, 8)     AS sd_value,
        ROUND((AVG(u_rep_g) / NULLIF(AVG(nominal_mass_g), 0) * 100)::numeric, 6)
                                            AS cv_pct,
        -- Simple balance QC: flag if |mean - nominal| > 3 * u_rep
        SUM(CASE
            WHEN ABS(reading_g - nominal_mass_g - bias_g)
                 > 3 * u_rep_g THEN 1 ELSE 0
        END)                                AS n_rejected,
        0                                   AS n_warnings,
        NULL                                AS dominant_rule,
        CASE
            WHEN SUM(CASE
                WHEN ABS(reading_g - nominal_mass_g - bias_g)
                     > 3 * u_rep_g THEN 1 ELSE 0 END) > 0
            THEN 'out_of_control'
            ELSE 'in_control'
        END                                 AS calibration_status,
        ROUND(AVG(u_rep_g)::numeric, 8)     AS u_rep,
        NULL::double precision              AS r_squared,
        NULL::double precision              AS u_combined
    FROM {{ ref("stg_balances") }}
    GROUP BY batch_id, instrument_id, measurement_date
),

-- Operational "current status" grain: one row per instrument/analyte, keeping
-- the most recent measurement_date. Full per-reading history lives in
-- fact_control_charts / fact_balance_chart; the SCD Type 2 snapshot versions
-- this current status over time.
unioned AS (
    SELECT * FROM xrf_status
    UNION ALL
    SELECT * FROM hplc_status
    UNION ALL
    SELECT * FROM balance_status
),

latest AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY instrument_id, analyte_or_element
            ORDER BY measurement_date DESC
        ) AS _rn
    FROM unioned
)

SELECT
    batch_id, instrument_id, instrument_type, analyte_or_element,
    measurement_date, n_readings, mean_value, sd_value, cv_pct,
    n_rejected, n_warnings, dominant_rule, calibration_status,
    u_rep, r_squared, u_combined
FROM latest
WHERE _rn = 1
