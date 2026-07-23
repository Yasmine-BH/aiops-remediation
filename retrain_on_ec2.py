import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import joblib

# --- Load raw logged data ---
df = pd.read_csv("cpu_metrics_log.csv")
df = df.sort_values("timestamp").reset_index(drop=True)

# --- Corrected ground truth (ramp-up + peak + recovery, not just the trigger row) ---
CPU_ELEVATED = df["cpu_percent"] > 60

baseline_load = df["load_avg_1min"].shift(1).rolling(300, min_periods=30).median()
RECOVERING = df["load_avg_1min"] > (baseline_load * 3)

raw_anomalous = (CPU_ELEVATED | RECOVERING).fillna(False)

PAD = 5
padded = raw_anomalous.copy()
for i in np.where(raw_anomalous)[0]:
    lo = max(0, i - PAD)
    hi = min(len(df), i + PAD + 1)
    padded.iloc[lo:hi] = True

df["ground_truth_incident"] = padded

print("Original is_incident count:      ", df["is_incident"].sum())
print("Corrected ground_truth_incident: ", df["ground_truth_incident"].sum())

# --- Train Isolation Forest on genuinely normal rows only ---
FEATURES = ["cpu_percent", "mem_percent", "load_avg_1min"]
normal_data = df[~df["ground_truth_incident"]][FEATURES]

scaler = StandardScaler()
normal_scaled = scaler.fit_transform(normal_data)

iso = IsolationForest(n_estimators=200, contamination=0.03, random_state=42)
iso.fit(normal_scaled)

# --- Quick validation ---
all_scaled = scaler.transform(df[FEATURES])
pred = iso.predict(all_scaled) == -1
gt = df["ground_truth_incident"]
tp = (pred & gt).sum()
fp = (pred & ~gt).sum()
fn = (~pred & gt).sum()
precision = tp / (tp + fp) if (tp + fp) else 0
recall = tp / (tp + fn) if (tp + fn) else 0
print(f"\nValidation -> Precision: {precision:.3f}  Recall: {recall:.3f}")

# --- Save, overwriting the imported versions with box-native ones ---
joblib.dump(iso, "iso_forest_cpu.joblib")
joblib.dump(scaler, "cpu_scaler.joblib")
print("\nRetrained and saved: iso_forest_cpu.joblib, cpu_scaler.joblib (matches this box's scikit-learn version)")
