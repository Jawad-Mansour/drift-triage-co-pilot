"""
Drift detection utilities: PSI for numeric features, chi‑square for categoricals.
"""

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

def compute_psi(expected_dist, actual_dist, bins=10, epsilon=1e-6):
    """
    Population Stability Index (PSI).
    expected_dist : array of expected proportions per bin (must sum to 1)
    actual_dist   : array of actual proportions per bin
    """
    expected = np.array(expected_dist) + epsilon
    actual = np.array(actual_dist) + epsilon
    expected = expected / expected.sum()
    actual = actual / actual.sum()
    psi = np.sum((actual - expected) * np.log(actual / expected))
    return psi

def compute_psi_from_continuous(expected_series, actual_series, bins=10, quantile_bins=True):
    """
    Compute PSI by binning continuous values.
    If quantile_bins=True, use expected's percentiles as bin edges.
    """
    if quantile_bins:
        bin_edges = np.percentile(expected_series.dropna(), np.linspace(0, 100, bins+1))
        bin_edges[0] = -np.inf
        bin_edges[-1] = np.inf
    else:
        bin_edges = np.linspace(expected_series.min(), expected_series.max(), bins+1)
    
    expected_counts, _ = np.histogram(expected_series.dropna(), bins=bin_edges)
    actual_counts, _ = np.histogram(actual_series.dropna(), bins=bin_edges)
    
    expected_dist = expected_counts / len(expected_series)
    actual_dist = actual_counts / len(actual_series)
    return compute_psi(expected_dist, actual_dist)

def compute_chi2_pvalue(expected_counts, actual_counts):
    """
    Chi-square test p-value for categorical feature.
    expected_counts : dict or Series of expected frequencies
    actual_counts   : dict or Series of actual frequencies
    """
    # Align categories
    all_cats = set(expected_counts.keys()) | set(actual_counts.keys())
    exp = np.array([expected_counts.get(cat, 0) for cat in all_cats])
    act = np.array([actual_counts.get(cat, 0) for cat in all_cats])
    # Contingency table: rows = expected/actual, columns = categories
    contingency = np.vstack([exp, act])
    # Remove zero rows/cols
    contingency = contingency[:, ~np.all(contingency == 0, axis=0)]
    if contingency.shape[1] < 2:
        return 1.0  # not enough categories
    _, p, _, _ = chi2_contingency(contingency)
    return p