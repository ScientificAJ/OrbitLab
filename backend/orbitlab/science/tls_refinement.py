from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from orbitlab.science.bls import TransitCandidate


@dataclass(frozen=True)
class TlsRefinement:
    status: str
    period_days: float | None = None
    duration_days: float | None = None
    epoch_days: float | None = None
    depth_fraction: float | None = None
    snr: float | None = None
    period_agreement_fraction: float | None = None
    model_shape_score: str | None = None
    detail: str | None = None


def _finite_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def _finite_int(value) -> int | None:
    number = _finite_float(value)
    if number is None:
        return None
    return int(number)


def refine_with_tls(time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate) -> dict:
    try:
        from transitleastsquares import transitleastsquares
    except ImportError as exc:
        return asdict(TlsRefinement(status="unavailable", detail=f"transitleastsquares is not installed: {exc}"))
    try:
        model = transitleastsquares(np.asarray(time, dtype=float), np.asarray(flux, dtype=float))
        results = model.power(period_min=max(0.05, candidate.period * 0.8), period_max=candidate.period * 1.2)
        period = float(results.period)
        agreement = abs(period - candidate.period) / candidate.period if candidate.period > 0 else None
        snr = float(getattr(results, "snr", np.nan))
        return asdict(
            TlsRefinement(
                status="complete",
                period_days=period,
                duration_days=float(getattr(results, "duration", np.nan)),
                epoch_days=float(getattr(results, "T0", np.nan)),
                depth_fraction=float(getattr(results, "depth", np.nan)),
                snr=snr if np.isfinite(snr) else None,
                period_agreement_fraction=agreement,
                model_shape_score="planet_like" if agreement is not None and agreement <= 0.01 else "mismatch",
            )
        )
    except Exception as exc:
        return asdict(TlsRefinement(status="failed", detail=str(exc)))


def search_with_tls(
    time: np.ndarray,
    flux: np.ndarray,
    *,
    min_period: float,
    max_period: float,
    stellar_radius_solar: float | None = None,
    stellar_mass_solar: float | None = None,
    transit_depth_min: float = 10e-6,
    n_transits_min: int = 2,
    oversampling_factor: int = 3,
    duration_grid_step: float = 1.1,
) -> dict:
    try:
        from transitleastsquares import transitleastsquares
    except ImportError as exc:
        return {
            "status": "unavailable",
            "engine": "transitleastsquares",
            "detail": f"transitleastsquares is not installed: {exc}",
        }
    try:
        clean_time = np.asarray(time, dtype=float)
        clean_flux = np.asarray(flux, dtype=float)
        finite = np.isfinite(clean_time) & np.isfinite(clean_flux)
        clean_time = clean_time[finite]
        clean_flux = clean_flux[finite]
        if clean_time.size < 16:
            raise ValueError("TLS requires at least 16 finite cadences")

        model = transitleastsquares(clean_time, clean_flux)
        parameters = {
            "period_min": max(float(min_period), 0.05),
            "period_max": float(max_period),
            "n_transits_min": int(n_transits_min),
            "transit_depth_min": float(transit_depth_min),
            "oversampling_factor": int(oversampling_factor),
            "duration_grid_step": float(duration_grid_step),
            "show_progress_bar": False,
        }
        if stellar_radius_solar and stellar_radius_solar > 0:
            parameters["R_star"] = float(stellar_radius_solar)
        if stellar_mass_solar and stellar_mass_solar > 0:
            parameters["M_star"] = float(stellar_mass_solar)
        results = model.power(**parameters)
        periods = getattr(results, "periods", None)
        return {
            "status": "complete",
            "engine": "transitleastsquares",
            "period_days": _finite_float(getattr(results, "period", None)),
            "duration_days": _finite_float(getattr(results, "duration", None)),
            "epoch_days": _finite_float(getattr(results, "T0", None)),
            "depth_fraction": _finite_float(getattr(results, "depth", None)),
            "snr": _finite_float(getattr(results, "snr", None)),
            "sde": _finite_float(getattr(results, "SDE", None)),
            "sde_raw": _finite_float(getattr(results, "SDE_raw", None)),
            "fap": _finite_float(getattr(results, "FAP", None)),
            "transit_count": _finite_int(getattr(results, "transit_count", None)),
            "distinct_transit_count": _finite_int(getattr(results, "distinct_transit_count", None)),
            "period_uncertainty": _finite_float(getattr(results, "period_uncertainty", None)),
            "periodogram_period_count": int(len(periods)) if periods is not None else None,
            "period_range": {"min": parameters["period_min"], "max": parameters["period_max"]},
            "thresholds": {
                "transit_depth_min": transit_depth_min,
                "n_transits_min": n_transits_min,
                "oversampling_factor": oversampling_factor,
                "duration_grid_step": duration_grid_step,
            },
            "source": "Hippke & Heller 2019 transitleastsquares",
        }
    except Exception as exc:
        return {"status": "failed", "engine": "transitleastsquares", "detail": str(exc)}
