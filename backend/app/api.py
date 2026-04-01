"""
OceanGuard AI — FastAPI Routes
REST + WebSocket + Climate Risk endpoints
"""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import JSONResponse

from app.store import vessel_store
from app.alerts import alert_engine
from app.models import Vessel
from app import config

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self._clients:
            self._clients.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self._clients:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self._clients:
                self._clients.remove(ws)


manager = ConnectionManager()


async def broadcast_loop():
    """Push vessel + risk updates every POLL_INTERVAL seconds."""
    while True:
        await asyncio.sleep(config.POLL_INTERVAL)
        if not manager._clients:
            continue
        vessels = [v.model_dump(mode="json") for v in vessel_store.all()]
        alerts = [a.model_dump(mode="json") for a in alert_engine.get_alerts(50)]
        await manager.broadcast({
            "type": "update",
            "vessels": vessels,
            "alerts": alerts,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total": len(vessels),
        })


# ── Health ────────────────────────────────────────────────────────────────────
@router.get("/health")
async def health():
    return {
        "status": "ok",
        "provider": config.AIS_PROVIDER,
        "vessels_tracked": vessel_store.count(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "OceanGuard-AI-2.0",
    }


# ── Vessels ───────────────────────────────────────────────────────────────────
@router.get("/vessels/live")
async def get_live_vessels():
    vessels = [v.model_dump(mode="json") for v in vessel_store.all()]
    return JSONResponse({
        "vessels": vessels,
        "total": len(vessels),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@router.get("/vessels/{mmsi}")
async def get_vessel(mmsi: str):
    vessel = vessel_store.get(mmsi)
    if not vessel:
        raise HTTPException(status_code=404, detail="Vessel not found")
    return vessel.model_dump(mode="json")


@router.delete("/vessels/{mmsi}")
async def delete_vessel(mmsi: str):
    if not vessel_store.get(mmsi):
        raise HTTPException(status_code=404, detail="Vessel not found")
    vessel_store.delete(mmsi)
    return {"deleted": True, "mmsi": mmsi}


@router.post("/vessels/manual")
async def add_manual_vessel(vessel: Vessel):
    vessel_store.upsert(vessel)
    return {"added": True, "mmsi": vessel.mmsi}


# ── Risk scores ───────────────────────────────────────────────────────────────
@router.get("/risk/vessel/{mmsi}")
async def get_vessel_risk(mmsi: str):
    """Get detailed climate risk score for a specific vessel."""
    vessel = vessel_store.get(mmsi)
    if not vessel:
        raise HTTPException(status_code=404, detail="Vessel not found")
    return {
        "mmsi": vessel.mmsi,
        "name": vessel.name,
        "risk_score": vessel.risk_score,
        "risk_label": vessel.risk_label,
        "anomaly_score": vessel.anomaly_score,
        "weather": vessel.weather.dict() if vessel.weather else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/risk/top")
async def get_top_risk_vessels(limit: int = Query(20, le=100)):
    """Get vessels sorted by climate risk score."""
    all_vessels = vessel_store.all()
    sorted_vessels = sorted(all_vessels, key=lambda v: v.risk_score, reverse=True)
    return JSONResponse({
        "vessels": [v.model_dump(mode="json") for v in sorted_vessels[:limit]],
        "total": len(sorted_vessels),
    })


@router.get("/risk/heatmap")
async def get_risk_heatmap():
    """Risk heatmap data for frontend visualization."""
    try:
        from app.pg_store import get_risk_heatmap
        data = await get_risk_heatmap()
        if data:
            return JSONResponse({"heatmap": data})
    except Exception:
        pass
    # Fallback: compute from RAM store
    from collections import defaultdict
    grid = defaultdict(list)
    for v in vessel_store.all():
        key = (round(v.lat / 2) * 2, round(v.lon / 2) * 2)
        grid[key].append(v.risk_score)
    heatmap = [
        {"lat": k[0], "lon": k[1], "avg_risk": sum(v)/len(v), "count": len(v)}
        for k, v in grid.items() if sum(v)/len(v) > 10
    ]
    return JSONResponse({"heatmap": sorted(heatmap, key=lambda x: -x["avg_risk"])[:200]})


# ── Alerts ────────────────────────────────────────────────────────────────────
@router.get("/alerts")
async def get_alerts(limit: int = Query(100, le=1000)):
    alerts = [a.model_dump(mode="json") for a in alert_engine.get_alerts(limit)]
    return JSONResponse({"alerts": alerts, "total": len(alerts)})


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(alert_id: str):
    if not alert_engine.acknowledge(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"acknowledged": True}


# ── Spatial queries (PostGIS) ─────────────────────────────────────────────────
@router.get("/spatial/vessels")
async def vessels_in_bbox(
    lat_min: float = Query(...), lat_max: float = Query(...),
    lon_min: float = Query(...), lon_max: float = Query(...),
):
    """PostGIS spatial query — vessels in bounding box."""
    try:
        from app.pg_store import spatial_query_vessels_in_zone
        data = await spatial_query_vessels_in_zone(lat_min, lat_max, lon_min, lon_max)
        return JSONResponse({"vessels": data, "total": len(data)})
    except Exception:
        # Fallback to RAM
        result = [
            v.model_dump(mode="json") for v in vessel_store.all()
            if lat_min <= v.lat <= lat_max and lon_min <= v.lon <= lon_max
        ]
        return JSONResponse({"vessels": result, "total": len(result)})


# ── WebSocket ─────────────────────────────────────────────────────────────────
@router.websocket("/ws/vessels")
async def websocket_vessels(ws: WebSocket):
    await manager.connect(ws)
    # Send immediate snapshot
    vessels = [v.model_dump(mode="json") for v in vessel_store.all()]
    alerts = [a.model_dump(mode="json") for a in alert_engine.get_alerts(50)]
    await ws.send_json({
        "type": "snapshot",
        "vessels": vessels,
        "alerts": alerts,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(vessels),
    })
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
