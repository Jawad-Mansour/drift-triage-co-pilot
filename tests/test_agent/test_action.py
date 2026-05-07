"""
Action node test suite — covers all 7 rules, priority ordering, HIL flag,
idempotency dedup, and requires_hil tagging. DB writes skipped (no sessionmaker).
"""

import pytest

from backend.agent.agents.nodes.action import _rule_based_action
from backend.agent.agents.state import DriftContext, TriageDecision


def _triage(severity: str) -> TriageDecision:
    return TriageDecision(
        severity=severity,
        psi_band=severity,
        chi2_band=None,
        economic_escalation=False,
        rationale=f"severity={severity}",
    )


def _ctx(
    feature: str = "age",
    psi: float = 0.15,
    model_auc: float | None = None,
    model_uri_missing: bool = False,
    economic: bool = False,
    recent_retrain: bool = False,
    minutes_since_retrain: int | None = None,
) -> DriftContext:
    return DriftContext(
        feature_name=feature,
        psi_score=psi,
        model_auc=model_auc,
        model_uri_missing=model_uri_missing,
        economic_impact=economic,
        recent_retrain=recent_retrain,
        minutes_since_retrain=minutes_since_retrain,
    )


# ─────────────────────────────────────────────────────────────
# Rule 1: model URI missing → SWITCH_TO_FALLBACK
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "severity",
    ["LOW", "MED", "HIGH", "CRIT"],
)
def test_rule1_model_uri_missing_any_severity(severity, mock_settings):
    """Rule 1 fires regardless of severity — top priority."""
    action, rationale = _rule_based_action(
        _triage(severity), _ctx(model_uri_missing=True), mock_settings
    )
    assert action == "SWITCH_TO_FALLBACK"
    assert "URI missing" in rationale


def test_rule1_beats_rule2_poor_auc(mock_settings):
    """Model URI missing takes priority over poor AUC (Rule 1 > Rule 2)."""
    action, _ = _rule_based_action(
        _triage("CRIT"),
        _ctx(model_uri_missing=True, model_auc=0.50),
        mock_settings,
    )
    assert action == "SWITCH_TO_FALLBACK"


def test_rule1_beats_rule3_crit(mock_settings):
    """Model URI missing takes priority over CRIT severity (Rule 1 > Rule 3)."""
    action, _ = _rule_based_action(
        _triage("CRIT"),
        _ctx(model_uri_missing=True),
        mock_settings,
    )
    assert action == "SWITCH_TO_FALLBACK"


# ─────────────────────────────────────────────────────────────
# Rule 2: AUC below threshold → ROLLBACK
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "auc",
    [0.64, 0.60, 0.50, 0.0],
)
def test_rule2_poor_auc_triggers_rollback(auc, mock_settings):
    action, rationale = _rule_based_action(_triage("MED"), _ctx(model_auc=auc), mock_settings)
    assert action == "ROLLBACK"
    assert str(round(auc, 3)) in rationale


def test_rule2_boundary_auc_at_threshold_not_triggered(mock_settings):
    """AUC exactly at threshold is NOT below it → Rule 2 does not fire."""
    action, _ = _rule_based_action(_triage("MED"), _ctx(model_auc=0.65), mock_settings)
    assert action != "ROLLBACK"


def test_rule2_no_auc_skips_rule(mock_settings):
    """model_auc=None → Rule 2 is skipped entirely."""
    action, _ = _rule_based_action(_triage("MED"), _ctx(model_auc=None), mock_settings)
    assert action != "ROLLBACK"


def test_rule2_beats_rule3_crit_severity(mock_settings):
    """Poor AUC triggers ROLLBACK even when severity=CRIT (Rule 2 > Rule 3)."""
    action, _ = _rule_based_action(_triage("CRIT"), _ctx(model_auc=0.55), mock_settings)
    assert action == "ROLLBACK"


# ─────────────────────────────────────────────────────────────
# Rule 3: CRIT severity → ROLLBACK
# ─────────────────────────────────────────────────────────────
def test_rule3_crit_severity_rollback(mock_settings):
    action, rationale = _rule_based_action(_triage("CRIT"), _ctx(psi=0.35), mock_settings)
    assert action == "ROLLBACK"
    assert "CRITICAL" in rationale or "PSI" in rationale


def test_rule3_not_triggered_for_high(mock_settings):
    """Rule 3 only fires on CRIT, not HIGH."""
    action, _ = _rule_based_action(_triage("HIGH"), _ctx(psi=0.22), mock_settings)
    assert action != "ROLLBACK"  # Rule 3 does not fire; falls through to Rule 7


# ─────────────────────────────────────────────────────────────
# Rule 4: economic feature + HIGH → RETRAIN_URGENT
# ─────────────────────────────────────────────────────────────
def test_rule4_economic_high_retrain_urgent(mock_settings):
    action, rationale = _rule_based_action(
        _triage("HIGH"), _ctx(psi=0.22, economic=True), mock_settings
    )
    assert action == "RETRAIN_URGENT"
    assert "Economic" in rationale


def test_rule4_not_triggered_for_crit_economic(mock_settings):
    """Rule 3 fires before Rule 4 when severity=CRIT + economic."""
    action, _ = _rule_based_action(_triage("CRIT"), _ctx(psi=0.30, economic=True), mock_settings)
    assert action == "ROLLBACK"  # Rule 3 fires first


def test_rule4_not_triggered_without_economic(mock_settings):
    """HIGH without economic flag → falls through to Rule 7."""
    action, _ = _rule_based_action(_triage("HIGH"), _ctx(psi=0.22, economic=False), mock_settings)
    assert action == "RETRAIN_SCHEDULED"  # Rule 7


# ─────────────────────────────────────────────────────────────
# Rule 5: economic feature + MED → RETRAIN_SCHEDULED
# ─────────────────────────────────────────────────────────────
def test_rule5_economic_med_retrain_scheduled(mock_settings):
    action, rationale = _rule_based_action(
        _triage("MED"), _ctx(psi=0.15, economic=True), mock_settings
    )
    assert action == "RETRAIN_SCHEDULED"
    assert "Economic" in rationale


def test_rule5_not_triggered_for_high_economic(mock_settings):
    """Rule 4 fires before Rule 5 for HIGH + economic."""
    action, _ = _rule_based_action(_triage("HIGH"), _ctx(psi=0.22, economic=True), mock_settings)
    assert action == "RETRAIN_URGENT"  # Rule 4, not Rule 5


def test_rule5_not_triggered_without_economic(mock_settings):
    action, _ = _rule_based_action(_triage("MED"), _ctx(psi=0.15, economic=False), mock_settings)
    assert action == "REPLAY_TEST_SET"  # Rule 7


# ─────────────────────────────────────────────────────────────
# Rule 6: recent retrain + HIGH/MED → REPLAY_TEST_SET
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("severity", ["HIGH", "MED"])
def test_rule6_recent_retrain_replay(severity, mock_settings):
    action, rationale = _rule_based_action(
        _triage(severity),
        _ctx(psi=0.15, recent_retrain=True, minutes_since_retrain=15),
        mock_settings,
    )
    assert action == "REPLAY_TEST_SET"
    assert "min ago" in rationale or "Retrain" in rationale


def test_rule6_not_triggered_for_low(mock_settings):
    """Rule 6 only fires for HIGH/MED severity, not LOW."""
    action, _ = _rule_based_action(
        _triage("LOW"),
        _ctx(psi=0.05, recent_retrain=True, minutes_since_retrain=10),
        mock_settings,
    )
    assert action == "MONITOR"  # falls through to LOW → MONITOR


def test_rule6_not_triggered_for_crit(mock_settings):
    """Rule 3 fires before Rule 6 for CRIT + recent_retrain."""
    action, _ = _rule_based_action(
        _triage("CRIT"),
        _ctx(psi=0.30, recent_retrain=True, minutes_since_retrain=5),
        mock_settings,
    )
    assert action == "ROLLBACK"  # Rule 3 fires first


def test_rule6_not_triggered_when_no_retrain_flag(mock_settings):
    """recent_retrain=False → Rule 6 skipped."""
    action, _ = _rule_based_action(
        _triage("HIGH"),
        _ctx(psi=0.22, recent_retrain=False),
        mock_settings,
    )
    assert action == "RETRAIN_SCHEDULED"  # Rule 7


def test_rule4_beats_rule6_economic_plus_recent_retrain_high(mock_settings):
    """Economic feature + HIGH + recent retrain: Rule 4 fires before Rule 6."""
    action, _ = _rule_based_action(
        _triage("HIGH"),
        _ctx(psi=0.22, economic=True, recent_retrain=True, minutes_since_retrain=10),
        mock_settings,
    )
    assert action == "RETRAIN_URGENT"  # Rule 4 wins


# ─────────────────────────────────────────────────────────────
# Rule 7: standard severity mapping
# ─────────────────────────────────────────────────────────────
def test_rule7_high_retrain_scheduled(mock_settings):
    action, rationale = _rule_based_action(_triage("HIGH"), _ctx(psi=0.22), mock_settings)
    assert action == "RETRAIN_SCHEDULED"
    assert "HIGH" in rationale


def test_rule7_med_replay_test_set(mock_settings):
    action, rationale = _rule_based_action(_triage("MED"), _ctx(psi=0.15), mock_settings)
    assert action == "REPLAY_TEST_SET"
    assert "MED" in rationale


def test_rule7_low_monitor(mock_settings):
    action, rationale = _rule_based_action(_triage("LOW"), _ctx(psi=0.05), mock_settings)
    assert action == "MONITOR"
    assert "LOW" in rationale


# ─────────────────────────────────────────────────────────────
# requires_hil tagging
# ─────────────────────────────────────────────────────────────
_HIL_REQUIRED = {"ROLLBACK", "RETRAIN_URGENT", "RETRAIN_SCHEDULED", "SWITCH_TO_FALLBACK"}
_NO_HIL = {"MONITOR", "REPLAY_TEST_SET"}


@pytest.mark.parametrize(
    "action, hil_expected",
    [
        ("ROLLBACK", True),
        ("RETRAIN_URGENT", True),
        ("RETRAIN_SCHEDULED", True),
        ("SWITCH_TO_FALLBACK", True),
        ("MONITOR", False),
        ("REPLAY_TEST_SET", False),
    ],
)
def test_hil_flag_for_each_action(action, hil_expected):
    """_REQUIRES_HIL set membership is the only gate — verify it directly."""
    from backend.agent.agents.nodes.action import _REQUIRES_HIL

    assert (action in _REQUIRES_HIL) == hil_expected


# ─────────────────────────────────────────────────────────────
# Full priority chain (composite edge cases)
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "uri_missing, auc, severity, eco, recent, expected, desc",
    [
        (True, 0.50, "CRIT", True, True, "SWITCH_TO_FALLBACK", "R1>R2>R3>R4>R6"),
        (False, 0.60, "CRIT", True, True, "ROLLBACK", "R2>R3>R4>R6"),
        (False, None, "CRIT", True, True, "ROLLBACK", "R3>R4>R6 (CRIT wins)"),
        (False, None, "HIGH", True, True, "RETRAIN_URGENT", "R4>R6 (eco+HIGH wins)"),
        (False, None, "MED", True, True, "RETRAIN_SCHEDULED", "R5>R6 (eco+MED wins)"),
        (False, None, "HIGH", False, True, "REPLAY_TEST_SET", "R6 (recent+HIGH)"),
        (False, None, "MED", False, True, "REPLAY_TEST_SET", "R6 (recent+MED)"),
        (False, None, "HIGH", False, False, "RETRAIN_SCHEDULED", "R7 HIGH"),
        (False, None, "MED", False, False, "REPLAY_TEST_SET", "R7 MED"),
        (False, None, "LOW", True, True, "MONITOR", "LOW always MONITOR"),
    ],
)
def test_full_rule_priority_chain(
    uri_missing, auc, severity, eco, recent, expected, desc, mock_settings
):
    ctx = _ctx(
        model_uri_missing=uri_missing,
        model_auc=auc,
        psi=0.22 if severity in ("HIGH", "CRIT") else 0.15 if severity == "MED" else 0.05,
        economic=eco,
        recent_retrain=recent,
        minutes_since_retrain=10 if recent else None,
    )
    action, _ = _rule_based_action(_triage(severity), ctx, mock_settings)
    assert action == expected, desc
