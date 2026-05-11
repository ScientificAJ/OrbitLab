from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from orbitlab.science.bls import TransitCandidate


@dataclass(frozen=True)
class ValidationMetrics:
    odd_even_depth_delta: float
    secondary_depth: float
    duration_plausible: bool
    harmonic_flag: bool
    sap_pdcsap_agreement: float | None
    centroid_shift_pixels: float | None


def odd_even_depth(time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate) -> float:
    transit_number = np.floor((time - candidate.epoch) / candidate.period).astype(int)
    phase = np.abs(((time - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period)
    in_transit = phase < 0.5 * candidate.duration
    odd = flux[in_transit & (transit_number % 2 == 1)]
    even = flux[in_transit & (transit_number % 2 == 0)]
    valid_odd = odd[~np.isnan(odd)]
    valid_even = even[~np.isnan(even)]
    if valid_odd.size == 0 or valid_even.size == 0:
        return float("nan")
    return float(abs(np.nanmedian(valid_odd) - np.nanmedian(valid_even)))


def secondary_eclipse_depth(time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate) -> float:
    phase = ((time - candidate.epoch) % candidate.period) / candidate.period
    secondary = np.abs(phase - 0.5) < candidate.duration / candidate.period / 2
    if secondary.sum() == 0:
        return float("nan")
    return float(1.0 - np.nanmedian(flux[secondary]))


def duration_plausible(candidate: TransitCandidate) -> bool:
    return 0 < candidate.duration < 0.5 * candidate.period


def harmonic_flag(candidate: TransitCandidate, stellar_rotation_period: float | None = None) -> bool:
    if stellar_rotation_period is None or stellar_rotation_period <= 0:
        return False
    ratio = candidate.period / stellar_rotation_period
    return any(abs(ratio - value) < 0.02 for value in (0.25, 0.5, 1.0, 2.0, 4.0))


def validate_candidate(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    *,
    sap_flux: np.ndarray | None = None,
    pdcsap_flux: np.ndarray | None = None,
    centroid_shift_pixels: float | None = None,
    stellar_rotation_period: float | None = None,
) -> ValidationMetrics:
    agreement = None
    if sap_flux is not None and pdcsap_flux is not None:
        agreement = float(np.corrcoef(np.asarray(sap_flux), np.asarray(pdcsap_flux))[0, 1])
    return ValidationMetrics(
        odd_even_depth_delta=odd_even_depth(np.asarray(time), np.asarray(flux), candidate),
        secondary_depth=secondary_eclipse_depth(np.asarray(time), np.asarray(flux), candidate),
        duration_plausible=duration_plausible(candidate),
        harmonic_flag=harmonic_flag(candidate, stellar_rotation_period),
        sap_pdcsap_agreement=agreement,
        centroid_shift_pixels=centroid_shift_pixels,
    )

