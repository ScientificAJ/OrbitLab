from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from orbitlab.science.data_quality import clean_light_curve


@dataclass(frozen=True)
class TransitCandidate:
    period: float
    epoch: float
    duration: float
    depth: float
    power: float
    signal_to_noise: float


@dataclass(frozen=True)
class BlsResult:
    candidate: TransitCandidate
    periodogram: dict[str, np.ndarray]
    search_time: np.ndarray
    search_flux: np.ndarray
    clean_time: np.ndarray
    clean_flux: np.ndarray
    metadata: dict[str, Any]


def sigma_clip_flux(time: np.ndarray, flux: np.ndarray, sigma: float = 6.0) -> tuple[np.ndarray, np.ndarray]:
    median = np.nanmedian(flux)
    mad = np.nanmedian(np.abs(flux - median))
    if not np.isfinite(mad) or mad == 0:
        return time, flux
    robust_sigma = 1.4826 * mad
    keep = np.abs(flux - median) <= sigma * robust_sigma
    return time[keep], flux[keep]


def bin_light_curve_for_search(
    time: np.ndarray,
    flux: np.ndarray,
    *,
    max_cadences: int = 6000,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    t = np.asarray(time, dtype=np.float64)
    f = np.asarray(flux, dtype=np.float64)
    if t.shape != f.shape:
        raise ValueError("time and flux must have the same shape before BLS binning")
    if max_cadences <= 0 or t.size <= max_cadences:
        return (
            t,
            f,
            {
                "applied": False,
                "input_cadences": int(t.size),
                "search_cadences": int(t.size),
                "bin_size": 1,
            },
        )

    order = np.argsort(t)
    t = t[order]
    f = f[order]
    bin_size = int(np.ceil(t.size / max_cadences))
    binned_time = []
    binned_flux = []
    for start in range(0, t.size, bin_size):
        stop = min(start + bin_size, t.size)
        time_chunk = t[start:stop]
        flux_chunk = f[start:stop]
        finite = np.isfinite(time_chunk) & np.isfinite(flux_chunk)
        if not finite.any():
            continue
        binned_time.append(float(np.nanmedian(time_chunk[finite])))
        binned_flux.append(float(np.nanmedian(flux_chunk[finite])))

    return (
        np.asarray(binned_time, dtype=np.float64),
        np.asarray(binned_flux, dtype=np.float64),
        {
            "applied": True,
            "input_cadences": int(t.size),
            "search_cadences": int(len(binned_time)),
            "bin_size": bin_size,
        },
    )


def _largest_valid_odd_window(size: int, preferred: int) -> int:
    if size < 7:
        return size if size % 2 == 1 else max(size - 1, 1)
    window = min(preferred, size if size % 2 == 1 else size - 1)
    if window % 2 == 0:
        window -= 1
    return max(window, 7)


def transit_safe_flatten(time: np.ndarray, flux: np.ndarray, window: int = 401) -> np.ndarray:
    del time
    flux = np.asarray(flux, dtype=np.float64)
    if flux.size < 7:
        return flux.astype(np.float32)

    window = _largest_valid_odd_window(flux.size, window)
    if window < 7:
        median = np.nanmedian(flux)
        if np.isfinite(median) and median != 0:
            return (flux / median).astype(np.float32)
        return flux.astype(np.float32)

    try:
        from scipy.signal import savgol_filter
    except ImportError as exc:
        raise RuntimeError("scipy is required for transit-safe flattening") from exc

    trend = savgol_filter(flux, window_length=window, polyorder=min(3, window - 2), mode="interp")
    valid_trend = np.isfinite(trend) & (np.abs(trend) > np.finfo(float).eps)
    if not valid_trend.any():
        return flux.astype(np.float32)

    trend_fill = float(np.nanmedian(trend[valid_trend]))
    trend = np.where(valid_trend, trend, trend_fill)
    flat = flux / trend
    flat_median = np.nanmedian(flat)
    if np.isfinite(flat_median) and flat_median != 0:
        flat = flat / flat_median
    return flat.astype(np.float32)


def _cadence_days(time: np.ndarray) -> float:
    ordered = np.sort(np.asarray(time, dtype=np.float64))
    diffs = np.diff(ordered)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if diffs.size == 0:
        return 0.020833333333333332
    return float(np.nanmedian(diffs))


def _clamp_period_range(
    time: np.ndarray,
    min_period: float,
    max_period: float,
    *,
    min_transits: float,
) -> tuple[float, float, float, float]:
    t = np.asarray(time, dtype=np.float64)
    baseline = float(np.nanmax(t) - np.nanmin(t))
    cadence = _cadence_days(t)
    if not np.isfinite(baseline) or baseline <= 0:
        raise ValueError("BLS requires a positive observation baseline")

    safe_min_period = max(float(min_period), 3.0 * cadence, 1e-4)
    safe_max_period = min(float(max_period), baseline / min_transits)

    if safe_max_period <= safe_min_period:
        safe_max_period = min(float(max_period), baseline * 0.8)

    if safe_max_period <= safe_min_period:
        raise ValueError(
            f"invalid BLS period range after baseline clamp: "
            f"requested={min_period:.6g}-{max_period:.6g} days, "
            f"usable_baseline={baseline:.6g} days, "
            f"two_transit_max={baseline / min_transits:.6g} days, "
            f"single_segment_fallback_max={baseline * 0.8:.6g} days. "
            f"Select/stitch longer products for this target."
        )

    return safe_min_period, safe_max_period, baseline, cadence


def _adaptive_duration_grid(
    cadence_days: float,
    min_period: float,
    max_period: float,
    duration_grid: np.ndarray | None,
) -> np.ndarray:
    if duration_grid is not None:
        durations = np.asarray(duration_grid, dtype=np.float64)
        durations = durations[np.isfinite(durations) & (durations > 0)]
        if durations.size == 0:
            raise ValueError("duration_grid must contain at least one positive finite duration")
        return np.unique(durations)

    max_allowed_duration = max(1e-4, 0.8 * min_period)

    min_duration = min(max(2.0 * cadence_days, 0.02), max_allowed_duration / 3.0)
    max_duration = min(0.3, 0.2 * max_period, max_allowed_duration)

    if max_duration <= min_duration:
        max_duration = min(
            max_allowed_duration,
            max(min_duration * 2.0, min_duration + 1e-4),
        )

    durations = np.geomspace(min_duration, max_duration, 16)
    durations = durations[np.isfinite(durations) & (durations > 0) & (durations < min_period)]

    if durations.size == 0:
        durations = np.asarray([max_allowed_duration * 0.5], dtype=np.float64)

    return np.unique(durations).astype(np.float64)


def _build_period_grid(
    model: Any,
    durations: np.ndarray,
    *,
    min_period: float,
    max_period: float,
    period_samples: int,
    max_period_samples: int,
) -> tuple[np.ndarray, str]:
    sample_count = max(period_samples, 32)
    geom_periods = np.geomspace(min_period, max_period, sample_count).astype(np.float64)
    frequencies = np.linspace(1.0 / max_period, 1.0 / min_period, sample_count, dtype=np.float64)
    frequency_periods = np.sort(1.0 / frequencies)
    fallback = np.unique(np.concatenate([geom_periods, frequency_periods])).astype(np.float64)

    try:
        auto_periods = model.autoperiod(
            durations,
            minimum_period=min_period,
            maximum_period=max_period,
            minimum_n_transit=2,
            frequency_factor=1.0,
        )
        grid_source = "astropy_autoperiod_plus_geomspace_and_frequency_floor"
    except TypeError:
        auto_periods = model.autoperiod(
            durations,
            minimum_period=min_period,
            maximum_period=max_period,
            frequency_factor=1.0,
        )
        grid_source = "astropy_autoperiod_plus_geomspace_and_frequency_floor"
    except Exception:
        auto_periods = np.asarray([], dtype=np.float64)
        grid_source = "geomspace_and_frequency_fallback"

    periods = np.unique(np.concatenate([np.asarray(auto_periods, dtype=np.float64), fallback]))
    periods = periods[np.isfinite(periods) & (periods >= min_period) & (periods <= max_period)]

    if periods.size < 32:
        periods = fallback
        grid_source = "geomspace_and_frequency_fallback"

    if periods.size > max_period_samples:
        indices = np.unique(np.linspace(0, periods.size - 1, max_period_samples).astype(int))
        periods = periods[indices]
        grid_source = f"{grid_source}_capped"

    return periods.astype(np.float64), grid_source


def _robust_scatter(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=np.float64)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0
    median = float(np.nanmedian(finite))
    mad = float(np.nanmedian(np.abs(finite - median)))
    if np.isfinite(mad) and mad > 0:
        return 1.4826 * mad
    std = float(np.nanstd(finite))
    return std if np.isfinite(std) else 0.0


def _transit_detection_snr(
    time: np.ndarray,
    flux: np.ndarray,
    *,
    period: float,
    epoch: float,
    duration: float,
    depth: float,
) -> float:
    if period <= 0 or duration <= 0 or depth <= 0:
        return 0.0

    phase = ((time - epoch + 0.5 * period) % period) - 0.5 * period
    in_transit = np.abs(phase) <= 0.5 * duration
    if int(np.count_nonzero(in_transit)) < 2:
        return 0.0

    out_of_transit = np.abs(phase) >= duration
    scatter_source = flux[out_of_transit] if np.count_nonzero(out_of_transit) >= 16 else flux
    scatter = _robust_scatter(scatter_source - np.nanmedian(scatter_source))
    if scatter <= 0:
        return 0.0

    return float(depth / scatter * np.sqrt(np.count_nonzero(in_transit)))


def run_bls(
    time: np.ndarray,
    flux: np.ndarray,
    *,
    min_period: float = 0.5,
    max_period: float = 30.0,
    duration_grid: np.ndarray | None = None,
    period_samples: int = 8192,
    max_period_samples: int = 50000,
    min_transits: float = 2.0,
    max_search_cadences: int = 6000,
) -> BlsResult:
    clean_time, clean_flux = clean_light_curve(time, flux)
    clipped_time, clipped_flux = sigma_clip_flux(clean_time, clean_flux)

    if clipped_time.size < 64:
        raise ValueError("BLS requires at least 64 cadences after quality filtering and sigma clipping")

    snr_flux = transit_safe_flatten(clipped_time, clipped_flux)
    search_time, search_flux_source, binning = bin_light_curve_for_search(
        clipped_time,
        snr_flux,
        max_cadences=max_search_cadences,
    )

    if search_time.size < 64:
        raise ValueError("BLS requires at least 64 cadences after adaptive search binning")

    search_flux = transit_safe_flatten(search_time, search_flux_source)

    min_period, max_period, baseline_days, cadence_days = _clamp_period_range(
        search_time,
        min_period,
        max_period,
        min_transits=min_transits,
    )

    durations = _adaptive_duration_grid(cadence_days, min_period, max_period, duration_grid)

    try:
        from astropy.timeseries import BoxLeastSquares
    except ImportError as exc:
        raise RuntimeError("astropy is required for BLS detection") from exc

    model = BoxLeastSquares(search_time.astype(np.float64), search_flux.astype(np.float64))
    cadence_bound_period_samples = max(4096, int(search_time.size * 2))
    effective_max_period_samples = min(max_period_samples, cadence_bound_period_samples)
    periods, grid_source = _build_period_grid(
        model,
        durations,
        min_period=min_period,
        max_period=max_period,
        period_samples=period_samples,
        max_period_samples=effective_max_period_samples,
    )

    result = model.power(periods, durations)
    power_array = np.asarray(result.power, dtype=np.float64)
    finite_power = np.isfinite(power_array)

    if not finite_power.any():
        raise ValueError("BLS periodogram produced no finite power values")

    index = int(np.nanargmax(power_array))

    period = float(result.period[index])
    epoch = float(result.transit_time[index])
    duration = float(result.duration[index])
    depth = float(max(result.depth[index], 0.0))
    power = float(result.power[index])

    snr = _transit_detection_snr(
        clipped_time,
        snr_flux,
        period=period,
        epoch=epoch,
        duration=duration,
        depth=depth,
    )

    metadata: dict[str, Any] = {
        "baseline_days": baseline_days,
        "cadence_days": cadence_days,
        "min_period_days": min_period,
        "max_period_days": max_period,
        "min_transits_required": min_transits,
        "period_grid_source": grid_source,
        "period_count": int(np.asarray(result.period).size),
        "max_period_samples_requested": int(max_period_samples),
        "max_period_samples_effective": int(effective_max_period_samples),
        "duration_count": int(durations.size),
        "min_duration_days": float(np.nanmin(durations)),
        "max_duration_days": float(np.nanmax(durations)),
        "sigma_clip_kept_cadences": int(clipped_time.size),
        "clean_cadences": int(clean_time.size),
        "search_binning": binning,
        "snr_estimator": "depth_over_out_of_transit_mad_times_sqrt_in_transit_cadences",
    }

    return BlsResult(
        candidate=TransitCandidate(period, epoch, duration, depth, power, snr),
        periodogram={
            "period": np.asarray(result.period, dtype=np.float32),
            "power": np.asarray(result.power, dtype=np.float32),
            "duration": np.asarray(result.duration, dtype=np.float32),
        },
        search_time=search_time.astype(np.float32),
        search_flux=search_flux.astype(np.float32),
        clean_time=clean_time.astype(np.float32),
        clean_flux=clean_flux.astype(np.float32),
        metadata=metadata,
    )


def mask_transit_windows(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    width_factor: float = 1.5,
) -> tuple[np.ndarray, np.ndarray]:
    phase = ((time - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period
    keep = np.abs(phase) > width_factor * candidate.duration
    return time[keep], flux[keep]


def find_multi_planet_candidates(
    time: np.ndarray,
    flux: np.ndarray,
    *,
    max_candidates: int = 4,
    initial_candidate: TransitCandidate | None = None,
    min_period: float = 0.5,
    max_period: float = 30.0,
    duration_grid: np.ndarray | None = None,
    period_samples: int = 8192,
    max_period_samples: int = 50000,
    min_signal_to_noise: float = 6.0,
    preserve_initial_candidate: bool = False,
) -> list[TransitCandidate]:
    residual_time = np.asarray(time)
    residual_flux = np.asarray(flux)
    candidates: list[TransitCandidate] = []

    if initial_candidate is not None:
        if preserve_initial_candidate or initial_candidate.signal_to_noise >= min_signal_to_noise:
            candidates.append(initial_candidate)
            residual_time, residual_flux = mask_transit_windows(residual_time, residual_flux, initial_candidate)
            max_candidates -= 1
        else:
            return []

    for _ in range(max_candidates):
        if residual_time.size < 128:
            break

        try:
            bls_result = run_bls(
                residual_time,
                residual_flux,
                min_period=min_period,
                max_period=max_period,
                duration_grid=duration_grid,
                period_samples=period_samples,
                max_period_samples=max_period_samples,
            )
        except (ValueError, RuntimeError):
            break

        candidate = bls_result.candidate

        if candidate.signal_to_noise < min_signal_to_noise:
            break

        candidates.append(candidate)
        residual_time, residual_flux = mask_transit_windows(residual_time, residual_flux, candidate)

    return candidates
