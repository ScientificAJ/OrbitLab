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
