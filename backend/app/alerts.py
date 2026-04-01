"""
OceanGuard AI — Climate-Aware Alert Engine
==========================================
Three alert rules with explainable AI reasoning and climate context:
  1. High speed outside Indian boundary  → low
  2. Unfriendly vessel entering boundary → high
  3. Unfriendly vessel at high speed     → critical
  4. Any vessel entering piracy zone     → high (with weather context)
  5. Climate risk score threshold breach → medium/high/critical
"""
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from app.models import Vessel, Alert, WeatherSnapshot
from app.risk_engine import (
    compute_risk_score, predict_anomaly,
    FRIENDLY_FLAGS, PIRACY_ZONES, _in_india_eez, _in_zone
)
from app.weather import get_cached_weather

logger = logging.getLogger(__name__)

_alerts: list[Alert] = []
_MAX_ALERTS = 1000
_prev_states: dict[str, Vessel] = {}
_cooldowns: dict[str, datetime] = {}
COOLDOWN_SECS = 300
HIGH_SPEED_KN = 25.0


def _cooldown_ok(mmsi: str, rule: str) -> bool:
    key = f"{mmsi}:{rule}"
    last = _cooldowns.get(key)
    if last and (datetime.now(timezone.utc) - last).total_seconds() < COOLDOWN_SECS:
        return False
    _cooldowns[key] = datetime.now(timezone.utc)
    return True


def _add_alert(alert: Alert):
    for existing in _alerts[:20]:
        if existing.vessel_mmsi == alert.vessel_mmsi and existing.alert_type == alert.alert_type:
            age = (datetime.now(timezone.utc) - existing.timestamp).total_seconds()
            if age < COOLDOWN_SECS:
                return
    _alerts.insert(0, alert)
    if len(_alerts) > _MAX_ALERTS:
        _alerts.pop()
    logger.info("ALERT [%s] %.0f%% risk — %s", alert.priority.upper(),
                alert.risk_score, alert.message)
    # Async DB write (non-blocking)
    try:
        import asyncio
        from app.pg_store import save_alert_async
        asyncio.create_task(save_alert_async(alert))
    except Exception:
        pass


def _make_alert(vessel: Vessel, alert_type: str, message: str,
                priority: str, weather: Optional[WeatherSnapshot] = None) -> Alert:
    anomaly = predict_anomaly(vessel, weather)
    risk_score, _, reasoning, confidence = compute_risk_score(vessel, weather, anomaly)
    return Alert(
        id=str(uuid.uuid4()),
        vessel_mmsi=vessel.mmsi,
        vessel_name=vessel.name,
        alert_type=alert_type,
        message=message,
        priority=priority,
        risk_score=risk_score,
        confidence=confidence,
        reasoning=reasoning,
        lat=vessel.lat,
        lon=vessel.lon,
        weather_context=weather,
        timestamp=datetime.now(timezone.utc),
    )


def rule_high_speed_outside(vessel: Vessel, prev: Optional[Vessel],
                             weather: Optional[WeatherSnapshot]):
    if _in_india_eez(vessel.lat, vessel.lon):
        return
    if vessel.speed < HIGH_SPEED_KN:
        return
    if not _cooldown_ok(vessel.mmsi, "highspeed_outside"):
        return
    msg = f"{vessel.name or vessel.mmsi} at {vessel.speed:.1f} kn outside Indian boundary"
    if weather and weather.storm_index > 0.4:
        msg += f" — storm conditions (wave {weather.wave_height:.1f}m)"
    _add_alert(_make_alert(vessel, "high_speed_outside", msg, "low", weather))


def rule_unfriendly_entry(vessel: Vessel, prev: Optional[Vessel],
                           weather: Optional[WeatherSnapshot]):
    in_now = _in_india_eez(vessel.lat, vessel.lon)
    if not in_now:
        return
    was_inside = _in_india_eez(prev.lat, prev.lon) if prev else False
    if was_inside:
        return
    flag = (vessel.flag or "").strip()
    if not flag or flag == "Unknown" or flag in FRIENDLY_FLAGS:
        return
    if not _cooldown_ok(vessel.mmsi, "unfriendly_entry"):
        return

    if vessel.speed >= HIGH_SPEED_KN:
        priority = "critical"
        msg = (f"{vessel.name or vessel.mmsi} ({vessel.flag}) entering Indian boundary"
               f" at {vessel.speed:.1f} kn")
    else:
        priority = "high"
        msg = f"{vessel.name or vessel.mmsi} ({vessel.flag}) entering Indian maritime boundary"

    if weather and weather.storm_index > 0.3:
        msg += f" — adverse weather may mask approach (storm index {weather.storm_index:.2f})"

    _add_alert(_make_alert(vessel, f"unfriendly_entry{'_highspeed' if vessel.speed >= HIGH_SPEED_KN else ''}",
                           msg, priority, weather))


def rule_piracy_zone(vessel: Vessel, prev: Optional[Vessel],
                     weather: Optional[WeatherSnapshot]):
    """Alert when any vessel enters a piracy zone — with climate context."""
    for z in PIRACY_ZONES:
        in_now = _in_zone(vessel.lat, vessel.lon, z)
        was_in = _in_zone(prev.lat, prev.lon, z) if prev else False
        if in_now and not was_in and _cooldown_ok(vessel.mmsi, f"piracy_{z['name']}"):
            msg = f"{vessel.name or vessel.mmsi} entered {z['name']}"
            # Climate context — calm seas = higher piracy risk (skiff operations)
            if weather:
                if weather.wave_height < 1.5 and weather.wind_speed < 8:
                    msg += " — calm seas increase piracy skiff risk"
                elif weather.storm_index > 0.5:
                    msg += f" — storm forcing route through high-risk corridor"
            _add_alert(_make_alert(vessel, "piracy_zone_entry", msg, "high", weather))


def rule_climate_risk_threshold(vessel: Vessel, prev: Optional[Vessel],
                                 weather: Optional[WeatherSnapshot]):
    """Alert when composite climate risk score crosses a threshold."""
    if vessel.risk_score < 60:
        return
    if not _cooldown_ok(vessel.mmsi, "climate_risk"):
        return
    priority = "critical" if vessel.risk_score >= 80 else "high"
    msg = (f"{vessel.name or vessel.mmsi} — {vessel.risk_score:.0f}% Climate Risk Score. "
           f"{vessel.risk_label.upper()} threat level.")
    _add_alert(_make_alert(vessel, "climate_risk_threshold", msg, priority, weather))


RULES = [rule_high_speed_outside, rule_unfriendly_entry,
         rule_piracy_zone, rule_climate_risk_threshold]


class AlertEngine:
    def evaluate(self, vessel: Vessel):
        prev = _prev_states.get(vessel.mmsi)
        weather = get_cached_weather(vessel.lat, vessel.lon)
        for rule in RULES:
            try:
                rule(vessel, prev, weather)
            except Exception as exc:
                logger.debug("Rule %s error: %s", rule.__name__, exc)
        _prev_states[vessel.mmsi] = vessel

    def get_alerts(self, limit: int = 100) -> list[Alert]:
        return _alerts[:limit]

    def acknowledge(self, alert_id: str) -> bool:
        for a in _alerts:
            if a.id == alert_id:
                a.acknowledged = True
                return True
        return False


alert_engine = AlertEngine()
