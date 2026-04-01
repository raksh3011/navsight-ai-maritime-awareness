"""
Benchmarks the alert engine rule evaluation speed.
Tests how fast the backend can process vessel updates + run alert rules.

Run: python tests/bench_alerts.py  (from the backend/ directory)
     cd backend && python ../tests/bench_alerts.py
"""
import sys, os, time, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.models import Vessel
from app.alerts import alert_engine
from datetime import datetime, timezone

def make_vessel(mmsi, lat, lon, speed, flag="Unknown"):
    return Vessel(
        mmsi=str(mmsi), name=f"Vessel_{mmsi}",
        lat=lat, lon=lon, speed=speed, heading=random.randint(0,359),
        vessel_type="Naval Vessel", flag=flag,
        timestamp=datetime.now(timezone.utc),
    )

# Scenarios
SCENARIOS = [
    # (label, lat, lon, speed, flag)
    ("Inside EEZ unfriendly fast",  15.0, 72.0, 30.0, "China"),
    ("Inside EEZ unfriendly slow",  12.0, 80.0, 10.0, "Pakistan"),
    ("Outside EEZ fast",             2.0, 55.0, 28.0, "Unknown"),
    ("Friendly inside EEZ",         18.0, 68.0, 25.0, "USA"),
    ("Gulf of Aden",                12.5, 47.5,  8.0, "Unknown"),
]

N = 10_000  # evaluations per scenario

print(f"Alert engine benchmark — {N:,} evaluations per scenario\n")
print(f"{'Scenario':<35} {'Total':>8} {'Per eval':>10} {'Rate':>12}")
print("-" * 70)

for label, lat, lon, speed, flag in SCENARIOS:
    vessels = [make_vessel(i, lat, lon, speed, flag) for i in range(100)]
    t0 = time.perf_counter()
    for i in range(N):
        alert_engine.evaluate(vessels[i % 100])
    elapsed = time.perf_counter() - t0
    per_eval_us = (elapsed / N) * 1_000_000
    rate = N / elapsed
    print(f"{label:<35} {elapsed:>7.3f}s {per_eval_us:>9.1f}µs {rate:>10,.0f}/s")

print("\nAlert engine is efficient if per-eval < 100µs and rate > 10,000/s")
