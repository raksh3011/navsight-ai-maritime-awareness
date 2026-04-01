# OceanGuard AI — Climate & Environment Risk Edition
### *AI Climate Risk Co-Pilot for Maritime Safety — Scalable to Global Fleets*

> **Hackathon Track:** AI in Environment and Climate  
> **Branch:** `OceanGuard_Climate_AI`

---

## 30-Second Demo Pitch

*"Every year, climate-driven storms push vessels into piracy corridors. Existing systems like MarineTraffic show you where ships are — but not the risk they're sailing into. OceanGuard AI fuses real-time AIS vessel tracking with Open-Meteo marine weather data to compute a live Climate Risk Score for every vessel, every 30 seconds. When a cyclone forces a tanker toward the Somali Basin, our AI flags it as critical before the crew even knows. We handle 20,000+ vessels with sub-2ms per-vessel latency, zero cloud cost, and explainable alerts that ship operators actually trust."*

---

## What Makes This Different

| Gap in Existing Systems | OceanGuard AI Solution |
|---|---|
| AIS spoofing / dark vessels | Isolation Forest + pgvector trajectory similarity |
| No weather/climate fusion | Open-Meteo Marine API + composite risk scoring |
| Reactive alerts | Proactive Climate Risk Score (0-100) updated every 30s |
| 20k+ vessel cost barrier | Async FastAPI + PostGIS + pgvector, zero paid services |
| Alert fatigue in Malacca | Confidence-scored, climate-contextualized alerts |

---

## Architecture

```
Real Ships (VHF AIS)
      ↓
aisstream.io WebSocket
      ↓
FastAPI Ingestion (async, batched)
      ↓
┌─────────────────────────────────────────────┐
│  Risk Engine                                │
│  Open-Meteo Weather + Isolation Forest      │
│  → Climate Risk Score (0-100)               │
│  → Explainable reasoning                    │
└─────────────────────────────────────────────┘
      ↓
┌─────────────────────────────────────────────┐
│  PostgreSQL 16                              │
│  + PostGIS (spatial queries, heatmaps)      │
│  + pgvector (trajectory embeddings, HNSW)   │
│  + TimescaleDB (time-series history)        │
└─────────────────────────────────────────────┘
      ↓
WebSocket broadcast (every 3s)
      ↓
Leaflet Map + Risk Heatmap + Climate Overlays
```

---

## Quick Start

### Option A — Docker (recommended)
```bash
git clone https://github.com/raksh3011/navsight-ai-maritime-awareness
git checkout OceanGuard_Climate_AI
docker-compose up --build
# Open http://localhost:8000
```

### Option B — Local
```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend — open frontend/index.html in browser
# or use VS Code Live Server on port 5500
```

### Train anomaly model (optional)
```bash
python ml/train_anomaly_model.py
# Saves to backend/models/isolation_forest.joblib
```

---

## Performance Benchmarks

```bash
python tests/load_test_20k.py
```

| Metric | Target | Achieved |
|---|---|---|
| Per-vessel end-to-end | < 2ms | ~0.05ms |
| Risk scoring throughput | > 10k/s | ~200k/s |
| Store upsert throughput | > 10k/s | ~500k/s |
| Alert eval throughput | > 10k/s | ~100k/s |
| Concurrent vessels | 20,000+ | ✅ |

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /vessels/live` | All tracked vessels with risk scores |
| `GET /risk/top?limit=20` | Top risk vessels |
| `GET /risk/vessel/{mmsi}` | Detailed risk for one vessel |
| `GET /risk/heatmap` | Risk heatmap grid data |
| `GET /alerts?limit=100` | Recent alerts with reasoning |
| `GET /spatial/vessels?lat_min=...` | PostGIS bounding box query |
| `WS /ws/vessels` | Real-time WebSocket feed |

---

## Market Positioning

**Target customers:**
- Ship management companies (fleet risk dashboards)
- Fishing cooperatives in Indian Ocean / Malacca
- Tanker operators (Gulf of Aden routing)
- Port authorities (vessel approach risk)
- Maritime insurance underwriters

**Pricing model (SaaS):**
- Free tier: 50 vessels, 7-day history
- Pro: $299/month — 5,000 vessels, 90-day history, PDF reports
- Enterprise: custom — 20k+ vessels, API access, white-label

---

## Tech Stack

- **Backend:** FastAPI + asyncpg + Python 3.11
- **Database:** PostgreSQL 16 + PostGIS + pgvector + TimescaleDB
- **AI/ML:** scikit-learn Isolation Forest + rule-based risk engine
- **Weather:** Open-Meteo Marine API (free, no key required)
- **Frontend:** Vanilla JS + Leaflet.js
- **Deploy:** Docker Compose (zero cost)
- **AIS Data:** aisstream.io (free tier)

---

## Deployment (Free Tier)

| Platform | Notes |
|---|---|
| **Render** | Free web service + free Postgres 1GB |
| **Railway** | $5 credit/month covers small fleet |
| **Fly.io** | Free tier, good for WebSocket |
| **Self-hosted** | Docker Compose on any VPS |

---

*Built for the AI in Environment and Climate hackathon track.*  
*Zero monetary cost. Open source. Production-ready architecture.*
