from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from orbitlab.science.bls import TransitCandidate, run_bls
from orbitlab.science.tpf_diagnostics import aperture_stability_diagnostics, difference_image_diagnostics


@dataclass(frozen=True)
class SectorObservation:
    sector_id: str
    time: np.ndarray
    flux: np.ndarray
    quality: np.ndarray | None = None
    pixel_flux: np.ndarray | None = None
    aperture_mask: np.ndarray | None = None
    pixel_scale_arcsec: float | None = None


def infer_sector_id(product_uri: str | None, *, fallback: str = "current") -> str:
    if not product_uri:
        return fallback
    value = str(product_uri)
    patterns = (
        r"sector[-_ ]?(\d+)",
        r"tess\d{13}-s(\d{4})",
        r"[-_]s(\d{4})",
        r"q(\d+)",
        r"campaign[-_ ]?(\d+)",
        r"[-_]c(\d{2})",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            return match.group(1).lstrip("0") or match.group(1)
    return fallback


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _observed_transit_count(time: np.ndarray, candidate: TransitCandidate) -> int:
    if candidate.period <= 0:
        return 0
    t = np.asarray(time, dtype=np.float64)
    finite = t[np.isfinite(t)]
    if finite.size == 0:
        return 0
    first = float(np.nanmin(finite))
    last = float(np.nanmax(finite))
    epoch = float(candidate.epoch)
    while epoch > first:
        epoch -= candidate.period
    count = 0
    while epoch <= last:
        if epoch >= first:
            count += 1
        epoch += candidate.period
    return count


def _sector_evidence(observation: SectorObservation, candidate: TransitCandidate) -> dict[str, Any]:
    time = np.asarray(observation.time, dtype=np.float64)
    flux = np.asarray(observation.flux, dtype=np.float64)
    finite = np.isfinite(time) & np.isfinite(flux)
    time = time[finite]
    flux = flux[finite]
    evidence: dict[str, Any] = {
        "sector_id": observation.sector_id,
        "cadence_count": int(time.size),
        "transit_count": _observed_transit_count(time, candidate),
    }
    if time.size < 64:
        return evidence | {"status": "insufficient_data"}
    try:
        result = run_bls(
            time,
            flux,
            min_period=max(0.05, candidate.period * 0.8),
            max_period=max(candidate.period * 1.2, candidate.period + 0.05),
            period_samples=2048,
            max_period_samples=4096,
        )
        found = result.candidate
        evidence.update(
            {
                "status": "complete",
                "period_days": _finite_float(found.period),
                "period_support": _finite_float(
                    1.0 - min(abs(found.period - candidate.period) / candidate.period, 1.0)
                    if candidate.period
                    else None
                ),
                "depth_ppm": _finite_float(found.depth * 1_000_000.0),
                "duration_hours": _finite_float(found.duration * 24.0),
                "snr": _finite_float(found.signal_to_noise),
            }
        )
    except (RuntimeError, ValueError) as exc:
        evidence.update({"status": "failed", "detail": str(exc)})

    centroid = difference_image_diagnostics(
        time=time,
        pixel_flux=observation.pixel_flux,
        candidate=candidate,
        pixel_scale_arcsec=observation.pixel_scale_arcsec,
    )
    aperture = aperture_stability_diagnostics(
        time=time,
        pixel_flux=observation.pixel_flux,
        candidate=candidate,
        selected_mask=observation.aperture_mask,
    )
    evidence["centroid_offset"] = _finite_float(centroid.get("centroid_shift_arcsec"))
    evidence["centroid_status"] = centroid.get("status")
    evidence["aperture_score"] = _finite_float(aperture.get("score"))
    evidence["contamination_warning"] = bool(
        centroid.get("centroid_significance") is not None and float(centroid["centroid_significance"]) >= 2.0
    )
    return evidence


def summarize_sector_consistency(
    candidate: TransitCandidate,
    observations: list[SectorObservation],
) -> dict[str, Any]:
    if not observations:
        return {
            "status": "insufficient_data",
            "multi_sector_status": "insufficient_data",
            "sector_evidence": [],
        }
    sector_evidence = [_sector_evidence(observation, candidate) for observation in observations]
    complete = [row for row in sector_evidence if row.get("status") == "complete"]
    if len(observations) == 1:
        return {
            "status": "single_sector_only",
            "multi_sector_status": "single_sector_only",
            "sector_count": 1,
            "sector_evidence": sector_evidence,
        }
    if len(complete) < 2:
        return {
            "status": "insufficient_data",
            "multi_sector_status": "insufficient_data",
            "sector_count": len(observations),
            "sector_evidence": sector_evidence,
        }

    periods = np.asarray([row["period_days"] for row in complete if row.get("period_days") is not None])
    depths = np.asarray([row["depth_ppm"] for row in complete if row.get("depth_ppm") is not None])
    period_spread = float((np.nanmax(periods) - np.nanmin(periods)) / candidate.period) if periods.size > 1 else None
    depth_median = float(np.nanmedian(depths)) if depths.size else None
    depth_spread = (
        float((np.nanmax(depths) - np.nanmin(depths)) / abs(depth_median))
        if depths.size > 1 and depth_median not in {None, 0.0}
        else None
    )
    inconsistent = bool(
        (period_spread is not None and period_spread > 0.02)
        or (depth_spread is not None and depth_spread > 0.75)
        or any(row.get("contamination_warning") for row in complete)
    )
    return {
        "status": "inconsistent" if inconsistent else "consistent",
        "multi_sector_status": "inconsistent" if inconsistent else "consistent",
        "sector_count": len(observations),
        "period_spread_fraction": period_spread,
        "depth_spread_fraction": depth_spread,
        "sector_evidence": sector_evidence,
    }
