"""
OceanGuard AI — Open-Meteo Marine Weather Service
Free, no API key required. Respects rate limits with in-memory + DB cache.

API docs: https://open-meteo.com/en/docs/marine-weather-api
"""
import asyncio
import logging
import time
from typing import Optional

import httpx

from app.models import WeatherSnapshot

logger = logging.getLogger(__name__)

# In-memory cache: grid_key → (WeatherSnapshot, timestamp)
_cache: dict[str, tuple[WeatherSnapshot, float]] = {}
CACHE_TTL_SECS = 1800   # 30 minutes — Open-Meteo updates hourly
GRID_RESOLUTION = 0.5   # round to nearest 0.5° to maximise cache hits
_fetch_semaphore = asyncio.Semaphore(5)  # max 5 concurrent API calls


def _grid_key(lat: float, lon: float) -> str:
    """Round to grid to maximise cache hits."""
    glat = round(round(lat / GRID_RESOLUTION) * GRID_RESOLUTION, 1)
    glon = round(round(lon / GRID_RESOLUTION) * GRID_RESOLUTION, 1)
    return f"{glat}_{glon}"


def _storm_index(w: dict) -> float:
    """
    Derive a 0-1 storm severity index from wave + wind data.
    Beaufort-inspired: wave > 4m or wind > 17 m/s = severe.
    """
    wave = float(w.get("wave_height_max", [0])[0] or 0)
    wind = float(w.get("wind_speed_10m_max", [0])[0] or 0)
    wave_score = min(wave / 8.0, 1.0)      # 8m = max
    wind_score = min(wind / 25.0, 1.0)     # 25 m/s = hurricane force
    return round((wave_score * 0.6 + wind_score * 0.4), 3)


async def fetch_weather(lat: float, lon: float) -> Optional[WeatherSnapshot]:
    """
    Fetch marine weather for a lat/lon point.
    Returns cached result if fresh, otherwise calls Open-Meteo.
    """
    key = _grid_key(lat, lon)
    now = time.time()

    # Check in-memory cache
    if key in _cache:
        snap, ts = _cache[key]
        if now - ts < CACHE_TTL_SECS:
            return snap

    glat = round(round(lat / GRID_RESOLUTION) * GRID_RESOLUTION, 1)
    glon = round(round(lon / GRID_RESOLUTION) * GRID_RESOLUTION, 1)

    async with _fetch_semaphore:
        try:
            url = "https://marine-api.open-meteo.com/v1/marine"
            params = {
                "latitude": glat,
                "longitude": glon,
                "daily": [
                    "wave_height_max",
                    "wave_period_max",
                    "wind_speed_10m_max",
                    "wind_direction_10m_dominant",
                    "swell_wave_height_max",
                ],
                "timezone": "UTC",
                "forecast_days": 1,
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(url, params=params)
                r.raise_for_status()
                data = r.json().get("daily", {})

            snap = WeatherSnapshot(
                wave_height=float((data.get("wave_height_max") or [0])[0] or 0),
                wave_period=float((data.get("wave_period_max") or [0])[0] or 0),
                wind_speed=float((data.get("wind_speed_10m_max") or [0])[0] or 0),
                wind_direction=float((data.get("wind_direction_10m_dominant") or [0])[0] or 0),
                swell_height=float((data.get("swell_wave_height_max") or [0])[0] or 0),
                sea_surface_temp=27.0,  # Open-Meteo free tier doesn't include SST
                storm_index=_storm_index(data),
                fetched_at=str(int(now)),
            )
            _cache[key] = (snap, now)
            return snap

        except Exception as e:
            logger.debug("Weather fetch failed for %s,%s: %s", glat, glon, e)
            # Return last cached even if stale, or a neutral default
            if key in _cache:
                return _cache[key][0]
            return WeatherSnapshot()  # neutral defaults


def get_cached_weather(lat: float, lon: float) -> Optional[WeatherSnapshot]:
    """Synchronous cache lookup — for use in hot paths."""
    key = _grid_key(lat, lon)
    if key in _cache:
        snap, ts = _cache[key]
        if time.time() - ts < CACHE_TTL_SECS * 2:  # allow 2x stale in hot path
            return snap
    return None


async def prefetch_zone_weather():
    """
    Pre-warm cache for the three high-risk zones on startup.
    Runs as a background task every 30 minutes.
    """
    ZONE_CENTERS = [
        (12.5, 47.5, "Gulf of Aden"),
        (8.5,  56.0, "Somali Basin"),
        (4.5,  99.5, "Malacca Strait"),
        (15.0, 72.0, "Arabian Sea"),
        (10.0, 85.0, "Bay of Bengal"),
    ]
    while True:
        for lat, lon, name in ZONE_CENTERS:
            snap = await fetch_weather(lat, lon)
            if snap:
                logger.info("Weather prefetch %s: wave=%.1fm wind=%.1fm/s storm=%.2f",
                            name, snap.wave_height, snap.wind_speed, snap.storm_index)
            await asyncio.sleep(1)  # rate limit
        await asyncio.sleep(CACHE_TTL_SECS)
