"""
OceanGuard AI — Climate Risk Engine
====================================
Computes a 0-100 Climate Risk Score per vessel by fusing:
  1. Marine weather severity (Open-Meteo)
  2. Behavioral anomaly (Isolation Forest + trajectory similarity)
  3. Zone risk (piracy zones, EEZ boundary)
  4. Vessel vulnerability (type, flag, speed profile)

Designed for CPU-only inference, <5ms per vessel, 20k+ vessel throughput.
"""
import logging
import math
import numpy as np
from typing import Optional, Tuple

from app.models import Vessel, WeatherSnapshot

logger = logging.getLogger(__name__)

# ── Friendly flags (lower zone risk weight) ───────────────────────────────────
FRIENDLY_FLAGS = {
    "India", "USA", "UK", "France", "Australia", "Japan", "South Korea",
    "New Zealand", "Canada", "Germany", "Italy", "Norway", "Netherlands",
    "Denmark", "Sweden", "Finland", "Portugal", "Spain", "Greece",
}

# ── Piracy zone bounding boxes ────────────────────────────────────────────────
PIRACY_ZONES = [
    {"name": "Gulf of Aden",   "latMin": 10, "latMax": 15, "lonMin": 43, "lonMax": 52, "weight": 0.90},
    {"name": "Somali Basin",   "latMin":  5, "latMax": 12, "lonMin": 48, "lonMax": 65, "weight": 0.85},
    {"name": "Malacca Strait", "latMin":  3, "latMax":  6, "lonMin": 98, "lonMax":101, "weight": 0.70},
]

# India EEZ polygon (simplified bounding box for fast check)
INDIA_EEZ = {"latMin": 2, "latMax": 24, "lonMin": 62, "lonMax": 97}

# ── Vessel vulnerability weights by type ─────────────────────────────────────
VESSEL_VULNERABILITY = {
    "Fishing Vessel":  0.90,   # slow, low freeboard, high piracy target
    "Tanker":          0.75,   # high value cargo
    "Cargo Ship":      0.65,
    "Container Ship":  0.60,
    "Passenger Ship":  0.80,   # high consequence
    "Naval Vessel":    0.20,   # armed, low vulnerability
    "Coast Guard":     0.15,
    "Unknown":         0.85,   # unknown = assume vulnerable
}


def _in_zone(lat: float, lon: float, zone: dict) -> bool:
    return (zone["latMin"] <= lat <= zone["latMax"] and
            zone["lonMin"] <= lon <= zone["lonMax"])


def _in_india_eez(lat: float, lon: float) -> bool:
    return (INDIA_EEZ["latMin"] <= lat <= INDIA_EEZ["latMax"] and
            INDIA_EEZ["lonMin"] <= lon <= INDIA_EEZ["lonMax"])


def _weather_risk(w: Optional[WeatherSnapshot]) -> float:
    """
    Convert weather snapshot to 0-1 risk score.
    High waves + high wind + storm = high risk.
    """
    if not w:
        return 0.1  # unknown weather = slight risk
    wave_r  = min(w.wave_height / 6.0, 1.0)    # 6m = max reference
    wind_r  = min(w.wind_speed / 20.0, 1.0)    # 20 m/s = storm
    storm_r = w.storm_index
    swell_r = min(w.swell_height / 4.0, 1.0)
    # Weighted combination
    return round(wave_r * 0.35 + wind_r * 0.30 + storm_r * 0.25 + swell_r * 0.10, 3)


def _zone_risk(lat: float, lon: float) -> Tuple[float, str]:
    """Return zone risk weight and zone name."""
    for z in PIRACY_ZONES:
        if _in_zone(lat, lon, z):
            return z["weight"], z["name"]
    # Near zone buffer (~1°)
    for z in PIRACY_ZONES:
        if (z["latMin"] - 1 <= lat <= z["latMax"] + 1 and
                z["lonMin"] - 1 <= lon <= z["lonMax"] + 1):
            return z["weight"] * 0.5, f"Near {z['name']}"
    return 0.0, ""


def _behavioral_risk(vessel: Vessel) -> float:
    """
    Lightweight behavioral anomaly score without ML model.
    Used as fallback when IsolationForest model not loaded.
    Factors: speed anomaly, heading variance, dark vessel indicators.
    """
    score = 0.0
    # High speed in piracy zone
    zone_r, _ = _zone_risk(vessel.lat, vessel.lon)
    if zone_r > 0.5 and vessel.speed > 15:
        score += 0.3
    # Very high speed anywhere
    if vessel.speed > 25:
        score += 0.2
    # Unknown flag in sensitive area
    if vessel.flag in ("Unknown", "") and _in_india_eez(vessel.lat, vessel.lon):
        score += 0.25
    # Unfriendly flag entering EEZ
    if vessel.flag not in FRIENDLY_FLAGS and vessel.flag not in ("Unknown", ""):
        if _in_india_eez(vessel.lat, vessel.lon):
            score += 0.2
    return min(score, 1.0)


def _vulnerability(vessel: Vessel) -> float:
    return VESSEL_VULNERABILITY.get(vessel.vessel_type or "Unknown", 0.65)


def compute_risk_score(
    vessel: Vessel,
    weather: Optional[WeatherSnapshot] = None,
    anomaly_score: float = 0.0,
) -> Tuple[float, str, str, float]:
    """
    Compute composite Climate Risk Score (0-100).

    Formula:
        risk = (weather_risk × 0.30) +
               (zone_risk    × 0.35) +
               (behavioral   × 0.25) +
               (vulnerability× 0.10)
        × 100

    Returns: (score, label, reasoning, confidence)
    """
    w_risk = _weather_risk(weather)
    z_risk, zone_name = _zone_risk(vessel.lat, vessel.lon)
    b_risk = max(anomaly_score, _behavioral_risk(vessel))
    v_risk = _vulnerability(vessel)

    raw = (w_risk * 0.30 + z_risk * 0.35 + b_risk * 0.25 + v_risk * 0.10)
    score = round(min(raw * 100, 100), 1)

    # Label
    if score >= 75:
        label = "critical"
    elif score >= 50:
        label = "high"
    elif score >= 25:
        label = "medium"
    else:
        label = "low"

    # Confidence — higher when multiple factors agree
    factors_active = sum([w_risk > 0.3, z_risk > 0.3, b_risk > 0.3])
    confidence = round(0.5 + factors_active * 0.15, 2)

    # Explainable reasoning
    parts = []
    if w_risk > 0.4:
        parts.append(f"severe weather (wave {weather.wave_height:.1f}m, wind {weather.wind_speed:.1f}m/s)" if weather else "adverse weather")
    if z_risk > 0.3:
        parts.append(f"in {zone_name} piracy zone")
    if b_risk > 0.3:
        parts.append("anomalous vessel behavior")
    if vessel.flag not in FRIENDLY_FLAGS and vessel.flag not in ("Unknown", ""):
        parts.append(f"unfriendly flag ({vessel.flag})")
    if vessel.speed > 25:
        parts.append(f"high speed ({vessel.speed:.1f} kn)")

    reasoning = f"{score:.0f}% Climate Risk"
    if parts:
        reasoning += " — " + "; ".join(parts)
    if score >= 50 and zone_name:
        reasoning += f". AI-recommended: avoid {zone_name} corridor."

    return score, label, reasoning, confidence


# ── Isolation Forest (lightweight, CPU, sklearn) ──────────────────────────────
try:
    from sklearn.ensemble import IsolationForest
    import joblib
    import os

    _MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', 'models', 'isolation_forest.joblib')
    _iso_model = None

    def load_anomaly_model():
        global _iso_model
        if os.path.exists(_MODEL_PATH):
            _iso_model = joblib.load(_MODEL_PATH)
            logger.info("Isolation Forest model loaded from %s", _MODEL_PATH)
        else:
            logger.info("No pre-trained model found — using rule-based anomaly scoring")

    def extract_features(vessel: Vessel, weather: Optional[WeatherSnapshot]) -> np.ndarray:
        """Extract 10-dim feature vector for anomaly detection."""
        w = weather or WeatherSnapshot()
        zone_r, _ = _zone_risk(vessel.lat, vessel.lon)
        in_eez = float(_in_india_eez(vessel.lat, vessel.lon))
        return np.array([
            vessel.speed / 30.0,
            vessel.heading / 360.0,
            abs(math.sin(math.radians(vessel.heading))),  # heading variance proxy
            zone_r,
            in_eez,
            w.wave_height / 8.0,
            w.wind_speed / 25.0,
            w.storm_index,
            float(vessel.flag not in FRIENDLY_FLAGS),
            float(vessel.vessel_type in ("Unknown", "Fishing Vessel")),
        ], dtype=np.float32)

    def predict_anomaly(vessel: Vessel, weather: Optional[WeatherSnapshot]) -> float:
        """Return 0-1 anomaly score. 1 = highly anomalous."""
        if _iso_model is None:
            return _behavioral_risk(vessel)
        try:
            features = extract_features(vessel, weather).reshape(1, -1)
            # IsolationForest: -1 = anomaly, 1 = normal
            # score_samples returns negative anomaly score
            raw = _iso_model.score_samples(features)[0]
            # Normalise to 0-1 (typical range -0.5 to 0.5)
            normalised = max(0.0, min(1.0, (-raw - 0.1) / 0.4))
            return round(float(normalised), 3)
        except Exception as e:
            logger.debug("Anomaly model error: %s", e)
            return _behavioral_risk(vessel)

except ImportError:
    logger.warning("scikit-learn not installed — using rule-based anomaly scoring")

    def load_anomaly_model(): pass
    def extract_features(vessel, weather): return np.zeros(10)
    def predict_anomaly(vessel, weather): return _behavioral_risk(vessel)
