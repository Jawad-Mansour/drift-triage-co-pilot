"""
Triage node test suite — covers every PSI band, chi² band, worst-signal selection,
and economic escalation combination. No DB (no sessionmaker in config).
"""

import uuid
from unittest.mock import patch

import pytest

from backend.agent.agents.nodes.triage import triage_node
from backend.agent.agents.state import DriftContext


def _make_state(
    psi: float,
    chi2_p: float | None = None,
    economic: bool = False,
    feature: str = "age",
    investigation_id: str | None = None,
) -> dict:
    return {
        "thread_id": "test-thread",
        "investigation_id": investigation_id or str(uuid.uuid4()),
        "drift_context": DriftContext(
            feature_name=feature,
            psi_score=psi,
            chi2_pvalue=chi2_p,
            economic_impact=economic,
        ),
    }


# ─────────────────────────────────────────────────────────────
# PSI-only severity bands
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "psi, expected_severity, expected_psi_band",
    [
        # --- LOW: PSI < 0.1 ---
        (0.0, "LOW", "LOW"),
        (0.05, "LOW", "LOW"),
        (0.09, "LOW", "LOW"),
        (0.099, "LOW", "LOW"),
        # --- MED: 0.1 <= PSI < 0.2 ---
        (0.1, "MED", "MED"),
        (0.15, "MED", "MED"),
        (0.19, "MED", "MED"),
        (0.199, "MED", "MED"),
        # --- HIGH: 0.2 <= PSI < 0.25 ---
        (0.2, "HIGH", "HIGH"),
        (0.22, "HIGH", "HIGH"),
        (0.249, "HIGH", "HIGH"),
        # --- CRIT: PSI >= 0.25 ---
        (0.25, "CRIT", "CRIT"),
        (0.30, "CRIT", "CRIT"),
        (0.50, "CRIT", "CRIT"),
    ],
)
async def test_psi_only_bands(
    psi, expected_severity, expected_psi_band, mock_settings, no_db_config
):
    with patch("backend.agent.agents.nodes.triage.get_settings", return_value=mock_settings):
        result = await triage_node(_make_state(psi=psi), no_db_config)

    triage = result["triage"]
    assert triage.severity == expected_severity, f"PSI={psi}"
    assert triage.psi_band == expected_psi_band, f"PSI={psi}"
    assert triage.chi2_band is None
    assert triage.economic_escalation is False
    assert result["next_node"] == "action"


# ─────────────────────────────────────────────────────────────
# chi² bands (no economic effect)
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "psi, chi2_p, expected_chi2_band",
    [
        # HIGH: p <= 0.01
        (0.05, 0.001, "HIGH"),
        (0.05, 0.01, "HIGH"),  # boundary — inclusive
        # MED: 0.01 < p <= 0.05
        (0.05, 0.011, "MED"),
        (0.05, 0.03, "MED"),
        (0.05, 0.05, "MED"),  # boundary — inclusive
        # LOW: p > 0.05
        (0.05, 0.051, "LOW"),
        (0.05, 0.5, "LOW"),
        (0.05, 1.0, "LOW"),
        # None chi² → chi2_band should be None
    ],
)
async def test_chi2_band_values(psi, chi2_p, expected_chi2_band, mock_settings, no_db_config):
    with patch("backend.agent.agents.nodes.triage.get_settings", return_value=mock_settings):
        result = await triage_node(_make_state(psi=psi, chi2_p=chi2_p), no_db_config)

    triage = result["triage"]
    assert triage.chi2_band == expected_chi2_band, f"chi2_p={chi2_p}"


async def test_chi2_none_gives_none_band(mock_settings, no_db_config):
    with patch("backend.agent.agents.nodes.triage.get_settings", return_value=mock_settings):
        result = await triage_node(_make_state(psi=0.05, chi2_p=None), no_db_config)
    assert result["triage"].chi2_band is None


# ─────────────────────────────────────────────────────────────
# Worst-signal selection (PSI vs chi²)
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "psi, chi2_p, expected_severity, desc",
    [
        # chi² worse than PSI → chi² wins
        (0.05, 0.01, "HIGH", "psi=LOW chi2=HIGH → HIGH"),
        (0.05, 0.03, "MED", "psi=LOW chi2=MED  → MED"),
        (0.15, 0.005, "HIGH", "psi=MED chi2=HIGH → HIGH"),
        # PSI worse than chi² → PSI wins
        (0.25, 0.005, "CRIT", "psi=CRIT chi2=HIGH → CRIT"),
        (0.25, 0.03, "CRIT", "psi=CRIT chi2=MED  → CRIT"),
        (0.22, 0.03, "HIGH", "psi=HIGH chi2=MED  → HIGH"),
        # Both equal → either band (same result)
        (0.15, 0.03, "MED", "psi=MED chi2=MED  → MED"),
        (0.22, 0.005, "HIGH", "psi=HIGH chi2=HIGH → HIGH"),
    ],
)
async def test_worst_signal_selection(
    psi, chi2_p, expected_severity, desc, mock_settings, no_db_config
):
    with patch("backend.agent.agents.nodes.triage.get_settings", return_value=mock_settings):
        result = await triage_node(_make_state(psi=psi, chi2_p=chi2_p), no_db_config)

    assert result["triage"].severity == expected_severity, desc


# ─────────────────────────────────────────────────────────────
# Economic escalation
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "psi, economic, expected_severity, expected_escalation, desc",
    [
        # Escalation fires: economic=True, PSI > 0.15, base=MED → HIGH
        (0.16, True, "HIGH", True, "MED + eco + psi>0.15 → HIGH"),
        (0.19, True, "HIGH", True, "MED + eco + psi=0.19 → HIGH"),
        # Escalation fires: economic=True, PSI > 0.15, base=HIGH → CRIT
        (0.22, True, "CRIT", True, "HIGH + eco + psi>0.15 → CRIT"),
        (0.24, True, "CRIT", True, "HIGH + eco + psi=0.24 → CRIT"),
        # No escalation: PSI not > 0.15 (even with economic feature)
        (0.12, True, "MED", False, "MED + eco + psi=0.12 (not >0.15) → MED"),
        (0.15, True, "MED", False, "MED + eco + psi=0.15 (not strictly >) → MED"),
        # No escalation: non-economic feature
        (0.16, False, "MED", False, "MED + non-eco → MED"),
        (0.22, False, "HIGH", False, "HIGH + non-eco → HIGH"),
        # No escalation: base=CRIT (not in escalation candidates)
        (0.30, True, "CRIT", False, "CRIT + eco → stays CRIT (no double-escalation)"),
        # No escalation: base=LOW (not in escalation candidates)
        (0.05, True, "LOW", False, "LOW + eco → stays LOW"),
    ],
)
async def test_economic_escalation(
    psi, economic, expected_severity, expected_escalation, desc, mock_settings, no_db_config
):
    with patch("backend.agent.agents.nodes.triage.get_settings", return_value=mock_settings):
        result = await triage_node(_make_state(psi=psi, economic=economic), no_db_config)

    triage = result["triage"]
    assert triage.severity == expected_severity, desc
    assert triage.economic_escalation == expected_escalation, desc


# ─────────────────────────────────────────────────────────────
# Economic escalation + chi² interaction
# ─────────────────────────────────────────────────────────────
async def test_eco_escalation_uses_base_before_escalation(mock_settings, no_db_config):
    """chi² raises base to HIGH, then economic escalation raises HIGH → CRIT."""
    # PSI=0.05 (LOW), chi²=0.005 (HIGH) → base=HIGH; economic + psi>0.15? psi=0.05 → NO
    # So economic escalation should NOT fire because psi_score=0.05 ≤ 0.15
    with patch("backend.agent.agents.nodes.triage.get_settings", return_value=mock_settings):
        result = await triage_node(_make_state(psi=0.05, chi2_p=0.005, economic=True), no_db_config)
    triage = result["triage"]
    assert triage.severity == "HIGH"  # chi² base=HIGH
    assert triage.economic_escalation is False  # PSI not > 0.15 → no escalation


async def test_eco_escalation_with_high_psi_and_bad_chi2(mock_settings, no_db_config):
    """PSI=0.18 (MED), chi²=0.005 (HIGH) → base=HIGH; economic + psi=0.18>0.15 → CRIT."""
    with patch("backend.agent.agents.nodes.triage.get_settings", return_value=mock_settings):
        result = await triage_node(_make_state(psi=0.18, chi2_p=0.005, economic=True), no_db_config)
    triage = result["triage"]
    assert triage.severity == "CRIT"
    assert triage.economic_escalation is True


# ─────────────────────────────────────────────────────────────
# Rationale content checks
# ─────────────────────────────────────────────────────────────
async def test_rationale_contains_psi(mock_settings, no_db_config):
    with patch("backend.agent.agents.nodes.triage.get_settings", return_value=mock_settings):
        result = await triage_node(_make_state(psi=0.35), no_db_config)
    assert "PSI=0.350" in result["triage"].rationale


async def test_rationale_contains_chi2_when_present(mock_settings, no_db_config):
    with patch("backend.agent.agents.nodes.triage.get_settings", return_value=mock_settings):
        result = await triage_node(_make_state(psi=0.05, chi2_p=0.005), no_db_config)
    assert "chi²" in result["triage"].rationale


async def test_rationale_mentions_escalation(mock_settings, no_db_config):
    with patch("backend.agent.agents.nodes.triage.get_settings", return_value=mock_settings):
        result = await triage_node(_make_state(psi=0.18, economic=True), no_db_config)
    assert "escalation" in result["triage"].rationale


# ─────────────────────────────────────────────────────────────
# next_node routing
# ─────────────────────────────────────────────────────────────
async def test_triage_always_routes_to_action(mock_settings, no_db_config):
    with patch("backend.agent.agents.nodes.triage.get_settings", return_value=mock_settings):
        result = await triage_node(_make_state(psi=0.05), no_db_config)
    assert result["next_node"] == "action"
