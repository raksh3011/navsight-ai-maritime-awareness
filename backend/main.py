"""
OceanGuard AI — Backend Entry Point
Run: uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
import asyncio
import logging
import os

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app import config
from app.api import router, broadcast_loop
from app.ingestion import ingestion_loop
from app.weather import prefetch_zone_weather

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="OceanGuard AI — Climate & Environment Risk API",
    description="Real-time AI-fused maritime climate risk intelligence",
    version="2.0.0",
)

app.add_middleware(CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(router)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend')
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(FRONTEND_DIR, 'index.html'))

    @app.get("/{filename}")
    async def serve_file(filename: str):
        path = os.path.join(FRONTEND_DIR, filename)
        if os.path.exists(path):
            return FileResponse(path)
        return FileResponse(os.path.join(FRONTEND_DIR, 'index.html'))


@app.on_event("startup")
async def startup():
    logger.info("OceanGuard AI starting up...")

    # Init PostgreSQL pool (non-fatal if unavailable)
    try:
        from app.pg_store import init_pool, load_vessels_from_db, load_alerts_from_db
        from app.store import vessel_store
        from app.alerts import _alerts
        await init_pool()
        saved = await load_vessels_from_db()
        for v in saved:
            vessel_store._vessels[v.mmsi] = v
        saved_alerts = await load_alerts_from_db(200)
        _alerts.extend(saved_alerts)
        logger.info("Restored %d vessels, %d alerts from PostgreSQL",
                    len(saved), len(saved_alerts))
    except Exception as e:
        logger.warning("PostgreSQL unavailable (%s) — using RAM store", e)

    asyncio.create_task(ingestion_loop())
    asyncio.create_task(broadcast_loop())
    asyncio.create_task(prefetch_zone_weather())
    logger.info("All background tasks started. Server ready.")


@app.on_event("shutdown")
async def shutdown():
    logger.info("OceanGuard AI shutting down.")


if __name__ == "__main__":
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
