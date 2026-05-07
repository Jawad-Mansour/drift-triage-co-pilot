"""Shared fixtures for all agent tests."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_settings():
    """Default settings with standard PSI/chi² thresholds — matches .env defaults."""
    s = MagicMock()
    s.drift_psi_threshold_medium = 0.1
    s.drift_psi_threshold_high = 0.2
    s.drift_psi_threshold_critical = 0.25
    s.drift_chi2_threshold_medium = 0.05
    s.drift_chi2_threshold_high = 0.01
    s.poor_performance_auc_threshold = 0.65
    s.recent_retrain_threshold_minutes = 30
    s.idempotency_ttl_retrain = 86400
    s.idempotency_ttl_other = 3600
    s.economic_feature_list = ["euribor3m", "cons.price.idx"]
    s.approval_timeout_minutes = 10
    return s


@pytest.fixture
def no_db_config():
    """RunnableConfig with no sessionmaker — skips all DB writes in nodes."""
    return {"configurable": {}}
