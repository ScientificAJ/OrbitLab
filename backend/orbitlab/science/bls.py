from __future__ import annotations

from dataclasses import dataclass
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


def sigma_clip_flux(time: np.ndarray, flux: np.ndarray, sigma: float = 6.0) -> tuple[np.ndarray, np.ndarray]:
    median = np.nanmedian(flux)
    mad = np.nanmedian(np.abs(flux - median))
    if not np.isfinite(mad) or mad == 0:
        return time, flux
    robust_sigma = 1.4826 * mad
    keep = np.abs(flux - median) <= sigma * robust_sigma
    return time[keep], flux[keep]


def transit_safe_flatten(time: np.ndarray, flux: np.ndarray, window: int = 401) -> np.ndarray:
    if window % 2 == 0:
        window += 1
    if flux.size < window:
        return flux.astype(np.float32)
    try:
        from scipy.signal import savgol_filter
    except ImportError as exc:  # pragma: no cover - depends on optional science install
        raise RuntimeError("scipy is required for transit-safe flattening") from exc
    trend = savgol_filter(flux, window_length=window, polyorder=3)
    trend[trend == 0] = np.nanmedian(trend[trend != 0])
    return (flux / trend).astype(np.float32)


def run_bls(
    time: np.ndarray,
    flux: np.ndarray,
    *,
    min_period: float = 0.5,
    max_period: float = 30.0,
    duration_grid: np.ndarray | None = None,
    period_samples: int = 4096,
) -> tuple[TransitCandidate, dict[str, np.ndarray]]:
    t, f = clean_light_curve(time, flux)
    t, f = sigma_clip_flux(t, f)
    flat = transit_safe_flatten(t, f)
    try:
        from astropy.timeseries import BoxLeastSquares
    except ImportError as exc:  # pragma: no cover - depends on optional science install
        raise RuntimeError("astropy is required for BLS detection") from exc
    periods = np.linspace(min_period, max_period, period_samples, dtype=np.float64)
    durations = duration_grid if duration_grid is not None else np.linspace(0.04, 0.3, 12)
    model = BoxLeastSquares(t.astype(np.float64), flat.astype(np.float64))
    result = model.power(periods, durations)
    index = int(np.nanargmax(result.power))
    period = float(result.period[index])
    epoch = float(result.transit_time[index])
    duration = float(result.duration[index])
    depth = float(max(result.depth[index], 0.0))
    power = float(result.power[index])
    std = float(np.nanstd(flat - np.nanmedian(flat)))
    snr = float(depth / std) if std > 0 else 0.0
    return TransitCandidate(period, epoch, duration, depth, power, snr), {
        "period": np.asarray(result.period, dtype=np.float32),
        "power": np.asarray(result.power, dtype=np.float32),
        "duration": np.asarray(result.duration, dtype=np.float32),
    }


def mask_transit_windows(time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate, width_factor: float = 1.5) -> tuple[np.ndarray, np.ndarray]:
    phase = ((time - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period
    keep = np.abs(phase) > width_factor * candidate.duration
    return time[keep], flux[keep]


def find_multi_planet_candidates(
    time: np.ndarray,
    flux: np.ndarray,
    *,
    max_candidates: int = 4,
    initial_candidate: TransitCandidate | None = None,
    period_samples: int = 4096,
) -> list[TransitCandidate]:
    residual_time = np.asarray(time)
    residual_flux = np.asarray(flux)
    candidates: list[TransitCandidate] = []
    
    if initial_candidate is not None:
        if initial_candidate.signal_to_noise >= 6.0:
            candidates.append(initial_candidate)
            residual_time, residual_flux = mask_transit_windows(residual_time, residual_flux, initial_candidate)
            max_candidates -= 1
        else:
            return []

    for _ in range(max_candidates):
        candidate, _ = run_bls(residual_time, residual_flux, period_samples=period_samples)
        if candidate.signal_to_noise < 6.0:
            break
        candidates.append(candidate)
        residual_time, residual_flux = mask_transit_windows(residual_time, residual_flux, candidate)
        if residual_time.size < 128:
            break
    return candidates

