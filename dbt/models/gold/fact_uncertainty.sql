-- Gold: joins calibration QC status with UQaaS uncertainty results.
-- u_combined / u_expanded_k2 come from the uncertainty_enrichment DAG,
-- not from dbt transformations — this is the microservice join point.

SELECT
    s.batch_id,
    s.instrument_id,
    s.instrument_type,
    s.analyte_or_element,
    s.measurement_date,
    s.n_readings,
    s.mean_value,
    s.sd_value,
    s.cv_pct,
    s.n_rejected,
    s.n_warnings,
    s.dominant_rule,
    s.calibration_status,
    s.r_squared,
    -- UQaaS uncertainty fields (NULL until enrichment DAG runs)
    u.uqaas_model,
    u.distribution                          AS uqaas_distribution,
    u.u_combined,
    u.u_expanded_k2,
    u.coverage_lower,
    u.coverage_upper,
    u.k,
    u.n_simulations                         AS uqaas_n_simulations,
    u.uqaas_calc_id,
    u.computed_at                           AS uncertainty_computed_at,
    -- Relative expanded uncertainty (metrological KPI)
    CASE
        WHEN u.u_expanded_k2 IS NOT NULL AND s.mean_value > 0
        THEN ROUND((u.u_expanded_k2 / s.mean_value * 100)::numeric, 4)
        ELSE NULL
    END                                     AS rel_u_expanded_pct
FROM {{ ref("fact_calibration_status") }} s
LEFT JOIN {{ source("mip_raw", "calibration_uncertainty") }} u
    ON  s.batch_id            = u.batch_id
    AND s.instrument_id       = u.instrument_id
    AND s.analyte_or_element  = u.analyte_or_element
