"""
Preprocessing script for UCI Bank Marketing dataset.
Saves train/val/test splits and baseline distributions for drift monitoring.
"""

import os
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split

# -------------------------------
# Paths
# -------------------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
RAW_DATA_PATH = os.path.join(script_dir, "..", "data", "bank-additional-full.csv")
PROCESSED_DIR = os.path.join(script_dir, "..", "data", "processed")
os.makedirs(PROCESSED_DIR, exist_ok=True)

# -------------------------------
# 1. Load raw data
# -------------------------------
df = pd.read_csv(RAW_DATA_PATH, sep=";")
print(f"Loaded {df.shape[0]} rows")

# -------------------------------
# 2. Cleaning & feature engineering
# -------------------------------
# Drop duration (data leakage)
df = df.drop(columns=["duration"])

# Convert pdays sentinel (999) into binary flag
df["previously_contacted"] = (df["pdays"] != 999).astype(int)
df = df.drop(columns=["pdays"])

# Target encoding
df["y"] = df["y"].map({"yes": 1, "no": 0})

# -------------------------------
# 3. Split features & target
# -------------------------------
X = df.drop(columns=["y"])
y = df["y"]

# Feature lists (all except target)
numeric_features = ["age", "campaign", "previous", "emp.var.rate", 
                    "cons.price.idx", "cons.conf.idx", "euribor3m", "nr.employed"]
categorical_features = ["job", "marital", "education", "default", "housing", "loan",
                        "contact", "month", "day_of_week", "poutcome", "previously_contacted"]

# Keep only columns that exist
numeric_features = [c for c in numeric_features if c in X.columns]
categorical_features = [c for c in categorical_features if c in X.columns]

# -------------------------------
# 4. Stratified train/val/test split (60/20/20)
# -------------------------------
X_train, X_temp, y_train, y_temp = train_test_split(
    X, y, test_size=0.4, stratify=y, random_state=42
)
X_val, X_test, y_val, y_test = train_test_split(
    X_temp, y_temp, test_size=0.5, stratify=y_temp, random_state=42
)

print(f"Train: {X_train.shape}, Val: {X_val.shape}, Test: {X_test.shape}")

# -------------------------------
# 5. Save splits as CSV (with target included)
# -------------------------------
train_df = X_train.copy()
train_df["y"] = y_train
val_df = X_val.copy()
val_df["y"] = y_val
test_df = X_test.copy()
test_df["y"] = y_test

train_df.to_csv(f"{PROCESSED_DIR}/train.csv", index=False)
val_df.to_csv(f"{PROCESSED_DIR}/val.csv", index=False)
test_df.to_csv(f"{PROCESSED_DIR}/test.csv", index=False)
print("Saved train/val/test splits to data/processed/")

# -------------------------------
# 6. Compute baseline distributions for drift monitoring
# -------------------------------
baseline_stats = {}

# Numeric features: percentiles, mean, std
for col in numeric_features:
    series = X_train[col].dropna()
    baseline_stats[col] = {
        "percentiles": np.percentile(series, [0, 10, 25, 50, 75, 90, 100]).tolist(),
        "mean": float(series.mean()),
        "std": float(series.std())
    }

# Categorical features: relative frequencies
for col in categorical_features:
    baseline_stats[col] = X_train[col].value_counts(normalize=True).to_dict()

# Output distribution (positive rate and mean predicted probability placeholder)
baseline_stats["output"] = {
    "positive_rate": float(y_train.mean()),
    "predicted_probability_mean": None  # will be filled after training
}

# Save as JSON
import json
with open(f"{PROCESSED_DIR}/baseline_stats.json", "w") as f:
    json.dump(baseline_stats, f, indent=2)
print("Saved baseline_stats.json")