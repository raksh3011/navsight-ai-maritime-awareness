"""
OceanGuard AI — Trajectory Embedding Engine
============================================
Converts AIS trajectory windows into 64-dim vectors stored in pgvector.
Enables similarity search: "find vessels behaving like known threats."

Embedding approach: lightweight hand-crafted features (no GPU needed)
  - Speed/heading statistics over 10-step window
  - Zone proximity features
  - Weather context features
  - Normalized to unit sphere for cosine similarity
"""
import math
import logging
import numpy as np
from typing import List, Optional

from app.models import Vessel, WeatherSnapshot
from app.risk_engine import _zone_risk, _in_india_eez, FRIENDLY_FLAGS

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 64
WINDOW_SIZE = 10  # trajectory steps per embedding


def _safe_norm(v: np.ndarray) -> np.ndarray:
    """Normalize to unit vector for cosine similarity."""
    norm = np.linalg.norm(v)
    return v / norm if norm > 1e-8 else v


def build_trajectory_embedding(
    trail: List[List[float]],
    vessel: Vessel,
    weather: Optional[WeatherSnapshot] = None,
) -> np.ndarray:
    """
    Build a 64-dim embedding from a vessel's recent trajectory.

    Sections:
      [0:10]  — speed profile (normalized, padded)
      [10:20] — heading sin values
      [20:30] — heading cos values
      [30:40] — lat deltas (movement pattern)
      [40:50] — lon deltas
      [50:56] — zone/context features
      [56:60] — weather features
      [60:64] — vessel identity features
    """
    emb = np.zeros(EMBEDDING_DIM, dtype=np.float32)

    # Use trail + current position
    positions = trail[-WINDOW_SIZE:] + [[vessel.lat, vessel.lon]]
    n = len(positions)

    # Speed profile (approximate from position deltas)
    speeds = []
    headings = []
    lat_deltas = []
    lon_deltas = []

    for i in range(1, n):
        dlat = positions[i][0] - positions[i-1][0]
        dlon = positions[i][1] - positions[i-1][1]
        dist = math.sqrt(dlat**2 + dlon**2) * 111  # rough km
        speeds.append(min(dist * 20, 1.0))  # normalised speed proxy
        heading = math.degrees(math.atan2(dlon, dlat)) % 360
        headings.append(heading)
        lat_deltas.append(dlat * 100)
        lon_deltas.append(dlon * 100)

    # Pad to WINDOW_SIZE
    def pad(lst, size):
        lst = lst[-size:]
        return lst + [0.0] * (size - len(lst))

    speeds_p   = pad(speeds, 10)
    headings_p = pad(headings, 10)
    lat_d_p    = pad(lat_deltas, 10)
    lon_d_p    = pad(lon_deltas, 10)

    emb[0:10]  = np.clip(speeds_p, -1, 1)
    emb[10:20] = [math.sin(math.radians(h)) for h in headings_p]
    emb[20:30] = [math.cos(math.radians(h)) for h in headings_p]
    emb[30:40] = np.clip(lat_d_p, -1, 1)
    emb[40:50] = np.clip(lon_d_p, -1, 1)

    # Zone/context features [50:56]
    zone_r, _ = _zone_risk(vessel.lat, vessel.lon)
    in_eez = float(_in_india_eez(vessel.lat, vessel.lon))
    emb[50] = zone_r
    emb[51] = in_eez
    emb[52] = min(vessel.speed / 30.0, 1.0)
    emb[53] = float(vessel.flag not in FRIENDLY_FLAGS)
    emb[54] = float(vessel.vessel_type in ("Unknown", "Fishing Vessel"))
    emb[55] = float(len(trail) < 3)  # sparse trail = suspicious

    # Weather features [56:60]
    if weather:
        emb[56] = min(weather.wave_height / 6.0, 1.0)
        emb[57] = min(weather.wind_speed / 20.0, 1.0)
        emb[58] = weather.storm_index
        emb[59] = min(weather.swell_height / 4.0, 1.0)

    # Vessel identity features [60:64]
    emb[60] = min(vessel.lat / 90.0, 1.0)
    emb[61] = min(vessel.lon / 180.0, 1.0)
    emb[62] = float(vessel.heading / 360.0)
    emb[63] = float(vessel.speed / 30.0)

    return _safe_norm(emb)


def embedding_to_list(emb: np.ndarray) -> List[float]:
    """Convert numpy array to Python list for pgvector storage."""
    return emb.tolist()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two embeddings."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))
