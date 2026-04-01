"""
OceanGuard AI — 20,000 Vessel Load Test
========================================
Benchmarks end-to-end latency and throughput for 20k+ vessels.
Tests: ingestion pipeline, risk scoring, alert evaluation, API response.

Run: python tests/load_test_20k.py
"""
import asyncio
import sys
import os
import time
import random
import statistics

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.models import Vessel, WeatherSnapshot
from app.store import VesselStore
from app.risk_engine import compute_risk_score, predict_anomaly
from app.alerts import AlertEngine
from datetime import datetime, timezone

N_VESSELS = 20000
BATCH_SIZE = 500

def make_vessel(i: int) -> Vessel:
    flags = ["India","China","USA","Unknown","Pakistan","Liberia","Panama"]
    types = ["Cargo Ship","Tanker","Naval Vessel","Fishing Vessel","Unknown","Passenger Ship"]
    return Vessel(
        mmsi=str(100000000 + i),
        name=f"Vessel_{i:05d}",
        lat=random.uniform(-10, 30),
        lon=random.uniform(40, 130),
        speed=random.uniform(0, 35),
        heading=random.uniform(0, 360),
        vessel_type=random.choice(types),
        flag=random.choice(flags),
        timestamp=datetime.now(timezone.utc),
    )

def make_weather() -> WeatherSnapshot:
    return WeatherSnapshot(
        wave_height=random.uniform(0, 5),
        wind_speed=random.uniform(0, 20),
        storm_index=random.uniform(0, 0.8),
        swell_height=random.uniform(0, 3),
    )

async def run_benchmark():
    print(f"\n{'='*60}")
    print(f"OceanGuard AI — 20k Vessel Load Test")
    print(f"{'='*60}\n")

    store = VesselStore(max_vessels=25000)
    alert_engine = AlertEngine()
    vessels = [make_vessel(i) for i in range(N_VESSELS)]
    weather_samples = [make_weather() for _ in range(100)]

    # ── Test 1: Risk scoring throughput ──────────────────────────────────────
    print(f"[1] Risk scoring — {N_VESSELS:,} vessels...")
    latencies = []
    t_start = time.perf_counter()
    for v in vessels:
        w = random.choice(weather_samples)
        t0 = time.perf_counter()
        anomaly = predict_anomaly(v, w)
        score, label, reasoning, conf = compute_risk_score(v, w, anomaly)
        v.risk_score = score
        v.risk_label = label
        latencies.append((time.perf_counter() - t0) * 1000)
    total = time.perf_counter() - t_start

    print(f"   Total time:    {total:.2f}s")
    print(f"   Throughput:    {N_VESSELS/total:,.0f} vessels/s")
    print(f"   Avg latency:   {statistics.mean(latencies):.3f}ms")
    print(f"   P95 latency:   {statistics.quantiles(latencies, n=20)[18]:.3f}ms")
    print(f"   P99 latency:   {statistics.quantiles(latencies, n=100)[98]:.3f}ms")

    # ── Test 2: Store upsert throughput ───────────────────────────────────────
    print(f"\n[2] Store upsert — {N_VESSELS:,} vessels...")
    t_start = time.perf_counter()
    for v in vessels:
        store.upsert(v)
    total = time.perf_counter() - t_start
    print(f"   Total time:    {total:.2f}s")
    print(f"   Throughput:    {N_VESSELS/total:,.0f} upserts/s")
    print(f"   Store size:    {store.count():,} vessels")

    # ── Test 3: Alert evaluation throughput ───────────────────────────────────
    print(f"\n[3] Alert evaluation — {N_VESSELS:,} vessels...")
    t_start = time.perf_counter()
    for v in vessels:
        alert_engine.evaluate(v)
    total = time.perf_counter() - t_start
    alerts_generated = len(alert_engine.get_alerts(10000))
    print(f"   Total time:    {total:.2f}s")
    print(f"   Throughput:    {N_VESSELS/total:,.0f} evals/s")
    print(f"   Alerts fired:  {alerts_generated}")

    # ── Test 4: Full pipeline (risk + store + alert) ──────────────────────────
    print(f"\n[4] Full pipeline — {N_VESSELS:,} vessels (batches of {BATCH_SIZE})...")
    store2 = VesselStore(max_vessels=25000)
    engine2 = AlertEngine()
    batch_times = []

    for batch_start in range(0, N_VESSELS, BATCH_SIZE):
        batch = vessels[batch_start:batch_start + BATCH_SIZE]
        t0 = time.perf_counter()
        for v in batch:
            w = random.choice(weather_samples)
            anomaly = predict_anomaly(v, w)
            score, label, _, _ = compute_risk_score(v, w, anomaly)
            v.risk_score = score
            v.risk_label = label
            store2.upsert(v)
            engine2.evaluate(v)
        batch_times.append((time.perf_counter() - t0) * 1000)

    total_pipeline = sum(batch_times) / 1000
    avg_batch_ms = statistics.mean(batch_times)
    print(f"   Total time:    {total_pipeline:.2f}s")
    print(f"   Throughput:    {N_VESSELS/total_pipeline:,.0f} vessels/s")
    print(f"   Avg batch ms:  {avg_batch_ms:.1f}ms per {BATCH_SIZE} vessels")
    print(f"   Per-vessel:    {avg_batch_ms/BATCH_SIZE:.3f}ms")

    # ── Summary ───────────────────────────────────────────────────────────────
    per_vessel_ms = avg_batch_ms / BATCH_SIZE
    target_met = per_vessel_ms < 2.0
    print(f"\n{'='*60}")
    print(f"RESULT: {per_vessel_ms:.3f}ms per vessel end-to-end")
    print(f"TARGET: <2ms per vessel")
    print(f"STATUS: {'✅ PASSED' if target_met else '❌ NEEDS OPTIMIZATION'}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
