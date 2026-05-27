from __future__ import annotations

from typing import Any

import numpy as np


def _median_cadence_days(time: np.ndarray) -> float:
    ordered = np.sort(np.asarray(time, dtype=np.float64))
    diffs = np.diff(ordered)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if diffs.size == 0:
        return 0.020833333333333332
    return float(np.nanmedian(diffs))


def detrend_with_wotan(
    time: np.ndarray,
    flux: np.ndarray,
    *,
    method: str = "biweight",
    window_length_days: float | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    from wotan import flatten

    clean_time = np.asarray(time, dtype=np.float64)
    clean_flux = np.asarray(flux, dtype=np.float64)
    finite = np.isfinite(clean_time) & np.isfinite(clean_flux)
    clean_time = clean_time[finite]
    clean_flux = clean_flux[finite]
    if clean_time.size < 16:
        raise ValueError("wotan detrending requires at least 16 finite cadences")

    cadence_days = _median_cadence_days(clean_time)
    baseline_days = float(np.nanmax(clean_time) - np.nanmin(clean_time))
    if window_length_days is None:
        window_length_days = float(np.clip(0.75, max(5.0 * cadence_days, 0.1), max(baseline_days / 3.0, 0.1)))
    detrended, trend = flatten(
        clean_time,
        clean_flux,
        method=method,
        window_length=window_length_days,
        return_trend=True,
    )
    detrended = np.asarray(detrended, dtype=np.float32)
    trend = np.asarray(trend, dtype=np.float64)
    if not np.isfinite(detrended).any():
        raise ValueError("wotan detrending produced no finite flux values")
    return detrended, {
        "status": "complete",
        "engine": "wotan",
        "method": method,
        "window_length_days": window_length_days,
        "cadence_days": cadence_days,
        "trend_median": float(np.nanmedian(trend)) if np.isfinite(trend).any() else None,
        "source": "wotan flatten Tukey biweight detrending",
    }
