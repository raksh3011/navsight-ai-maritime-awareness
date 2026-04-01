"""
HOW TO WIRE database.py INTO THE EXISTING SYSTEM
=================================================
This file shows exactly what to change in main.py, store.py, and alerts.py
to enable SQLite persistence. Copy the relevant snippets.
"""

# ── 1. main.py — init DB on startup, load saved data ─────────────────────────
MAIN_PY_STARTUP = """
@app.on_event("startup")
async def startup():
    from app.database import init_db, load_recent_vessels, load_recent_alerts
    from app.store import vessel_store
    from app.alerts import _alerts

    # Init tables
    await init_db()

    # Restore vessels from last session
    saved_vessels = await load_recent_vessels()
    for v in saved_vessels:
        vessel_store._vessels[v.mmsi] = v

    # Restore alerts from last session
    saved_alerts = await load_recent_alerts(200)
    _alerts.extend(saved_alerts)

    asyncio.create_task(ingestion_loop())
    asyncio.create_task(broadcast_loop())
"""

# ── 2. store.py — save to DB on every upsert ─────────────────────────────────
STORE_PY_UPSERT = """
# Add to the end of VesselStore.upsert(), after self._vessels[mmsi] = vessel:

    import asyncio
    from app.database import save_vessel
    asyncio.create_task(save_vessel(vessel))   # non-blocking async write
    return True
"""

# ── 3. alerts.py — persist every new alert ───────────────────────────────────
ALERTS_PY_ADD = """
# Add to the end of _add_alert(), after _alerts.insert(0, alert):

    import asyncio
    from app.database import save_alert
    asyncio.create_task(save_alert(alert))     # non-blocking async write
"""

# ── 4. New API endpoints to add in api.py ────────────────────────────────────
NEW_ENDPOINTS = """
from app.database import query_vessels_by_flag, get_alert_stats

@router.get("/analytics/alerts")
async def alert_stats():
    return await get_alert_stats()

@router.get("/vessels/flag/{flag}")
async def vessels_by_flag(flag: str):
    return await query_vessels_by_flag(flag)
"""
