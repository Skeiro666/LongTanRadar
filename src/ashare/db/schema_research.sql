-- Additive research tables. Do not drop existing trading tables.
CREATE TABLE IF NOT EXISTS research_sessions (
    research_id     TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    name            TEXT,
    research_time   TIMESTAMPTZ NOT NULL,
    rating          TEXT,
    trading_action  TEXT,
    confidence      DOUBLE PRECISION,
    payload_json    JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_research_sessions_symbol ON research_sessions (symbol);
CREATE INDEX IF NOT EXISTS idx_research_sessions_time ON research_sessions (research_time DESC);

CREATE TABLE IF NOT EXISTS research_snapshots (
    research_id     TEXT PRIMARY KEY REFERENCES research_sessions(research_id),
    factor_version  TEXT,
    prompt_bundle   TEXT,
    model_bundle    TEXT,
    snapshot_json   JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS research_outcomes (
    id              BIGSERIAL PRIMARY KEY,
    research_id     TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    horizon_days    INTEGER NOT NULL,
    actual_return   DOUBLE PRECISION,
    benchmark_return DOUBLE PRECISION,
    excess_return   DOUBLE PRECISION,
    hit             BOOLEAN,
    discovery_sources TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_research_outcomes_rid ON research_outcomes (research_id);
-- Existing DBs: ALTER TABLE research_outcomes ADD COLUMN IF NOT EXISTS discovery_sources TEXT;

CREATE TABLE IF NOT EXISTS factor_definitions (
    factor_name     TEXT PRIMARY KEY,
    category        TEXT,
    description     TEXT,
    available       BOOLEAN DEFAULT TRUE,
    active          BOOLEAN DEFAULT TRUE,
    meta_json       JSONB
);

CREATE TABLE IF NOT EXISTS prompt_versions (
    prompt_key      TEXT PRIMARY KEY,
    version         TEXT NOT NULL,
    body            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS model_versions (
    model_key       TEXT PRIMARY KEY,
    version         TEXT NOT NULL,
    meta_json       JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
