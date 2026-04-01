"""
OceanGuard AI — PostgreSQL + PostGIS + pgvector async store
============================================================
Replaces the in-memory dict store with persistent Postgres.
Uses asyncpg connection pool for 20k+ vessel throughput.

Connection pool: min=5, max=20 connections
Batch upsert: groups vessel writes into batches of 100 for efficiency
"""
import asyncio
import json
import logging
import os
from typing import Optional, List

try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

from app.models import Vessel, Alert
from app.store import VesselStore, vessel_store  # fallback to RAM store

logger = logging.getLogger(__name__)

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/oceanguard"
)

_pool: Optional[object] = None
_write_queue: asyncio.Queue = asyncio.Queue(maxsize=50000)
_alert_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)


async def init_pool():
    """Initialize asyncpg connection pool."""
    global _pool
    if not HAS_ASYNCPG:
        logger.warning("asyncpg not installed — using RAM store only")
        return
    try:
        _pool = await asyncpg.create_pool(
            DB_URL,
            min_size=5,
            max_size=20,
            command_timeout=10,
            statement_cache_size=100,
        )
        logger.info("PostgreSQL pool initialized: %s", DB_URL)
        # Start background writer
        asyncio.create_task(_batch_writer())
        asyncio.create_task(_alert_writer())
    except Exception as e:
        logger.error("PostgreSQL connection failed: %s — using RAM store", e)
        _pool = None


async def _batch_writer():
    """
    Drain the write queue in batches of 100.
    This decouples ingestion speed from DB write speed.
    Target: 20k vessels/s ingestion, ~200 DB writes/s in batches.
    """
    batch = []
    while True:
        try:
            # Collect up to 100 vessels or wait 100ms
            try:
                while len(batch) < 100:
                    vessel = await asyncio.wait_for(_write_queue.get(), timeout=0.1)
                    batch.append(vessel)
            except asyncio.TimeoutError:
                pass

            if batch and _pool:
                await _upsert_vessels_batch(batch)
                batch = []
        except Exception as e:
            logger.debug("Batch writer error: %s", e)
            batch = []
            await asyncio.sleep(0.5)


async def _alert_writer():
    """Write alerts to Postgres asynchronously."""
    while True:
        try:
            alert = await _alert_queue.get()
            if _pool:
                await _insert_alert(alert)
        except Exception as e:
            logger.debug("Alert writer error: %s", e)


async def _upsert_vessels_batch(vessels: List[Vessel]):
    """Batch upsert vessels using COPY-style efficiency."""
    if not _pool:
        return
    async with _pool.acquire() as conn:
        await conn.executemany("""
            INSERT INTO vessels (mmsi, name, lat, lon, speed, heading, course,
                vessel_type, flag, status, trail, risk_score, anomaly_score,
                risk_label, last_weather, timestamp)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
            ON CONFLICT (mmsi) DO UPDATE SET
                name=EXCLUDED.name, lat=EXCLUDED.lat, lon=EXCLUDED.lon,
                speed=EXCLUDED.speed, heading=EXCLUDED.heading,
                course=EXCLUDED.course, vessel_type=EXCLUDED.vessel_type,
                flag=EXCLUDED.flag, status=EXCLUDED.status,
                trail=EXCLUDED.trail, risk_score=EXCLUDED.risk_score,
                anomaly_score=EXCLUDED.anomaly_score,
                risk_label=EXCLUDED.risk_label,
                last_weather=EXCLUDED.last_weather,
                timestamp=EXCLUDED.timestamp,
                updated_at=NOW()
        """, [
            (
                v.mmsi, v.name, v.lat, v.lon, v.speed, v.heading, v.course,
                v.vessel_type, v.flag, v.status,
                json.dumps(v.trail),
                v.risk_score, v.anomaly_score, v.risk_label,
                json.dumps(v.weather.dict() if v.weather else {}),
                v.timestamp,
            )
            for v in vessels
        ])


async def _insert_alert(alert: Alert):
    if not _pool:
        return
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO risk_events
                (id, vessel_mmsi, vessel_name, alert_type, message, priority,
                 risk_score, confidence, reasoning, lat, lon, weather_context, timestamp)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            ON CONFLICT (id) DO NOTHING
        """, (
            alert.id, alert.vessel_mmsi, alert.vessel_name,
            alert.alert_type, alert.message, alert.priority,
            alert.risk_score, alert.confidence, alert.reasoning,
            alert.lat, alert.lon,
            json.dumps(alert.weather_context.dict() if alert.weather_context else {}),
            alert.timestamp,
        ))


async def save_vessel_async(vessel: Vessel):
    """Queue vessel for async DB write. Non-blocking."""
    try:
        _write_queue.put_nowait(vessel)
    except asyncio.QueueFull:
        pass  # drop under extreme load — RAM store is source of truth


async def save_alert_async(alert: Alert):
    """Queue alert for async DB write."""
    try:
        _alert_queue.put_nowait(alert)
    except asyncio.QueueFull:
        pass


async def load_vessels_from_db(limit: int = 8000) -> List[Vessel]:
    """Restore vessel state from Postgres on startup."""
    if not _pool:
        return []
    vessels = []
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM vessels ORDER BY updated_at DESC LIMIT $1", limit
        )
        for row in rows:
            try:
                vessels.append(Vessel(
                    mmsi=row["mmsi"], name=row["name"],
                    lat=row["lat"], lon=row["lon"],
                    speed=row["speed"], heading=row["heading"],
                    vessel_type=row["vessel_type"], flag=row["flag"],
                    status=row["status"],
                    trail=json.loads(row["trail"] or "[]"),
                    risk_score=row["risk_score"] or 0,
                    anomaly_score=row["anomaly_score"] or 0,
                    risk_label=row["risk_label"] or "low",
                    timestamp=row["timestamp"],
                ))
            except Exception:
                pass
    logger.info("Restored %d vessels from PostgreSQL", len(vessels))
    return vessels


async def load_alerts_from_db(limit: int = 500) -> List[Alert]:
    """Restore recent alerts from Postgres on startup."""
    if not _pool:
        return []
    alerts = []
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM risk_events ORDER BY timestamp DESC LIMIT $1", limit
        )
        for row in rows:
            try:
                alerts.append(Alert(
                    id=row["id"], vessel_mmsi=row["vessel_mmsi"],
                    vessel_name=row["vessel_name"],
                    alert_type=row["alert_type"], message=row["message"],
                    priority=row["priority"],
                    risk_score=row["risk_score"] or 0,
                    confidence=row["confidence"] or 0,
                    reasoning=row["reasoning"],
                    lat=row["lat"], lon=row["lon"],
                    timestamp=row["timestamp"],
                    acknowledged=row["acknowledged"] or False,
                ))
            except Exception:
                pass
    return alerts


async def spatial_query_vessels_in_zone(
    lat_min: float, lat_max: float, lon_min: float, lon_max: float
) -> List[dict]:
    """PostGIS spatial query — vessels in a bounding box."""
    if not _pool:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT mmsi, name, lat, lon, speed, vessel_type, flag, risk_score
            FROM vessels
            WHERE ST_Within(
                geom,
                ST_MakeEnvelope($1, $2, $3, $4, 4326)
            )
            ORDER BY risk_score DESC
            LIMIT 500
        """, lon_min, lat_min, lon_max, lat_max)
        return [dict(r) for r in rows]


async def get_risk_heatmap(resolution: float = 2.0) -> List[dict]:
    """
    Generate risk heatmap data using PostGIS grid aggregation.
    Returns grid cells with average risk score for frontend visualization.
    """
    if not _pool:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT
                ROUND(lat::numeric / {resolution}) * {resolution} AS grid_lat,
                ROUND(lon::numeric / {resolution}) * {resolution} AS grid_lon,
                AVG(risk_score) AS avg_risk,
                COUNT(*) AS vessel_count
            FROM vessels
            WHERE risk_score > 10
            GROUP BY grid_lat, grid_lon
            HAVING COUNT(*) > 0
            ORDER BY avg_risk DESC
            LIMIT 200
        """)
        return [dict(r) for r in rows]
