-- ─────────────────────────────────────────────────────────────────────────────
-- MIP — Metrology Intelligence Platform
-- Bronze layer: raw calibration ingestion table
-- ─────────────────────────────────────────────────────────────────────────────

-- Bronze: one row per individual instrument reading, exactly as generated/received.
-- instrument-specific fields stored in payload JSONB — no transformation here.
CREATE TABLE IF NOT EXISTS raw_calibration (
    id              SERIAL PRIMARY KEY,
    batch_id        VARCHAR(128)  NOT NULL,
    instrument_id   VARCHAR(64)   NOT NULL,
    instrument_type VARCHAR(32)   NOT NULL,   -- XRF | HPLC | Balance
    measured_at     TIMESTAMPTZ   NOT NULL,
    unit            VARCHAR(16)   NOT NULL,
    nominal_value   DOUBLE PRECISION,         -- reference/expected value (nullable for HPLC curve)
    reading         DOUBLE PRECISION NOT NULL, -- raw measurement
    payload         JSONB         NOT NULL DEFAULT '{}', -- instrument-specific extras
    ingested_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_raw_batch      ON raw_calibration (batch_id);
CREATE INDEX IF NOT EXISTS idx_raw_instrument ON raw_calibration (instrument_id, instrument_type);
CREATE INDEX IF NOT EXISTS idx_raw_measured   ON raw_calibration (measured_at);

-- Prevent duplicate ingestion of the same batch
CREATE UNIQUE INDEX IF NOT EXISTS uidx_raw_batch_reading
    ON raw_calibration (batch_id, instrument_id, measured_at);
