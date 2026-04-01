-- OceanGuard AI — PostgreSQL + PostGIS + pgvector schema
-- Run: psql -U postgres -d oceanguard -f 001_init_schema.sql

-- Extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;  -- optional, comment out if not installed

-- ── Vessels (current state) ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vessels (
    mmsi            TEXT PRIMARY KEY,
    name            TEXT,
    lat             DOUBLE PRECISION NOT NULL,
    lon             DOUBLE PRECISION NOT NULL,
    geom            GEOMETRY(Point, 4326),          -- PostGIS spatial index
    speed           REAL DEFAULT 0,
    heading         REAL DEFAULT 0,
    course          REAL DEFAULT 0,
    vessel_type     TEXT DEFAULT 'Unknown',
    flag            TEXT DEFAULT 'Unknown',
    imo             TEXT,
    status          TEXT DEFAULT 'underway',
    trail           JSONB DEFAULT '[]',
    risk_score      REAL DEFAULT 0,                 -- 0-100 Climate Risk Score
    anomaly_score   REAL DEFAULT 0,                 -- 0-1 behavioral anomaly
    risk_label      TEXT DEFAULT 'low',             -- low/medium/high/critical
    last_weather    JSONB DEFAULT '{}',             -- cached weather snapshot
    timestamp       TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vessels_geom    ON vessels USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_vessels_flag    ON vessels(flag);
CREATE INDEX IF NOT EXISTS idx_vessels_risk    ON vessels(risk_score DESC);
CREATE INDEX IF NOT EXISTS idx_vessels_type    ON vessels(vessel_type);
CREATE INDEX IF NOT EXISTS idx_vessels_updated ON vessels(updated_at DESC);

-- Auto-update geom from lat/lon
CREATE OR REPLACE FUNCTION update_vessel_geom()
RETURNS TRIGGER AS $$
BEGIN
    NEW.geom = ST_SetSRID(ST_MakePoint(NEW.lon, NEW.lat), 4326);
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_vessel_geom ON vessels;
CREATE TRIGGER trg_vessel_geom
    BEFORE INSERT OR UPDATE OF lat, lon ON vessels
    FOR EACH ROW EXECUTE FUNCTION update_vessel_geom();

-- ── Position history (time-series) ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS positions_history (
    id          BIGSERIAL,
    mmsi        TEXT NOT NULL,
    lat         DOUBLE PRECISION NOT NULL,
    lon         DOUBLE PRECISION NOT NULL,
    geom        GEOMETRY(Point, 4326),
    speed       REAL,
    heading     REAL,
    risk_score  REAL DEFAULT 0,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, timestamp)
);

-- Convert to hypertable if TimescaleDB available
SELECT create_hypertable('positions_history', 'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_pos_mmsi_ts ON positions_history(mmsi, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_pos_geom    ON positions_history USING GIST(geom);

-- ── Risk events / alerts ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS risk_events (
    id              TEXT PRIMARY KEY,
    vessel_mmsi     TEXT,
    vessel_name     TEXT,
    alert_type      TEXT NOT NULL,
    message         TEXT NOT NULL,
    priority        TEXT DEFAULT 'medium',
    risk_score      REAL DEFAULT 0,
    confidence      REAL DEFAULT 0,            -- 0-1 model confidence
    reasoning       TEXT,                      -- explainable AI reasoning
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    geom            GEOMETRY(Point, 4326),
    weather_context JSONB DEFAULT '{}',        -- weather at time of alert
    acknowledged    BOOLEAN DEFAULT FALSE,
    timestamp       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_ts       ON risk_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_priority ON risk_events(priority);
CREATE INDEX IF NOT EXISTS idx_events_mmsi     ON risk_events(vessel_mmsi);
CREATE INDEX IF NOT EXISTS idx_events_geom     ON risk_events USING GIST(geom);

-- ── Trajectory embeddings (pgvector) ─────────────────────────────────────────
-- 64-dim embedding of 10-step AIS trajectory window
-- Used for similarity search: "find vessels behaving like known threats"
CREATE TABLE IF NOT EXISTS trajectory_embeddings (
    id          BIGSERIAL PRIMARY KEY,
    mmsi        TEXT NOT NULL,
    embedding   vector(64) NOT NULL,           -- pgvector column
    label       TEXT DEFAULT 'normal',         -- normal / suspicious / threat
    risk_score  REAL DEFAULT 0,
    features    JSONB DEFAULT '{}',            -- raw features used
    timestamp   TIMESTAMPTZ DEFAULT NOW()
);

-- HNSW index for fast approximate nearest-neighbor search
CREATE INDEX IF NOT EXISTS idx_embed_hnsw ON trajectory_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_embed_mmsi ON trajectory_embeddings(mmsi);
CREATE INDEX IF NOT EXISTS idx_embed_label ON trajectory_embeddings(label);

-- ── Weather cache ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS weather_cache (
    grid_key    TEXT PRIMARY KEY,              -- "lat_lon" rounded to 0.5°
    lat         REAL,
    lon         REAL,
    data        JSONB NOT NULL,
    fetched_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_weather_fetched ON weather_cache(fetched_at);

-- ── Spatial zones ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS risk_zones (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    zone_type   TEXT NOT NULL,                 -- piracy / cyclone / restricted / fishing
    geom        GEOMETRY(Polygon, 4326) NOT NULL,
    risk_weight REAL DEFAULT 1.0,
    description TEXT,
    active      BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_zones_geom ON risk_zones USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_zones_type ON risk_zones(zone_type);

-- Insert default piracy zones
INSERT INTO risk_zones (name, zone_type, geom, risk_weight, description) VALUES
(
    'Gulf of Aden',
    'piracy',
    ST_GeomFromText('POLYGON((43 10, 52 10, 52 15, 43 15, 43 10))', 4326),
    0.9,
    'High piracy risk — Somali coast approach'
),
(
    'Somali Basin',
    'piracy',
    ST_GeomFromText('POLYGON((48 5, 65 5, 65 12, 48 12, 48 5))', 4326),
    0.85,
    'Somali Basin — offshore piracy zone'
),
(
    'Malacca Strait',
    'piracy',
    ST_GeomFromText('POLYGON((98 3, 101 3, 101 6, 98 6, 98 3))', 4326),
    0.7,
    'Malacca Strait — armed robbery risk'
)
ON CONFLICT DO NOTHING;
