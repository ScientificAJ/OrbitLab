from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from orbitlab.science.bls import run_bls


@dataclass(frozen=True)
class InjectionCase:
    period_days: float
    depth_ppm: float
    duration_hours: float
    recovered: bool
    recovered_period_days: float | None
    period_error_fraction: float | None
    recovered_snr: float | None


def inject_box_transit(
    time: np.ndarray, flux: np.ndarray, *, period_days: float, depth_ppm: float, duration_hours: float
) -> np.ndarray:
    injected = np.asarray(flux, dtype=np.float32).copy()
    duration_days = duration_hours / 24.0
    epoch = float(np.nanmin(time)) + 0.15 * period_days
    phase = ((np.asarray(time) - epoch + 0.5 * period_days) % period_days) - 0.5 * period_days
    injected[np.abs(phase) <= 0.5 * duration_days] -= depth_ppm / 1_000_000.0
    return injected


def run_injection_recovery(
    time: np.ndarray,
    flux: np.ndarray,
    *,
    period_days: tuple[float, ...] = (3.0, 7.0, 15.0, 30.0),
    depth_ppm: tuple[float, ...] = (100.0, 300.0, 1000.0),
    duration_hours: tuple[float, ...] = (1.0, 2.0, 4.0),
    tolerance_fraction: float = 0.01,
) -> dict:
    cases: list[InjectionCase] = []
    baseline = float(np.nanmax(time) - np.nanmin(time)) if np.asarray(time).size else 0.0
    for period in period_days:
        if baseline and period > baseline * 0.8:
            continue
        for depth in depth_ppm:
            for duration in duration_hours:
                injected = inject_box_transit(time, flux, period_days=period, depth_ppm=depth, duration_hours=duration)
                recovered = False
                found_period = None
                period_error = None
                snr = None
                try:
                    result = run_bls(
                        time,
                        injected,
                        min_period=max(0.1, period * 0.8),
                        max_period=period * 1.2,
                        period_samples=2048,
                        max_period_samples=4096,
                    )
                    found_period = float(result.candidate.period)
                    period_error = abs(found_period - period) / period
                    snr = float(result.candidate.signal_to_noise)
                    recovered = (
                        period_error <= tolerance_fraction
                        or abs(found_period / period - 0.5) <= tolerance_fraction
                        or abs(found_period / period - 2.0) <= tolerance_fraction
                    )
                except (RuntimeError, ValueError):
                    pass
                cases.append(InjectionCase(period, depth, duration, recovered, found_period, period_error, snr))
    total = len(cases)
    recovered_count = sum(case.recovered for case in cases)
    return {
        "status": "complete" if total else "skipped",
        "engine": "box_injection_recovery",
        "total_cases": total,
        "recovered_cases": recovered_count,
        "completeness": recovered_count / total if total else None,
        "cases": [asdict(case) for case in cases],
    }
