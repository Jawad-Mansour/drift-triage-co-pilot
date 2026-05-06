-- Runs once on first postgres container boot (docker-entrypoint-initdb.d)
-- drift_triage is created automatically by POSTGRES_DB env var
-- mlflow needs its own database for MLflow's backend store
CREATE DATABASE mlflow;
