-- Enable TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ── OHLCV bars ───────────────────────────────────────────────────────────────
-- Table name must match writer.py ("INSERT INTO ohlcv") and api/app.py queries
CREATE TABLE IF NOT EXISTS ohlcv (
    time        TIMESTAMPTZ      NOT NULL,
    ticker      TEXT             NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      DOUBLE PRECISION,
    vwap        DOUBLE PRECISION,
    source      TEXT             DEFAULT 'yfinance',
    created_at  TIMESTAMPTZ      DEFAULT NOW(),
    UNIQUE (ticker, time)   -- required by ON CONFLICT in writer.py
);

SELECT create_hypertable('ohlcv', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_time ON ohlcv (ticker, time DESC);

-- ── Macro / economic series ───────────────────────────────────────────────────
-- writer.py inserts into "macro" with columns: time, series_id, value, source
CREATE TABLE IF NOT EXISTS macro (
    time        TIMESTAMPTZ      NOT NULL,
    series_id   TEXT             NOT NULL,
    value       DOUBLE PRECISION,
    source      TEXT             DEFAULT 'fred',
    created_at  TIMESTAMPTZ      DEFAULT NOW(),
    UNIQUE (series_id, time)
);

SELECT create_hypertable('macro', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_macro_series_time ON macro (series_id, time DESC);

-- ── Feature vectors ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feature_vectors (
    time                TIMESTAMPTZ      NOT NULL,
    ticker              TEXT             NOT NULL,
    rv_5d               DOUBLE PRECISION,
    rv_21d              DOUBLE PRECISION,
    rv_63d              DOUBLE PRECISION,
    iv_atm              DOUBLE PRECISION,
    iv_skew             DOUBLE PRECISION,
    put_call_ratio      DOUBLE PRECISION,
    gex_proxy           DOUBLE PRECISION,
    rsi_14              DOUBLE PRECISION,
    tsi                 DOUBLE PRECISION,
    atr_14              DOUBLE PRECISION,
    vix                 DOUBLE PRECISION,
    vix_term_slope      DOUBLE PRECISION,
    yield_curve_slope   DOUBLE PRECISION,
    rv_5d_z             DOUBLE PRECISION,
    rv_21d_z            DOUBLE PRECISION,
    created_at          TIMESTAMPTZ      DEFAULT NOW()
);

SELECT create_hypertable('feature_vectors', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_features_ticker_time ON feature_vectors (ticker, time DESC);

-- ── Regime signals ───────────────────────────────────────────────────────────
-- Column names must match inference/engine.py _write_db():
--   regime INTEGER, hmm_prob JSONB, transformer_prob JSONB, ensemble_prob JSONB
CREATE TABLE IF NOT EXISTS regime_signals (
    time                TIMESTAMPTZ      NOT NULL,
    ticker              TEXT             NOT NULL,
    regime              INTEGER          NOT NULL,   -- 0=trending 1=mean_rev 2=choppy 3=high_vol
    confidence          DOUBLE PRECISION,
    hmm_prob            JSONB,
    transformer_prob    JSONB,
    ensemble_prob       JSONB,
    model_version       TEXT,
    created_at          TIMESTAMPTZ      DEFAULT NOW()
);

SELECT create_hypertable('regime_signals', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_regime_ticker_time ON regime_signals (ticker, time DESC);

-- ── Alert events ─────────────────────────────────────────────────────────────
-- Table name must match alert/app.py ("INSERT INTO alerts") and api/app.py ("FROM alerts")
-- api/app.py queries "WHERE read=FALSE" so the column must be named "read"
CREATE TABLE IF NOT EXISTS alerts (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    time        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ticker      TEXT,
    alert_type  TEXT        NOT NULL,
    severity    INTEGER     NOT NULL,   -- 1=info 2=warning 3=critical
    payload     JSONB,
    read        BOOLEAN     DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_alerts_time   ON alerts (time DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_ticker ON alerts (ticker, time DESC);

-- ── Daily OHLCV aggregate (TimescaleDB continuous aggregate) ─────────────────
CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    ticker,
    first(open, time)   AS open,
    max(high)           AS high,
    min(low)            AS low,
    last(close, time)   AS close,
    sum(volume)         AS volume
FROM ohlcv
GROUP BY bucket, ticker
WITH NO DATA;

-- Refresh policy: update daily aggregate every hour
SELECT add_continuous_aggregate_policy('ohlcv_daily',
    start_offset      => INTERVAL '7 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE
);

-- ── Data retention policies ──────────────────────────────────────────────────
SELECT add_retention_policy('ohlcv',            INTERVAL '2 years', if_not_exists => TRUE);
SELECT add_retention_policy('feature_vectors',  INTERVAL '5 years', if_not_exists => TRUE);
SELECT add_retention_policy('regime_signals',   INTERVAL '5 years', if_not_exists => TRUE);

-- ── MLflow database ──────────────────────────────────────────────────────────
-- Must be last statement; CREATE DATABASE cannot run inside a transaction block.
CREATE DATABASE mlflow OWNER quantpulse;
