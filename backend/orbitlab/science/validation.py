from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np

from orbitlab.science.bls import TransitCandidate


@dataclass(frozen=True)
class ValidationMetrics:
    odd_even_depth_delta: float
    odd_even_sigma: float | None
    secondary_depth: float
    secondary_snr: float | None
    duration_plausible: bool
    harmonic_flag: bool
    sap_pdcsap_agreement: float | None
    centroid_shift_pixels: float | None
    centroid_uncertainty_pixels: float | None
    centroid_significance: float | None
    centroid_shift_flag: bool
    false_positive_flags: tuple[str, ...]


def _robust_scatter(values: np.ndarray) -> float:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return float("nan")
    median = float(np.nanmedian(finite))
    mad = float(np.nanmedian(np.abs(finite - median)))
    if np.isfinite(mad) and mad > 0:
        return 1.4826 * mad
    std = float(np.nanstd(finite))
    return std if np.isfinite(std) and std > 0 else float("nan")


def odd_even_depth(time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate) -> float:
    odd_depth, even_depth, _, _ = odd_even_depths_with_uncertainty(time, flux, candidate)
    if not np.isfinite(odd_depth) or not np.isfinite(even_depth):
        return float("nan")
    return float(abs(odd_depth - even_depth))


def odd_even_depths_with_uncertainty(
    time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate
) -> tuple[float, float, float, float]:
    transit_number = np.floor((time - candidate.epoch) / candidate.period).astype(int)
    phase = np.abs(((time - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period)
    in_transit = phase < 0.5 * candidate.duration
    out_of_transit = phase > candidate.duration
    baseline = (
        float(np.nanmedian(flux[out_of_transit])) if np.count_nonzero(out_of_transit) else float(np.nanmedian(flux))
    )
    scatter = (
        _robust_scatter(flux[out_of_transit] - baseline)
        if np.count_nonzero(out_of_transit)
        else _robust_scatter(flux - baseline)
    )
    depths = []
    errors = []
    for parity in (1, 0):
        values = flux[in_transit & (transit_number % 2 == parity)]
        values = values[np.isfinite(values)]
        if values.size == 0:
            depths.append(float("nan"))
            errors.append(float("nan"))
            continue
        depths.append(max(0.0, baseline - float(np.nanmedian(values))))
        errors.append(float(scatter / math.sqrt(values.size)) if np.isfinite(scatter) and scatter > 0 else float("nan"))
    return depths[0], depths[1], errors[0], errors[1]


def odd_even_significance(odd_depth: float, even_depth: float, odd_err: float, even_err: float) -> float | None:
    denom = math.sqrt(odd_err**2 + even_err**2) if np.isfinite(odd_err) and np.isfinite(even_err) else float("nan")
    if denom <= 0 or not np.isfinite(denom):
        return None
    return float(abs(odd_depth - even_depth) / denom)


def secondary_eclipse_depth(time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate) -> float:
    phase = ((time - candidate.epoch) % candidate.period) / candidate.period
    secondary = np.abs(phase - 0.5) < candidate.duration / candidate.period / 2
    if secondary.sum() == 0:
        return float("nan")
    return float(1.0 - np.nanmedian(flux[secondary]))


def secondary_eclipse_snr(time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate) -> float | None:
    phase_time = ((time - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period
    phase = ((time - candidate.epoch) % candidate.period) / candidate.period
    secondary = np.abs(phase - 0.5) < candidate.duration / candidate.period / 2
    primary_or_secondary = (np.abs(phase_time) < 0.5 * candidate.duration) | secondary
    baseline_values = flux[~primary_or_secondary]
    baseline = float(np.nanmedian(baseline_values)) if baseline_values.size else float(np.nanmedian(flux))
    depth = baseline - float(np.nanmedian(flux[secondary])) if secondary.any() else float("nan")
    scatter = _robust_scatter(baseline_values - baseline if baseline_values.size else flux - baseline)
    if (
        not np.isfinite(depth)
        or depth <= 0
        or not np.isfinite(scatter)
        or scatter <= 0
        or np.count_nonzero(secondary) == 0
    ):
        return None
    return float(depth / scatter * math.sqrt(np.count_nonzero(secondary)))


def duration_plausible(candidate: TransitCandidate) -> bool:
    return 0 < candidate.duration < 0.5 * candidate.period


def harmonic_flag(candidate: TransitCandidate, stellar_rotation_period: float | None = None) -> bool:
    if stellar_rotation_period is None or stellar_rotation_period <= 0:
        return False
    ratio = candidate.period / stellar_rotation_period
    return any(abs(ratio - value) < 0.02 for value in (0.25, 0.5, 1.0, 2.0, 4.0))


def false_positive_flags(
    *,
    candidate: TransitCandidate,
    odd_even_delta: float,
    odd_even_sigma: float | None,
    secondary_depth: float,
    secondary_snr: float | None,
    duration_ok: bool,
    harmonic: bool,
    centroid_shift_pixels: float | None,
    centroid_significance: float | None,
    sap_pdcsap_agreement: float | None,
) -> tuple[str, ...]:
    flags: list[str] = []
    if candidate.signal_to_noise < 7.1:
        flags.append("low_snr")
    if not duration_ok:
        flags.append("implausible_duration")
    if harmonic:
        flags.append("stellar_rotation_harmonic")
    if odd_even_sigma is not None and odd_even_sigma >= 2.0:
        flags.append("odd_even_depth_mismatch")
    elif np.isfinite(odd_even_delta) and candidate.depth > 0 and odd_even_delta > 0.5 * candidate.depth:
        flags.append("odd_even_depth_mismatch")
    if secondary_snr is not None and secondary_snr >= 3.0:
        flags.append("secondary_eclipse")
    elif np.isfinite(secondary_depth) and candidate.depth > 0 and secondary_depth > 0.5 * candidate.depth:
        flags.append("secondary_eclipse")
    if centroid_significance is not None:
        if centroid_significance >= 2.0:
            flags.append("centroid_shift")
    elif centroid_shift_pixels is not None and np.isfinite(centroid_shift_pixels) and centroid_shift_pixels > 1.0:
        flags.append("centroid_shift")
    if sap_pdcsap_agreement is not None and np.isfinite(sap_pdcsap_agreement) and sap_pdcsap_agreement < 0.8:
        flags.append("sap_pdcsap_disagreement")
    return tuple(flags)


def validate_candidate(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    *,
    sap_flux: np.ndarray | None = None,
    pdcsap_flux: np.ndarray | None = None,
    centroid_shift_pixels: float | None = None,
    centroid_uncertainty_pixels: float | None = None,
    stellar_rotation_period: float | None = None,
) -> ValidationMetrics:
    time_arr = np.asarray(time)
    flux_arr = np.asarray(flux)
    agreement = None
    if sap_flux is not None and pdcsap_flux is not None:
        agreement = float(np.corrcoef(np.asarray(sap_flux), np.asarray(pdcsap_flux))[0, 1])
    odd_depth, even_depth, odd_err, even_err = odd_even_depths_with_uncertainty(time_arr, flux_arr, candidate)
    odd_even_delta = (
        float(abs(odd_depth - even_depth)) if np.isfinite(odd_depth) and np.isfinite(even_depth) else float("nan")
    )
    odd_even_sigma = odd_even_significance(odd_depth, even_depth, odd_err, even_err)
    secondary_depth_value = secondary_eclipse_depth(time_arr, flux_arr, candidate)
    secondary_snr_value = secondary_eclipse_snr(time_arr, flux_arr, candidate)
    duration_ok = duration_plausible(candidate)
    harmonic = harmonic_flag(candidate, stellar_rotation_period)
    centroid_significance = None
    if (
        centroid_shift_pixels is not None
        and centroid_uncertainty_pixels is not None
        and np.isfinite(centroid_shift_pixels)
        and np.isfinite(centroid_uncertainty_pixels)
        and centroid_uncertainty_pixels > 0
    ):
        centroid_significance = float(abs(centroid_shift_pixels) / centroid_uncertainty_pixels)
    centroid_flag = bool(
        centroid_significance >= 2.0
        if centroid_significance is not None
        else centroid_shift_pixels is not None and np.isfinite(centroid_shift_pixels) and centroid_shift_pixels > 1.0
    )
    flags = false_positive_flags(
        candidate=candidate,
        odd_even_delta=odd_even_delta,
        odd_even_sigma=odd_even_sigma,
        secondary_depth=secondary_depth_value,
        secondary_snr=secondary_snr_value,
        duration_ok=duration_ok,
        harmonic=harmonic,
        centroid_shift_pixels=centroid_shift_pixels,
        centroid_significance=centroid_significance,
        sap_pdcsap_agreement=agreement,
    )
    return ValidationMetrics(
        odd_even_depth_delta=odd_even_delta,
        odd_even_sigma=odd_even_sigma,
        secondary_depth=secondary_depth_value,
        secondary_snr=secondary_snr_value,
        duration_plausible=duration_ok,
        harmonic_flag=harmonic,
        sap_pdcsap_agreement=agreement,
        centroid_shift_pixels=centroid_shift_pixels,
        centroid_uncertainty_pixels=centroid_uncertainty_pixels,
        centroid_significance=centroid_significance,
        centroid_shift_flag=centroid_flag,
        false_positive_flags=flags,
    )
