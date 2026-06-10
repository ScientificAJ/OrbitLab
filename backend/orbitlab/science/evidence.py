from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from orbitlab.science.bls import TransitCandidate


@dataclass(frozen=True)
class CandidateEvidence:
    raw_snr: float
    red_noise_beta: float
    effective_snr: float
    transit_count: int
    phase_coverage_score: float
    detection_score: float
    vetting_score: float
    data_quality_score: float
    centroid_score: float
    physics_plausibility_score: float
    ml_score: float | None
    final_score: float
    explanation: tuple[str, ...]


def out_of_transit_residuals(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    *,
    width_factor: float = 0.75,
) -> np.ndarray:
    """Return median-subtracted flux residuals with the candidate transit excluded.

    Red-noise (beta) estimation must run on out-of-transit residuals: a real
    transit is a coherent dip, so binned scatter that includes it inflates beta
    and punishes exactly the strongest signals (Pont, Zucker & Queloz 2006 use
    residuals after the transit model is removed). ``width_factor`` widens the
    excluded window slightly beyond the boxed half-duration to keep ingress and
    egress wings out of the noise estimate. Falls back to the full series when
    the mask would leave too few cadences to bin.
    """
    time_arr = np.asarray(time, dtype=np.float64)
    flux_arr = np.asarray(flux, dtype=np.float64)
    if candidate.period <= 0 or candidate.duration <= 0 or time_arr.shape != flux_arr.shape:
        return flux_arr - np.nanmedian(flux_arr)
    phase = ((time_arr - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period
    out_of_transit = np.abs(phase) > width_factor * candidate.duration
    values = flux_arr[out_of_transit]
    values = values[np.isfinite(values)]
    if values.size < 64:
        return flux_arr - np.nanmedian(flux_arr)
    return values - np.nanmedian(values)


def estimate_red_noise_beta(residuals: np.ndarray, bin_sizes: tuple[int, ...] = (5, 10, 20, 40)) -> float:
    values = np.asarray(residuals, dtype=np.float64)
    values = values[np.isfinite(values)]
    if values.size < min(bin_sizes) * 4:
        return 1.0
    white_sigma = float(np.nanstd(values))
    if not math.isfinite(white_sigma) or white_sigma <= 0:
        return 1.0
    betas: list[float] = []
    for bin_size in bin_sizes:
        if values.size < bin_size * 4:
            continue
        usable = values[: values.size // bin_size * bin_size]
        if usable.size == 0:
            continue
        binned = usable.reshape(-1, bin_size).mean(axis=1)
        expected = white_sigma / math.sqrt(bin_size)
        observed = float(np.nanstd(binned))
        if expected > 0 and math.isfinite(observed):
            betas.append(max(1.0, observed / expected))
    if not betas:
        return 1.0
    beta = float(np.nanmedian(betas))
    return beta if math.isfinite(beta) and beta > 0 else 1.0


def phase_coverage_score(time: np.ndarray, candidate: TransitCandidate, bins: int = 24) -> float:
    if candidate.period <= 0:
        return 0.0
    phase = ((np.asarray(time, dtype=np.float64) - candidate.epoch) % candidate.period) / candidate.period
    finite = phase[np.isfinite(phase)]
    if finite.size == 0:
        return 0.0
    occupied = np.unique(np.clip((finite * bins).astype(int), 0, bins - 1)).size
    return float(np.clip(occupied / bins, 0.0, 1.0))


def _score_snr(effective_snr: float, borderline_snr: float, promotion_snr: float) -> float:
    if not math.isfinite(effective_snr) or effective_snr <= 0:
        return 0.0
    anchor = max(promotion_snr * 2.0, promotion_snr + 1.0)
    return float(np.clip((effective_snr - borderline_snr) / (anchor - borderline_snr), 0.0, 1.0))


def _ml_probability(ml: dict[str, Any] | None) -> float | None:
    if not ml:
        return None
    for key in ("calibrated_ml_probability", "probability"):
        value = ml.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(np.clip(value, 0.0, 1.0))
    return None


def build_candidate_evidence(
    *,
    candidate: TransitCandidate,
    search_time: np.ndarray,
    search_flux: np.ndarray,
    validation: dict[str, Any],
    physics: dict[str, Any],
    flags: list[dict[str, Any]],
    ml: dict[str, Any] | None,
    observed_transits: int,
    quality_flag_fraction: float,
    config,
) -> CandidateEvidence:
    residuals = out_of_transit_residuals(search_time, search_flux, candidate)
    beta = estimate_red_noise_beta(residuals)
    effective_snr = float(candidate.signal_to_noise / beta) if beta > 0 else float(candidate.signal_to_noise)
    coverage = phase_coverage_score(search_time, candidate)
    detection_score = _score_snr(effective_snr, config.borderline_snr_min, config.promotion_snr)
    transit_score = float(np.clip(observed_transits / 3.0, 0.0, 1.0))
    coverage_score = coverage
    detection_score = float(0.7 * detection_score + 0.2 * transit_score + 0.1 * coverage_score)

    hard_fails = sum(1 for flag in flags if flag.get("severity") == "hard_fail")
    warnings = sum(1 for flag in flags if flag.get("severity") == "warning")
    vetting_score = float(np.clip(1.0 - hard_fails * 0.65 - warnings * 0.12, 0.0, 1.0))
    data_quality_score = float(
        np.clip(1.0 - quality_flag_fraction / max(config.quality_flag_dominance_fraction, 1e-6), 0.0, 1.0)
    )

    centroid_significance = validation.get("centroid_significance")
    if isinstance(centroid_significance, (int, float)) and math.isfinite(float(centroid_significance)):
        centroid_score = float(np.clip(1.0 - float(centroid_significance) / 3.0, 0.0, 1.0))
    elif validation.get("centroid_shift_flag"):
        centroid_score = 0.25
    else:
        centroid_score = 1.0

    physics_plausibility_score = 0.5 if physics.get("stellar_context_source") == "solar_like_fallback" else 1.0
    ml_score = _ml_probability(ml)
    ml_component = 0.5 if ml_score is None else ml_score
    final_score = float(
        0.25 * detection_score
        + 0.20 * vetting_score
        + 0.15 * data_quality_score
        + 0.15 * centroid_score
        + 0.10 * physics_plausibility_score
        + 0.15 * ml_component
    )
    explanation: list[str] = []
    if effective_snr >= config.borderline_snr_min:
        explanation.append("Recovered periodic transit-like signal")
    if beta >= config.red_noise_warning_beta:
        explanation.append("Red noise reduces effective SNR")
    if validation.get("odd_even_sigma") is not None and not any(
        f.get("code") == "odd_even_depth_mismatch" for f in flags
    ):
        explanation.append("No significant odd/even depth mismatch")
    if validation.get("secondary_snr") is not None and not any(f.get("code") == "secondary_eclipse" for f in flags):
        explanation.append("No strong secondary eclipse")
    if centroid_score >= 0.66:
        explanation.append("Centroid evidence is below rejection threshold")
    if physics.get("stellar_context_source") == "solar_like_fallback":
        explanation.append("Habitability is limited by fallback stellar parameters")
    return CandidateEvidence(
        raw_snr=float(candidate.signal_to_noise),
        red_noise_beta=beta,
        effective_snr=effective_snr,
        transit_count=int(observed_transits),
        phase_coverage_score=coverage,
        detection_score=detection_score,
        vetting_score=vetting_score,
        data_quality_score=data_quality_score,
        centroid_score=centroid_score,
        physics_plausibility_score=physics_plausibility_score,
        ml_score=ml_score,
        final_score=final_score,
        explanation=tuple(explanation),
    )
