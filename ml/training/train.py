"""
Improved training pipeline for UCI Bank Marketing.
Uses XGBoost + calibration, logs full artifact triple,
and computes baseline distributions for drift monitoring.
"""

import os
import sys
import json
import hashlib
import subprocess
from datetime import datetime
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import recall_score, roc_auc_score, f1_score, precision_score
import xgboost as xgb
import mlflow
import mlflow.sklearn
from mlflow.models import infer_signature
import psycopg

# -------------------------------
# 1. Load & clean data
# -------------------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
data_path = os.path.join(script_dir, os.pardir, "data", "bank-additional-full.csv")

if not os.path.exists(data_path):
    raise FileNotFoundError(f"Dataset not found at {data_path}")

df = pd.read_csv(data_path, sep=";")
print(f"Loaded {df.shape[0]} rows from {data_path}")

# Drop duration (leakage)
df = df.drop(columns=["duration"])

# Convert pdays sentinel -> binary flag
df["previously_contacted"] = (df["pdays"] != 999).astype(int)
df = df.drop(columns=["pdays"])

# Target
y = df["y"].map({"yes": 1, "no": 0})
X = df.drop(columns=["y"])

# Feature lists (adjust to your actual columns)
numeric_features = ["age", "campaign", "previous", "emp.var.rate", 
                    "cons.price.idx", "cons.conf.idx", "euribor3m", "nr.employed"]
categorical_features = ["job", "marital", "education", "default", "housing", "loan",
                        "contact", "month", "day_of_week", "poutcome", "previously_contacted"]

# Keep only those that exist
numeric_features = [c for c in numeric_features if c in X.columns]
categorical_features = [c for c in categorical_features if c in X.columns]

# -------------------------------
# 2. Stratified split
# -------------------------------
X_train, X_temp, y_train, y_temp = train_test_split(
    X, y, test_size=0.4, stratify=y, random_state=42
)
X_val, X_test, y_val, y_test = train_test_split(
    X_temp, y_temp, test_size=0.5, stratify=y_temp, random_state=42
)
print(f"Train: {X_train.shape}, Val: {X_val.shape}, Test: {X_test.shape}")

# -------------------------------
# 3. Preprocessing pipeline
# -------------------------------
numeric_transformer = Pipeline([
    ("imputer", SimpleImputer(strategy="median")),
    ("scaler", StandardScaler())
])

categorical_transformer = Pipeline([
    ("imputer", SimpleImputer(strategy="most_frequent")),
    ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False))
])

preprocessor = ColumnTransformer([
    ("num", numeric_transformer, numeric_features),
    ("cat", categorical_transformer, categorical_features)
])

# -------------------------------
# 4. Base classifier (XGBoost)
# -------------------------------
base_model = xgb.XGBClassifier(
    n_estimators=200,
    max_depth=6,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    scale_pos_weight=(len(y_train)-y_train.sum())/y_train.sum(),
    random_state=42,
    eval_metric="logloss"
)

# Wrap with probability calibration (using validation set as calibration set)
calibrated_model = CalibratedClassifierCV(base_model, method="sigmoid", cv=3)

# -------------------------------
# 5. Full pipeline
# -------------------------------
model = Pipeline([
    ("preprocessor", preprocessor),
    ("classifier", calibrated_model)
])

# Train
model.fit(X_train, y_train)

# -------------------------------
# 6. Threshold tuning (recall >= 0.75)
# -------------------------------
proba_val = model.predict_proba(X_val)[:, 1]
thresholds = np.linspace(0, 1, 101)
best_threshold = 0.5
for thresh in thresholds:
    pred = (proba_val >= thresh).astype(int)
    rec = recall_score(y_val, pred)
    if rec >= 0.75:
        best_threshold = thresh
    else:
        break
print(f"Selected threshold: {best_threshold:.3f}")

# -------------------------------
# 7. Evaluate on test set
# -------------------------------
proba_test = model.predict_proba(X_test)[:, 1]
y_pred_test = (proba_test >= best_threshold).astype(int)
test_auc = roc_auc_score(y_test, proba_test)
test_f1 = f1_score(y_test, y_pred_test)
test_recall = recall_score(y_test, y_pred_test)
test_precision = precision_score(y_test, y_pred_test)
print(f"Test AUC: {test_auc:.4f}, F1: {test_f1:.4f}, Recall: {test_recall:.4f}, Precision: {test_precision:.4f}")

# -------------------------------
# 8. Baseline distributions (for drift)
# -------------------------------
# Store numeric percentiles & categorical frequencies from training set
baseline_stats = {}
for col in numeric_features:
    baseline_stats[col] = {
        "percentiles": np.percentile(X_train[col].dropna(), [0, 10, 25, 50, 75, 90, 100]).tolist(),
        "mean": float(X_train[col].mean()),
        "std": float(X_train[col].std())
    }
for col in categorical_features:
    baseline_stats[col] = X_train[col].value_counts(normalize=True).to_dict()
baseline_stats["output"] = {
    "positive_rate": float(y_train.mean()),
    "predicted_probability_mean": float(model.predict_proba(X_train)[:,1].mean())
}

# -------------------------------
# 9. MLflow logging
# -------------------------------
mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "file:./mlruns"))
mlflow.set_experiment("bank_marketing_improved")

# Environment fingerprint (safe pip freeze)
try:
    pip_freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    env_hash = hashlib.sha256(pip_freeze.encode()).hexdigest()[:8]
except:
    env_hash = "unknown_env"

# Model card
model_card = {
    "model_name": "BankMarketing_XGB_Calibrated",
    "training_date": datetime.now().isoformat(),
    "dataset": "UCI Bank Marketing (bank-additional-full.csv)",
    "preprocessing": {
        "dropped": ["duration"],
        "pdays_encoding": "binary flag previously_contacted",
        "unknown_handling": "kept as category"
    },
    "classifier": "XGBoost + sigmoid calibration",
    "threshold": float(best_threshold),
    "test_metrics": {
        "auc": float(test_auc),
        "f1": float(test_f1),
        "recall": float(test_recall),
        "precision": float(test_precision)
    },
    "environment_fingerprint": env_hash,
    "random_state": 42
}

# Save model card
os.makedirs("artifacts", exist_ok=True)
with open("artifacts/model_card.json", "w") as f:
    json.dump(model_card, f, indent=2)
with open("artifacts/baseline_stats.json", "w") as f:
    json.dump(baseline_stats, f, indent=2)

# Start MLflow run
with mlflow.start_run(run_name="improved_xgb_calibrated"):
    mlflow.log_params({
        "classifier": "XGBoost",
        "calibration": "sigmoid",
        "threshold_rule": "max_with_recall>=0.75",
        "tuned_threshold": str(best_threshold),
    })
    mlflow.log_metrics({
        "test_auc": test_auc,
        "test_f1": test_f1,
        "test_recall": test_recall,
        "test_precision": test_precision,
        "tuned_threshold": best_threshold
    })
    # Log model with signature
    signature = infer_signature(X_train, model.predict_proba(X_train)[:, 1])
    mlflow.sklearn.log_model(
        sk_model=model,
        artifact_path="model",
        signature=signature,
        input_example=X_train.iloc[:5]
    )
    # Log artifacts
    mlflow.log_artifact("artifacts/model_card.json", artifact_path="model_card")
    mlflow.log_artifact("artifacts/baseline_stats.json", artifact_path="drift")

    # Register model
    model_uri = f"runs:/{mlflow.active_run().info.run_id}/model"
    registered = mlflow.register_model(model_uri, "BankMarketingXGB")
    client = mlflow.tracking.MlflowClient()
    if os.getenv("PROMOTE_ON_TRAIN", "true").lower() == "true":
        client.set_registered_model_alias("BankMarketingXGB", "champion", registered.version)
        print(f"Model registered as version {registered.version} → champion alias set")
    else:
        print(f"Model registered as version {registered.version} (no alias — pending HIL)")

print("Training complete. Artifacts saved in ./mlruns and ./artifacts")

# -------------------------------
# 10. Seed drift_reference in Postgres
# -------------------------------
pg_host = os.getenv("POSTGRES_HOST", "localhost")
pg_user = os.getenv("POSTGRES_USER", "drift")
pg_pass = os.getenv("POSTGRES_PASSWORD", "")
pg_db   = os.getenv("POSTGRES_DB", "drift_triage")

try:
    conn_str = f"host={pg_host} user={pg_user} password={pg_pass} dbname={pg_db}"
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS drift_reference (
                    feature_name VARCHAR(100) PRIMARY KEY,
                    feature_type VARCHAR(20) NOT NULL,
                    bin_edges     JSONB,
                    ref_counts    JSONB NOT NULL,
                    model_version VARCHAR(50) NOT NULL
                )
            """)
            for col in numeric_features:
                vals = X_train[col].dropna().values
                edges = np.percentile(vals, np.linspace(0, 100, 11)).tolist()
                counts, _ = np.histogram(vals, bins=edges)
                cur.execute("""
                    INSERT INTO drift_reference VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT (feature_name) DO UPDATE
                    SET bin_edges=EXCLUDED.bin_edges, ref_counts=EXCLUDED.ref_counts,
                        model_version=EXCLUDED.model_version
                """, (col, "numeric", json.dumps(edges), json.dumps(counts.tolist()), registered.version))
            for col in categorical_features:
                freq = X_train[col].value_counts(normalize=True).to_dict()
                cur.execute("""
                    INSERT INTO drift_reference VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT (feature_name) DO UPDATE
                    SET bin_edges=EXCLUDED.bin_edges, ref_counts=EXCLUDED.ref_counts,
                        model_version=EXCLUDED.model_version
                """, (col, "categorical", None, json.dumps(freq), registered.version))
        conn.commit()
    print("drift_reference seeded in Postgres")
except Exception as e:
    print(f"WARNING: could not seed drift_reference: {e}")