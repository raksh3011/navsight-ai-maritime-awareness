"""
OceanGuard AI — Unified data models.
Extends base vessel/alert with climate risk scoring and embeddings.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class WeatherSnapshot(BaseModel):
    """Marine weather at a geographic point."""
    wave_height: float = 0.0        # metres
    wave_period: float = 0.0        # seconds
    wind_speed: float = 0.0         # m/s
    wind_direction: float = 0.0     # degrees
    swell_height: float = 0.0       # metres
    sea_surface_temp: float = 25.0  # °C
    visibility: float = 10.0        # km (proxy)
    storm_index: float = 0.0        # 0-1 derived severity
    fetched_at: Optional[str] = None


class Vessel(BaseModel):
    """Normalized vessel state with climate risk fields."""
    mmsi: str
    name: Optional[str] = "Unknown"
    lat: float
    lon: float
    speed: float = 0.0
    heading: float = 0.0
    course: float = 0.0
    vessel_type: Optional[str] = "Unknown"
    flag: Optional[str] = "Unknown"
    imo: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: Optional[str] = "underway"
    trail: List[List[float]] = Field(default_factory=list)
    # Climate Risk fields
    risk_score: float = 0.0         # 0-100 composite Climate Risk Score
    anomaly_score: float = 0.0      # 0-1 behavioral anomaly
    risk_label: str = "low"         # low / medium / high / critical
    weather: Optional[WeatherSnapshot] = None


class Alert(BaseModel):
    id: str
    vessel_mmsi: Optional[str] = None
    vessel_name: Optional[str] = None
    alert_type: str
    message: str
    priority: str = "medium"
    risk_score: float = 0.0
    confidence: float = 0.0         # 0-1 model confidence
    reasoning: Optional[str] = None # explainable AI text
    lat: Optional[float] = None
    lon: Optional[float] = None
    weather_context: Optional[WeatherSnapshot] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    acknowledged: bool = False


class TrajectoryEmbedding(BaseModel):
    """pgvector embedding of a vessel trajectory window."""
    mmsi: str
    embedding: List[float]          # 64-dim vector
    label: str = "normal"
    risk_score: float = 0.0
    features: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RiskScoreResponse(BaseModel):
    """API response for per-vessel risk score."""
    mmsi: str
    name: str
    risk_score: float
    risk_label: str
    anomaly_score: float
    confidence: float
    reasoning: str
    weather: Optional[WeatherSnapshot] = None
    timestamp: str


class VesselUpdate(BaseModel):
    mmsi: str
    lat: float
    lon: float
    speed: float
    heading: float
    timestamp: str
