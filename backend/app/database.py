"""
SQLite persistence layer for vessels and alerts.
Uses aiosqlite for async I/O — non-blocking with FastAPI.

Install: pip install aiosqlite
"""
import aiosqlite
import json
import logging
import os
from datetime import datetime, timezone
from app.models import Vessel, Alert

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'orvms.db')


async def init_db():
    """Create tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vessels (
                mmsi        TEXT PRIMARY KEY,
                name        TEXT,
                lat         REAL,
                lon         REAL,
                speed       REAL,
                heading     REAL,
                vessel_type TEXT,
                flag        TEXT,
                status      TEXT,
                trail       TEXT,        -- JSON array
                timestamp   TEXT,
                updated_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id           TEXT PRIMARY KEY,
                vessel_mmsi  TEXT,
                vessel_name  TEXT,
                alert_type   TEXT,
                message      TEXT,
                priority     TEXT,
                lat          REAL,
                lon          REAL,
                timestamp    TEXT,
                acknowledged INTEGER DEFAULT 0
            )
        """)
        # Index for fast queries
        await db.execute("CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(timestamp DESC)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_vessels_flag ON vessels(flag)")
        await db.commit()
    logger.info("Database initialised at %s", DB_PATH)


async def save_vessel(vessel: Vessel):
    """Upsert a vessel into SQLite."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO vessels (mmsi, name, lat, lon, speed, heading, vessel_type,
                                 flag, status, trail, timestamp, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(mmsi) DO UPDATE SET
                name=excluded.name, lat=excluded.lat, lon=excluded.lon,
                speed=excluded.speed, heading=excluded.heading,
                vessel_type=excluded.vessel_type, flag=excluded.flag,
                status=excluded.status, trail=excluded.trail,
                timestamp=excluded.timestamp, updated_at=datetime('now')
        """, (
            vessel.mmsi, vessel.name, vessel.lat, vessel.lon,
            vessel.speed, vessel.heading, vessel.vessel_type,
            vessel.flag, vessel.status,
            json.dumps(vessel.trail),
            vessel.timestamp.isoformat(),
        ))
        await db.commit()


async def save_alert(alert: Alert):
    """Insert a new alert (ignore duplicates by id)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO alerts
                (id, vessel_mmsi, vessel_name, alert_type, message,
                 priority, lat, lon, timestamp, acknowledged)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            alert.id, alert.vessel_mmsi, alert.vessel_name,
            alert.alert_type, alert.message, alert.priority,
            alert.lat, alert.lon,
            alert.timestamp.isoformat(),
            int(alert.acknowledged),
        ))
        await db.commit()


async def load_recent_vessels(limit: int = 8000) -> list[Vessel]:
    """Load most recently updated vessels on startup."""
    vessels = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM vessels ORDER BY updated_at DESC LIMIT ?", (limit,)
        ) as cur:
            async for row in cur:
                try:
                    vessels.append(Vessel(
                        mmsi=row["mmsi"], name=row["name"],
                        lat=row["lat"], lon=row["lon"],
                        speed=row["speed"], heading=row["heading"],
                        vessel_type=row["vessel_type"], flag=row["flag"],
                        status=row["status"],
                        trail=json.loads(row["trail"] or "[]"),
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                    ))
                except Exception as e:
                    logger.debug("Failed to load vessel %s: %s", row["mmsi"], e)
    logger.info("Loaded %d vessels from database", len(vessels))
    return vessels


async def load_recent_alerts(limit: int = 200) -> list[Alert]:
    """Load recent alerts on startup."""
    alerts = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?", (limit,)
        ) as cur:
            async for row in cur:
                try:
                    alerts.append(Alert(
                        id=row["id"], vessel_mmsi=row["vessel_mmsi"],
                        vessel_name=row["vessel_name"],
                        alert_type=row["alert_type"], message=row["message"],
                        priority=row["priority"],
                        lat=row["lat"], lon=row["lon"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        acknowledged=bool(row["acknowledged"]),
                    ))
                except Exception as e:
                    logger.debug("Failed to load alert %s: %s", row["id"], e)
    logger.info("Loaded %d alerts from database", len(alerts))
    return alerts


async def query_vessels_by_flag(flag: str) -> list[dict]:
    """Example analytics query — vessels by flag."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT mmsi, name, lat, lon, speed, vessel_type FROM vessels WHERE flag=?",
            (flag,)
        ) as cur:
            return [dict(row) async for row in cur]


async def get_alert_stats() -> dict:
    """Alert counts by priority for analytics."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT priority, COUNT(*) as count
            FROM alerts
            GROUP BY priority
        """) as cur:
            rows = [dict(row) async for row in cur]
    return {r["priority"]: r["count"] for r in rows}
