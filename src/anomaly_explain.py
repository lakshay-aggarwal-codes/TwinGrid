"""Dependency-free explainability for the autoencoder anomaly detector.

Not SHAP -- SHAP treats the model as a black box and requires a new heavy
dependency, a background/reference dataset, and real compute per
explanation. This detector is an autoencoder, where the model *already*
computes something more informative for free: per-timestep, per-feature
reconstruction error. Which of the 5 sensor features the autoencoder
reconstructed worst IS the reason a sequence scored as anomalous -- there's
no black box to probe. This module just stops
AnomalyDetector._compute_errors from averaging that away before it reaches
the caller.

Limits vs. SHAP: this attributes error to INPUT FEATURES (which sensor
looked wrong), not to a counterfactual ("how would the score change if X
were different"), and it doesn't account for feature interactions. For a
5-feature autoencoder with no downstream classifier, feature-level
reconstruction error is the natural and sufficient explanation here; SHAP's
extra machinery buys little for this specific model shape.
"""

from __future__ import annotations

import numpy as np

from src.anomaly_detector import N_FEATURES, AnomalyDetector, NotTrainedError


def explain(detector: AnomalyDetector, sequences: np.ndarray) -> list[dict[str, object]]:
    """
    For each input sequence, return which of the 5 feature columns drove its
    reconstruction-error (anomaly) score, as a percentage breakdown.

    Args:
        detector: A trained AnomalyDetector (the same one used for detect()).
        sequences: Shape (n_samples, seq_len, 5) -- same input detect() takes.

    Returns:
        One dict per sequence:
            {
                "total_error": float,  # matches detect()'s error_scores exactly
                "feature_contributions_pct": {feature_name: pct, ...},  # sums to ~100
                "top_feature": str,  # single largest contributor
            }
    """
    if not detector._is_trained or detector._model is None or detector._scaler is None:
        raise NotTrainedError("Detector must be trained before explaining.")

    if sequences.ndim != 3 or sequences.shape[1] != detector._seq_len or sequences.shape[2] != N_FEATURES:
        raise ValueError(f"sequences must be (n, {detector._seq_len}, {N_FEATURES}), got {sequences.shape}")

    sequences_scaled = detector._scaler.transform(sequences.reshape(-1, N_FEATURES)).reshape(sequences.shape)
    reconstructions = detector._model.predict(sequences_scaled, verbose=0)

    # Per-sample, per-feature MSE (average over the time axis only -- unlike
    # _compute_errors, which also averages over features). That's the whole
    # difference between a bare anomaly score and an explanation of it.
    per_feature_mse = np.mean((sequences_scaled - reconstructions) ** 2, axis=1)  # (n, 5)
    total_error = np.mean(per_feature_mse, axis=1)  # matches _compute_errors exactly

    results: list[dict[str, object]] = []
    for i in range(len(sequences)):
        row = per_feature_mse[i]
        row_sum = float(row.sum())
        if row_sum > 0:
            pct = {col: float(row[j] / row_sum * 100) for j, col in enumerate(detector._feature_columns)}
        else:
            pct = {col: 0.0 for col in detector._feature_columns}
        top_feature = max(pct, key=pct.get)
        results.append(
            {
                "total_error": float(total_error[i]),
                "feature_contributions_pct": pct,
                "top_feature": top_feature,
            }
        )
    return results
