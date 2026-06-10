from __future__ import annotations

from typing import Any

import numpy as np

from orbitlab.science.bls import TransitCandidate, run_bls
from orbitlab.science.detrending import detrend_with_wotan


def _finite_float(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _mask_candidate_transits(time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate) -> np.ndarray:
    phase = ((np.asarray(time) - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period
    in_transit = np.abs(phase) <= 0.5 * candidate.duration
    masked = np.asarray(flux, dtype=np.float64).copy()
    oot = masked[~in_transit & np.isfinite(masked)]
    fill = float(np.nanmedian(oot)) if oot.size else float(np.nanmedian(masked))
    masked[in_transit] = fill
    return masked


def _candidate_metrics(label: str, time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate) -> dict[str, Any]:
    period_min = max(0.05, candidate.period * 0.8)
    period_max = max(period_min * 1.05, candidate.period * 1.2)
    result = run_bls(
        time,
        flux,
        min_period=period_min,
        max_period=period_max,
        period_samples=2048,
        max_period_samples=4096,
    )
    found = result.candidate
    return {
        "label": label,
        "status": "passed",
        "period_days": _finite_float(found.period),
        "epoch_days": _finite_float(found.epoch),
        "depth_fraction": _finite_float(found.depth),
        "depth_ppm": _finite_float(found.depth * 1_000_000.0),
        "duration_days": _finite_float(found.duration),
        "snr": _finite_float(found.signal_to_noise),
        "period_error_fraction": abs(found.period - candidate.period) / candidate.period if candidate.period else None,
    }


def _spread(values: list[float]) -> float | None:
    finite = np.asarray([value for value in values if np.isfinite(value)], dtype=np.float64)
    if finite.size < 2:
        return None
    median = float(np.nanmedian(np.abs(finite)))
    if median <= 0 or not np.isfinite(median):
        return None
    return float((np.nanmax(finite) - np.nanmin(finite)) / median)


def run_detrending_sensitivity(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    *,
    window_lengths_days: tuple[float, ...] = (0.5, 0.75, 1.5),
) -> dict[str, Any]:
    clean_time = np.asarray(time, dtype=np.float64)
    clean_flux = np.asarray(flux, dtype=np.float64)
    finite = np.isfinite(clean_time) & np.isfinite(clean_flux)
    clean_time = clean_time[finite]
    clean_flux = clean_flux[finite]
    if clean_time.size < 64:
        return {"status": "insufficient_data", "engine": "detrending_sensitivity", "methods": []}

    methods: list[dict[str, Any]] = []
    variants: list[tuple[str, np.ndarray]] = [("raw_cleaned_flux", clean_flux)]
    for window in window_lengths_days:
        try:
            detrended, _ = detrend_with_wotan(
                clean_time,
                clean_flux,
                method="biweight",
                window_length_days=window,
            )
            variants.append((f"wotan_biweight_{window:g}d", detrended))
        except (RuntimeError, ValueError, ImportError) as exc:
            methods.append({"label": f"wotan_biweight_{window:g}d", "status": "failed", "detail": str(exc)})

    try:
        # Transit-masked detrending: estimate the trend with the candidate's
        # transits replaced by the local baseline, then divide the ORIGINAL
        # flux by that trend. Detrending the masked flux directly would erase
        # the transit signal itself, so this variant would always disagree
        # with the others and falsely mark every strong candidate unstable.
        from wotan import flatten

        masked_flux = _mask_candidate_transits(clean_time, clean_flux, candidate)
        _, masked_trend = flatten(
            clean_time,
            masked_flux,
            method="biweight",
            window_length=0.75,
            return_trend=True,
        )
        masked_trend = np.asarray(masked_trend, dtype=np.float64)
        trend_valid = np.isfinite(masked_trend) & (np.abs(masked_trend) > np.finfo(float).eps)
        if not trend_valid.any():
            raise ValueError("transit-masked wotan trend produced no finite values")
        trend_fill = float(np.nanmedian(masked_trend[trend_valid]))
        masked_trend = np.where(trend_valid, masked_trend, trend_fill)
        variants.append(("transit_masked_wotan_biweight_0.75d", clean_flux / masked_trend))
    except (RuntimeError, ValueError, ImportError) as exc:
        methods.append({"label": "transit_masked_wotan_biweight_0.75d", "status": "failed", "detail": str(exc)})

    for label, variant_flux in variants:
        try:
            methods.append(_candidate_metrics(label, clean_time, np.asarray(variant_flux), candidate))
        except (RuntimeError, ValueError) as exc:
            methods.append({"label": label, "status": "failed", "detail": str(exc)})

    passed = [method for method in methods if method.get("status") == "passed"]
    if not passed:
        return {"status": "inconclusive", "engine": "detrending_sensitivity", "methods": methods}

    periods = [float(method["period_days"]) for method in passed if method.get("period_days") is not None]
    depths = [float(method["depth_ppm"]) for method in passed if method.get("depth_ppm") is not None]
    epochs = [float(method["epoch_days"]) for method in passed if method.get("epoch_days") is not None]
    snrs = [float(method["snr"]) for method in passed if method.get("snr") is not None]
    period_spread = _spread(periods)
    depth_spread = _spread(depths)
    epoch_spread = _spread(epochs)
    snr_spread = _spread(snrs)
    worst = min(passed, key=lambda method: float(method.get("snr") or 0.0))
    period_stable = period_spread is None or period_spread <= 0.02
    depth_stable = depth_spread is None or depth_spread <= 0.5
    epoch_stable = epoch_spread is None or epoch_spread <= 0.05
    snr_stable = snr_spread is None or snr_spread <= 0.5
    stable = bool(period_stable and depth_stable and epoch_stable and snr_stable)
    return {
        "status": "passed" if stable else "unstable_result",
        "engine": "detrending_sensitivity",
        "period_stable": period_stable,
        "depth_stable": depth_stable,
        "epoch_stable": epoch_stable,
        "snr_stable": snr_stable,
        "period_spread_fraction": period_spread,
        "depth_spread_fraction": depth_spread,
        "epoch_spread_fraction": epoch_spread,
        "snr_spread_fraction": snr_spread,
        "methods_tested": len(passed),
        "worst_case_result": worst,
        "methods": methods,
    }
