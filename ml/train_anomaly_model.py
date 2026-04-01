"""
OceanGuard AI — Offline Anomaly Model Training
===============================================
Trains an Isolation Forest on synthetic AIS + weather features.
Saves model to backend/models/isolation_forest.joblib

Run: python ml/train_anomaly_model.py

In production: replace synthetic data with real NOAA AIS historical data
from: https://marinecadastre.gov/ais/
"""
import os
import sys
import numpy as np
import joblib
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'backend', 'models')
os.makedirs(OUTPUT_DIR, exist_ok=True)

print("Generating synthetic training data...")

rng = np.random.default_rng(42)
N_NORMAL = 18000
N_ANOMALY = 2000

# Normal vessel features (10-dim):
# [speed/30, heading/360, heading_sin, zone_risk, in_eez,
#  wave/8, wind/25, storm_idx, unfriendly_flag, suspicious_type]
normal = np.column_stack([
    rng.uniform(0.1, 0.6, N_NORMAL),    # speed 3-18 kn
    rng.uniform(0, 1, N_NORMAL),         # heading
    rng.uniform(-1, 1, N_NORMAL),        # heading sin
    rng.uniform(0, 0.2, N_NORMAL),       # low zone risk
    rng.integers(0, 2, N_NORMAL).astype(float),
    rng.uniform(0, 0.3, N_NORMAL),       # calm seas
    rng.uniform(0, 0.3, N_NORMAL),
    rng.uniform(0, 0.2, N_NORMAL),
    rng.integers(0, 2, N_NORMAL).astype(float) * 0.3,
    rng.integers(0, 2, N_NORMAL).astype(float) * 0.2,
])

# Anomalous vessel features
anomaly = np.column_stack([
    rng.uniform(0.7, 1.0, N_ANOMALY),   # high speed
    rng.uniform(0, 1, N_ANOMALY),
    rng.uniform(-1, 1, N_ANOMALY),
    rng.uniform(0.6, 1.0, N_ANOMALY),   # high zone risk
    rng.integers(0, 2, N_ANOMALY).astype(float),
    rng.uniform(0.1, 0.8, N_ANOMALY),
    rng.uniform(0.1, 0.8, N_ANOMALY),
    rng.uniform(0.3, 1.0, N_ANOMALY),
    rng.integers(0, 2, N_ANOMALY).astype(float) * 0.8,
    rng.integers(0, 2, N_ANOMALY).astype(float) * 0.9,
])

X_train = np.vstack([normal, anomaly])
y_true = np.array([1]*N_NORMAL + [-1]*N_ANOMALY)  # 1=normal, -1=anomaly

print(f"Training on {len(X_train)} samples ({N_NORMAL} normal, {N_ANOMALY} anomaly)...")

model = Pipeline([
    ('scaler', StandardScaler()),
    ('iso', IsolationForest(
        n_estimators=100,
        contamination=N_ANOMALY / (N_NORMAL + N_ANOMALY),
        random_state=42,
        n_jobs=-1,
    ))
])

model.fit(X_train)

# Evaluate
y_pred = model.predict(X_train)
print("\nTraining set evaluation:")
print(classification_report(y_true, y_pred, target_names=['anomaly', 'normal']))

# Save
path = os.path.join(OUTPUT_DIR, 'isolation_forest.joblib')
joblib.dump(model, path)
print(f"\nModel saved to {path}")
print("Deploy: copy backend/models/ to your server and restart the backend.")
