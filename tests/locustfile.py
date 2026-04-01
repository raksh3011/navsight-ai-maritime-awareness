"""
ORVMS Backend Load Test
Run: locust -f tests/locustfile.py --host=http://127.0.0.1:8000
Then open: http://localhost:8089
"""
from locust import HttpUser, task, between
import json, random

class VesselAPIUser(HttpUser):
    wait_time = between(0.5, 2)  # simulate realistic request cadence

    @task(5)
    def get_live_vessels(self):
        """Most frequent — frontend polls this every 3s"""
        with self.client.get("/vessels/live", catch_response=True) as r:
            if r.status_code == 200:
                data = r.json()
                count = data.get("total", 0)
                if count == 0:
                    r.failure("No vessels returned")
                else:
                    r.success()
            else:
                r.failure(f"HTTP {r.status_code}")

    @task(3)
    def get_alerts(self):
        with self.client.get("/alerts?limit=50", catch_response=True) as r:
            if r.status_code == 200:
                r.success()
            else:
                r.failure(f"HTTP {r.status_code}")

    @task(1)
    def get_health(self):
        with self.client.get("/health", catch_response=True) as r:
            if r.status_code == 200:
                data = r.json()
                if data.get("status") != "ok":
                    r.failure("Health check failed")
            else:
                r.failure(f"HTTP {r.status_code}")

    @task(1)
    def post_manual_vessel(self):
        """Test manual vessel ingestion throughput"""
        mmsi = str(random.randint(100000000, 999999999))
        payload = {
            "mmsi": mmsi,
            "name": f"Test Vessel {mmsi[-4:]}",
            "lat": round(random.uniform(5, 22), 4),
            "lon": round(random.uniform(65, 92), 4),
            "speed": round(random.uniform(0, 30), 1),
            "heading": random.randint(0, 359),
            "vessel_type": random.choice(["Cargo Ship", "Tanker", "Naval Vessel"]),
            "flag": random.choice(["India", "China", "Unknown", "Pakistan"]),
            "timestamp": "2026-01-01T00:00:00Z",
        }
        with self.client.post("/vessels/manual", json=payload, catch_response=True) as r:
            if r.status_code == 200:
                r.success()
            else:
                r.failure(f"HTTP {r.status_code}")
