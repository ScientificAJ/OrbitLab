from __future__ import annotations

import math
from typing import Any

import numpy as np

from orbitlab.science.bls import TransitCandidate


def _finite_arrays(time: np.ndarray, flux: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    t = np.asarray(time, dtype=float)
    f = np.asarray(flux, dtype=float)
    finite = np.isfinite(t) & np.isfinite(f)
    return t[finite], f[finite]


def _robust_scatter(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    median = float(np.nanmedian(arr))
    mad = float(np.nanmedian(np.abs(arr - median)))
    scatter = 1.4826 * mad
    if not np.isfinite(scatter) or scatter <= 0:
        scatter = float(np.nanstd(arr))
    return scatter


def _phase_time(time: np.ndarray, candidate: TransitCandidate, offset_days: float = 0.0) -> np.ndarray:
    return ((time - candidate.epoch - offset_days + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period


def _window_mask(time: np.ndarray, candidate: TransitCandidate, center_days: float, width_days: float) -> np.ndarray:
    return np.abs(_phase_time(time, candidate, center_days)) <= 0.5 * width_days


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def _erfcinv(value: float) -> float:
    y = min(max(float(value), 1e-300), 2.0 - 1e-16)
    low = -12.0
    high = 12.0
    for _ in range(96):
        mid = 0.5 * (low + high)
        if math.erfc(mid) > y:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def _false_alarm_sigma(probability: float) -> float:
    sigma = math.sqrt(2.0) * _erfcinv(probability)
    if not np.isfinite(sigma):
        return 3.0
    return max(3.0, sigma)


def _dave_sigma_thresholds(time: np.ndarray, candidate: TransitCandidate, objects_evaluated: int) -> dict[str, float]:
    baseline_days = float(np.nanmax(time) - np.nanmin(time)) if time.size else 0.0
    period = max(float(candidate.period), np.finfo(float).eps)
    search_trials = max(float(objects_evaluated), 1.0)
    sigfa1_probability = baseline_days / (period * search_trials)
    sigfa2_probability = baseline_days / period
    return {
        "sigfa1": _false_alarm_sigma(sigfa1_probability),
        "sigfa2": _false_alarm_sigma(sigfa2_probability),
        "objects_evaluated": float(objects_evaluated),
    }


def _depth_significance(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    *,
    center_days: float,
    baseline: float,
    scatter: float,
) -> tuple[float, float, int]:
    mask = _window_mask(time, candidate, center_days, candidate.duration)
    count = int(np.count_nonzero(mask))
    if count == 0 or not np.isfinite(scatter) or scatter <= 0:
        return 0.0, 0.0, count
    depth = baseline - float(np.nanmedian(flux[mask]))
    significance = depth / scatter * math.sqrt(count)
    return float(depth), float(significance), count


def _brightening_significance(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    *,
    center_days: float,
    baseline: float,
    scatter: float,
) -> tuple[float, float, int]:
    mask = _window_mask(time, candidate, center_days, candidate.duration)
    count = int(np.count_nonzero(mask))
    if count == 0 or not np.isfinite(scatter) or scatter <= 0:
        return 0.0, 0.0, count
    height = float(np.nanmedian(flux[mask])) - baseline
    significance = height / scatter * math.sqrt(count)
    return float(height), float(significance), count


def _transit_depth_series(
    time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate, *, baseline: float
) -> list[float]:
    transit_number = np.floor((time - candidate.epoch) / candidate.period).astype(int)
    primary_mask = _window_mask(time, candidate, 0.0, candidate.duration)
    depths: list[float] = []
    for number in np.unique(transit_number[primary_mask]):
        mask = primary_mask & (transit_number == number)
        if np.count_nonzero(mask):
            depths.append(max(0.0, baseline - float(np.nanmedian(flux[mask]))))
    return depths


def _red_noise_factor(time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate, scatter: float) -> float:
    if time.size < 8 or not np.isfinite(scatter) or scatter <= 0:
        return 1.0
    cadence = np.diff(np.sort(time))
    cadence = cadence[np.isfinite(cadence) & (cadence > 0)]
    if cadence.size == 0:
        return 1.0
    bin_size = max(2, int(round(candidate.duration / float(np.nanmedian(cadence)))))
    if bin_size <= 1 or time.size < bin_size * 3:
        return 1.0
    residual = flux - float(np.nanmedian(flux))
    usable = residual[: residual.size - residual.size % bin_size]
    if usable.size == 0:
        return 1.0
    binned = np.nanmean(usable.reshape(-1, bin_size), axis=1)
    expected = scatter / math.sqrt(bin_size)
    measured = _robust_scatter(binned)
    if not np.isfinite(measured) or not np.isfinite(expected) or expected <= 0:
        return 1.0
    return float(max(1.0, measured / expected))


def run_sweet_test(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    *,
    threshold_sigma: float = 3.0,
) -> dict[str, Any]:
    t, f = _finite_arrays(time, flux)
    if t.size < 16 or candidate.period <= 0 or candidate.duration <= 0:
        return {"status": "insufficient_data", "engine": "sweet", "threshold_sigma": threshold_sigma}
    out_of_transit = np.abs(_phase_time(t, candidate)) > candidate.duration
    if np.count_nonzero(out_of_transit) < 8:
        return {"status": "insufficient_data", "engine": "sweet", "threshold_sigma": threshold_sigma}
    oot_time = t[out_of_transit]
    oot_flux = f[out_of_transit] - float(np.nanmedian(f[out_of_transit]))
    rows = []
    max_sigma = 0.0
    for label, period in (
        ("half_period", candidate.period / 2.0),
        ("period", candidate.period),
        ("double_period", candidate.period * 2.0),
    ):
        if period <= 0:
            continue
        omega = 2.0 * math.pi / period
        design = np.column_stack((np.sin(omega * oot_time), np.cos(omega * oot_time), np.ones_like(oot_time)))
        try:
            coefficients, *_ = np.linalg.lstsq(design, oot_flux, rcond=None)
        except np.linalg.LinAlgError:
            continue
        model = design @ coefficients
        residual_scatter = _robust_scatter(oot_flux - model)
        amplitude = float(math.hypot(float(coefficients[0]), float(coefficients[1])))
        amplitude_uncertainty = residual_scatter / math.sqrt(max(oot_time.size / 2.0, 1.0))
        sigma = amplitude / amplitude_uncertainty if amplitude_uncertainty > 0 else 0.0
        max_sigma = max(max_sigma, sigma)
        rows.append(
            {
                "period_tested_days": period,
                "period_label": label,
                "amplitude": amplitude,
                "sigma": sigma,
                "threshold_sigma": threshold_sigma,
                "status": "warning" if sigma >= threshold_sigma else "pass",
            }
        )
    return {
        "status": "warning" if any(row["status"] == "warning" for row in rows) else "pass",
        "engine": "sweet",
        "threshold_sigma": threshold_sigma,
        "max_sigma": max_sigma,
        "periods": rows,
        "source": "DAVE SWEET sinusoid search at P/2, P, and 2P",
    }


def run_model_shift(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    *,
    objects_evaluated: int = 20000,
) -> dict[str, Any]:
    t, f = _finite_arrays(time, flux)
    if t.size < 16 or candidate.period <= 0 or candidate.duration <= 0:
        return {"status": "insufficient_data", "engine": "dave_model_shift"}
    out_of_transit = np.abs(_phase_time(t, candidate)) > candidate.duration
    baseline = float(np.nanmedian(f[out_of_transit])) if np.count_nonzero(out_of_transit) else float(np.nanmedian(f))
    scatter = (
        _robust_scatter(f[out_of_transit] - baseline)
        if np.count_nonzero(out_of_transit)
        else _robust_scatter(f - baseline)
    )
    if not np.isfinite(scatter) or scatter <= 0:
        return {"status": "insufficient_data", "engine": "dave_model_shift"}

    primary_depth, primary_sigma, primary_count = _depth_significance(
        t, f, candidate, center_days=0.0, baseline=baseline, scatter=scatter
    )
    centers = np.linspace(-0.5 * candidate.period, 0.5 * candidate.period, 161, endpoint=False)
    candidates = []
    positives = []
    for center in centers:
        if abs(center) <= candidate.duration:
            continue
        depth, depth_sigma, count = _depth_significance(
            t,
            f,
            candidate,
            center_days=float(center),
            baseline=baseline,
            scatter=scatter,
        )
        height, height_sigma, _ = _brightening_significance(
            t, f, candidate, center_days=float(center), baseline=baseline, scatter=scatter
        )
        candidates.append({"center_days": float(center), "depth": depth, "sigma": depth_sigma, "count": count})
        positives.append({"center_days": float(center), "height": height, "sigma": height_sigma, "count": count})
    candidates.sort(key=lambda row: row["sigma"], reverse=True)
    positives.sort(key=lambda row: row["sigma"], reverse=True)
    secondary = candidates[0] if candidates else {"center_days": None, "depth": 0.0, "sigma": 0.0, "count": 0}
    tertiary = next(
        (
            row
            for row in candidates[1:]
            if secondary["center_days"] is None
            or abs(float(row["center_days"]) - float(secondary["center_days"])) > candidate.duration
        ),
        {"center_days": None, "depth": 0.0, "sigma": 0.0, "count": 0},
    )
    positive = positives[0] if positives else {"center_days": None, "height": 0.0, "sigma": 0.0, "count": 0}
    thresholds = _dave_sigma_thresholds(t, candidate, objects_evaluated)
    fred = _red_noise_factor(t, f, candidate, scatter)
    sigfa1 = thresholds["sigfa1"]
    sigfa2 = thresholds["sigfa2"]
    normalized_primary = primary_sigma / fred if fred else primary_sigma
    normalized_secondary = float(secondary["sigma"]) / fred if fred else float(secondary["sigma"])
    normalized_tertiary = float(tertiary["sigma"]) / fred if fred else float(tertiary["sigma"])
    normalized_positive = float(positive["sigma"]) / fred if fred else float(positive["sigma"])

    transit_depths = _transit_depth_series(t, f, candidate, baseline=baseline)
    if transit_depths:
        median_depth = float(np.nanmedian(transit_depths))
        mean_depth = float(np.nanmean(transit_depths))
        dmm = mean_depth / median_depth if median_depth > 0 else float("inf")
    else:
        dmm = float("inf")
    shape_metric = (
        max(normalized_secondary, normalized_positive) / max(normalized_primary, np.finfo(float).eps)
        if normalized_primary > 0
        else float("inf")
    )

    odd_even_sigma = 0.0
    if len(transit_depths) >= 3:
        even = np.asarray(transit_depths[::2], dtype=float)
        odd = np.asarray(transit_depths[1::2], dtype=float)
        if even.size and odd.size:
            err = math.sqrt(max(np.nanvar(even), 0.0) / even.size + max(np.nanvar(odd), 0.0) / odd.size)
            odd_even_sigma = abs(float(np.nanmean(even) - np.nanmean(odd))) / err if err > 0 else 0.0

    flags = []
    if normalized_primary < sigfa1:
        flags.append("not_transit_like")
    if normalized_primary - normalized_tertiary < sigfa2:
        flags.append("primary_tertiary_margin")
    if normalized_primary - normalized_positive < sigfa2:
        flags.append("primary_positive_margin")
    if dmm > 1.5:
        flags.append("depth_mean_median_ratio")
    if shape_metric > 0.3:
        flags.append("shape_metric")
    if normalized_secondary > sigfa1:
        flags.append("significant_secondary")
    if odd_even_sigma > sigfa1:
        flags.append("odd_even_depth_mismatch")

    return {
        "status": "fail" if flags else "pass",
        "engine": "dave_model_shift",
        "hard_fail": bool(flags),
        "flags": flags,
        "primary": {
            "depth": primary_depth,
            "sigma": primary_sigma,
            "normalized_sigma": normalized_primary,
            "count": primary_count,
        },
        "secondary": secondary,
        "tertiary": tertiary,
        "positive": positive,
        "thresholds": thresholds,
        "fred": fred,
        "dmm": _safe_float(dmm),
        "shape_metric": _safe_float(shape_metric),
        "odd_even_sigma": _safe_float(odd_even_sigma),
        "source": "DAVE RoboVet model-shift threshold structure",
    }
