from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np

from orbitlab.science.bls import run_bls


@dataclass(frozen=True)
class InjectionCase:
    period_days: float
    depth_ppm: float
    duration_hours: float
    injection_model: str
    recovered: bool
    recovered_period_days: float | None
    period_error_fraction: float | None
    recovered_snr: float | None
    recovered_epoch_days: float | None = None
    epoch_error_fraction: float | None = None
    recovered_depth_ppm: float | None = None
    depth_error_fraction: float | None = None
    failed_gate: str | None = None


def inject_box_transit(
    time: np.ndarray,
    flux: np.ndarray,
    *,
    period_days: float,
    depth_ppm: float,
    duration_hours: float,
    epoch_days: float | None = None,
) -> np.ndarray:
    injected = np.asarray(flux, dtype=np.float32).copy()
    duration_days = duration_hours / 24.0
    epoch = float(epoch_days) if epoch_days is not None else float(np.nanmin(time)) + 0.15 * period_days
    phase = ((np.asarray(time) - epoch + 0.5 * period_days) % period_days) - 0.5 * period_days
    injected[np.abs(phase) <= 0.5 * duration_days] -= depth_ppm / 1_000_000.0
    return injected


def inject_tls_like_transit(
    time: np.ndarray,
    flux: np.ndarray,
    *,
    period_days: float,
    depth_ppm: float,
    duration_hours: float,
    epoch_days: float | None = None,
    impact_parameter: float = 0.2,
    limb_darkening: tuple[float, float] = (0.3, 0.2),
) -> np.ndarray:
    """Inject a smooth transit-shaped dip without requiring a heavy fitting dependency."""
    injected = np.asarray(flux, dtype=np.float32).copy()
    duration_days = duration_hours / 24.0
    epoch = float(epoch_days) if epoch_days is not None else float(np.nanmin(time)) + 0.15 * period_days
    phase = ((np.asarray(time) - epoch + 0.5 * period_days) % period_days) - 0.5 * period_days
    x = np.abs(phase) / max(0.5 * duration_days, np.finfo(float).eps)
    in_transit = x <= 1.0
    if not np.count_nonzero(in_transit):
        return injected

    u1, u2 = limb_darkening
    b = float(np.clip(impact_parameter, 0.0, 0.98))
    chord = np.clip(np.sqrt(np.maximum(0.0, 1.0 - (x[in_transit] ** 2) * (1.0 - b**2))), 0.0, 1.0)
    surface_brightness = 1.0 - u1 * (1.0 - chord) - u2 * (1.0 - chord) ** 2
    surface_brightness = np.clip(surface_brightness, 0.05, None)
    surface_brightness /= max(float(np.nanmax(surface_brightness)), np.finfo(float).eps)
    ingress_taper = 0.5 * (1.0 + np.cos(np.pi * np.clip(x[in_transit], 0.0, 1.0)))
    shape = np.maximum(surface_brightness, 0.25) * np.maximum(ingress_taper, 0.15)
    shape /= max(float(np.nanmax(shape)), np.finfo(float).eps)
    injected[in_transit] -= (depth_ppm / 1_000_000.0) * shape.astype(np.float32)
    return injected


def _period_recovered(found_period: float | None, injected_period: float, tolerance_fraction: float) -> bool:
    if found_period is None or injected_period <= 0:
        return False
    return (
        abs(found_period - injected_period) / injected_period <= tolerance_fraction
        or abs(found_period / injected_period - 0.5) <= tolerance_fraction
        or abs(found_period / injected_period - 2.0) <= tolerance_fraction
    )


def _fractional_error(found: float | None, expected: float) -> float | None:
    if found is None or expected == 0:
        return None
    return abs(float(found) - float(expected)) / abs(float(expected))


def _recovery_case(
    time: np.ndarray,
    flux: np.ndarray,
    *,
    period: float,
    depth: float,
    duration: float,
    injection_model: Literal["box", "tls_like"],
    tolerance_fraction: float = 0.01,
) -> InjectionCase:
    epoch = float(np.nanmin(time)) + 0.15 * period
    if injection_model == "tls_like":
        injected = inject_tls_like_transit(
            time,
            flux,
            period_days=period,
            depth_ppm=depth,
            duration_hours=duration,
            epoch_days=epoch,
        )
    else:
        injected = inject_box_transit(
            time,
            flux,
            period_days=period,
            depth_ppm=depth,
            duration_hours=duration,
            epoch_days=epoch,
        )

    found_period = None
    recovered_epoch = None
    recovered_depth_ppm = None
    period_error = None
    epoch_error = None
    depth_error = None
    snr = None
    failed_gate = None
    recovered = False
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
        recovered_epoch = float(result.candidate.epoch)
        recovered_depth_ppm = float(result.candidate.depth * 1_000_000.0)
        period_error = _fractional_error(found_period, period)
        epoch_error = _fractional_error(recovered_epoch, epoch)
        depth_error = _fractional_error(recovered_depth_ppm, depth)
        snr = float(result.candidate.signal_to_noise)
        recovered = _period_recovered(found_period, period, tolerance_fraction)
        failed_gate = None if recovered else "period_mismatch"
    except (RuntimeError, ValueError) as exc:
        failed_gate = exc.__class__.__name__

    return InjectionCase(
        period_days=period,
        depth_ppm=depth,
        duration_hours=duration,
        injection_model=injection_model,
        recovered=recovered,
        recovered_period_days=found_period,
        period_error_fraction=period_error,
        recovered_snr=snr,
        recovered_epoch_days=recovered_epoch,
        epoch_error_fraction=epoch_error,
        recovered_depth_ppm=recovered_depth_ppm,
        depth_error_fraction=depth_error,
        failed_gate=failed_gate,
    )


def summarize_recovery(cases: list[InjectionCase]) -> dict:
    total = len(cases)
    recovered_count = sum(case.recovered for case in cases)
    by_period: dict[str, dict] = {}
    by_depth: dict[str, dict] = {}
    for case in cases:
        for bucket, key in ((by_period, f"{case.period_days:g}"), (by_depth, f"{case.depth_ppm:g}")):
            row = bucket.setdefault(key, {"total": 0, "recovered": 0, "recovery_probability": None})
            row["total"] += 1
            row["recovered"] += int(case.recovered)
            row["recovery_probability"] = row["recovered"] / row["total"]

    recovered_depths = sorted({case.depth_ppm for case in cases if case.recovered})
    failed_gates: dict[str, int] = {}
    for case in cases:
        if case.recovered:
            continue
        gate = case.failed_gate or "not_recovered"
        failed_gates[gate] = failed_gates.get(gate, 0) + 1

    return {
        "total_cases": total,
        "recovered_cases": recovered_count,
        "recovery_probability": recovered_count / total if total else None,
        "minimum_detectable_depth_ppm": recovered_depths[0] if recovered_depths else None,
        "period_sensitivity": by_period,
        "depth_sensitivity": by_depth,
        "failed_gate_counts": failed_gates,
        "pipeline_sensitivity_score": recovered_count / total if total else None,
    }


def run_recovery_grid(
    time: np.ndarray,
    flux: np.ndarray,
    *,
    period_days: tuple[float, ...] = (3.0, 7.0, 15.0, 30.0),
    depth_ppm: tuple[float, ...] = (100.0, 300.0, 1000.0),
    duration_hours: tuple[float, ...] = (1.0, 2.0, 4.0),
    injection_models: tuple[Literal["box", "tls_like"], ...] = ("box", "tls_like"),
    tolerance_fraction: float = 0.01,
) -> list[InjectionCase]:
    cases: list[InjectionCase] = []
    baseline = float(np.nanmax(time) - np.nanmin(time)) if np.asarray(time).size else 0.0
    for period in period_days:
        if baseline and period > baseline * 0.8:
            continue
        for depth in depth_ppm:
            for duration in duration_hours:
                for injection_model in injection_models:
                    cases.append(
                        _recovery_case(
                            time,
                            flux,
                            period=period,
                            depth=depth,
                            duration=duration,
                            injection_model=injection_model,
                            tolerance_fraction=tolerance_fraction,
                        )
                    )
    return cases


def run_injection_recovery(
    time: np.ndarray,
    flux: np.ndarray,
    *,
    period_days: tuple[float, ...] = (3.0, 7.0, 15.0, 30.0),
    depth_ppm: tuple[float, ...] = (100.0, 300.0, 1000.0),
    duration_hours: tuple[float, ...] = (1.0, 2.0, 4.0),
    injection_models: tuple[Literal["box", "tls_like"], ...] = ("box",),
    tolerance_fraction: float = 0.01,
) -> dict:
    cases = run_recovery_grid(
        time,
        flux,
        period_days=period_days,
        depth_ppm=depth_ppm,
        duration_hours=duration_hours,
        injection_models=injection_models,
        tolerance_fraction=tolerance_fraction,
    )
    summary = summarize_recovery(cases)
    return {
        "status": "complete" if cases else "skipped",
        "engine": "injection_recovery",
        "injection_models": list(injection_models),
        "total_cases": summary["total_cases"],
        "recovered_cases": summary["recovered_cases"],
        "completeness": summary["recovery_probability"],
        "summary": summary,
        "cases": [asdict(case) for case in cases],
    }
