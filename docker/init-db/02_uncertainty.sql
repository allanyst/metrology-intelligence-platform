-- Stores UQaaS uncertainty results linked to calibration batches.
-- Populated by the uncertainty_enrichment Airflow DAG (not by dbt).
CREATE TABLE IF NOT EXISTS calibration_uncertainty (
    id              SERIAL PRIMARY KEY,
    batch_id        VARCHAR(128)     NOT NULL,
    instrument_id   VARCHAR(64)      NOT NULL,
    instrument_type VARCHAR(32)      NOT NULL,
    analyte_or_element VARCHAR(64)   NOT NULL,
    uqaas_model     TEXT             NOT NULL,   -- model expression sent to UQaaS
    distribution    VARCHAR(32)      NOT NULL,   -- e.g. norm, laplace
    u_combined      DOUBLE PRECISION NOT NULL,
    u_expanded_k2   DOUBLE PRECISION NOT NULL,
    coverage_lower  DOUBLE PRECISION NOT NULL,
    coverage_upper  DOUBLE PRECISION NOT NULL,
    k               DOUBLE PRECISION NOT NULL DEFAULT 2.0,
    n_simulations   INTEGER          NOT NULL,
    uqaas_calc_id   INTEGER,                     -- id returned by UQaaS /calculate/
    computed_at     TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uidx_unc_batch_instrument
    ON calibration_uncertainty (batch_id, instrument_id, analyte_or_element);

CREATE INDEX IF NOT EXISTS idx_unc_computed ON calibration_uncertainty (computed_at);
