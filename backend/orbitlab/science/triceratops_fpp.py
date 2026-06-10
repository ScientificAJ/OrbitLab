from __future__ import annotations

import re
from typing import Any

import numpy as np

from orbitlab.science.bls import TransitCandidate
from orbitlab.science.catalog_context import parse_tic_id


def _patch_legacy_science_imports() -> None:
    if not hasattr(np, "int"):
        np.int = int  # type: ignore[attr-defined]
    if not hasattr(np, "float"):
        np.float = float  # type: ignore[attr-defined]
    if not hasattr(np, "complex"):
        np.complex = complex  # type: ignore[attr-defined]

    import scipy.integrate as integrate

    if not hasattr(integrate, "trapz"):
        integrate.trapz = np.trapz  # type: ignore[attr-defined]


def parse_tess_sector(product_uri: str | None) -> int | None:
    if not product_uri:
        return None
    match = re.search(r"(?:^|[-_/])[sS](\d{4})(?:[-_/.]|$)", product_uri)
    return int(match.group(1)) if match else None


def parse_tic_from_product_uri(product_uri: str | None) -> int | None:
    """Recover the TIC id from a TESS product URI.

    Name-based searches (e.g. "L 98-59") resolve products whose URIs embed the
    zero-padded TIC (SPOC: ``...-0000000307210830-...``, HLSP TESS-SPOC:
    ``..._0000000307210830-s0008_...``); without this fallback TRICERATOPS
    would be unavailable for every target the user typed by name.
    """
    if not product_uri:
        return None
    match = re.search(r"[-_](\d{13,16})[-_]", product_uri)
    if match:
        return int(match.group(1))
    return None


def _phase_time(time: np.ndarray, candidate: TransitCandidate) -> np.ndarray:
    return ((time - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period


def _bin_for_triceratops(
    phase_time: np.ndarray,
    flux: np.ndarray,
    bins: int = 100,
) -> tuple[np.ndarray, np.ndarray, float]:
    finite = np.isfinite(phase_time) & np.isfinite(flux)
    x = np.asarray(phase_time[finite], dtype=np.float64)
    y = np.asarray(flux[finite], dtype=np.float64)
    if x.size < 16:
        raise ValueError("TRICERATOPS requires at least 16 finite folded cadences")
    order = np.argsort(x)
    x = x[order]
    y = y[order]
    edges = np.linspace(float(np.nanmin(x)), float(np.nanmax(x)), bins + 1)
    binned_time = []
    binned_flux = []
    for left, right in zip(edges[:-1], edges[1:], strict=True):
        mask = (x >= left) & (x < right)
        if not np.count_nonzero(mask):
            continue
        binned_time.append(float(np.nanmedian(x[mask])))
        binned_flux.append(float(np.nanmedian(y[mask])))
    residual = y - float(np.nanmedian(y))
    flux_err = float(np.nanstd(residual))
    if not np.isfinite(flux_err) or flux_err <= 0:
        raise ValueError("TRICERATOPS flux error estimate is invalid")
    return np.asarray(binned_time), np.asarray(binned_flux), flux_err


def _aperture_pixels(aperture_mask: np.ndarray | None) -> np.ndarray | None:
    if aperture_mask is None:
        return None
    mask = np.asarray(aperture_mask, dtype=bool)
    if mask.ndim != 2 or not mask.any():
        return None
    return np.argwhere(mask).astype(int)


def run_triceratops_fpp(
    *,
    target_id: str,
    product_uri: str | None,
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    aperture_mask: np.ndarray | None = None,
    samples: int = 1_000_000,
    parallel: bool = False,
) -> dict[str, Any]:
    _patch_legacy_science_imports()
    import triceratops.triceratops as tr

    tic_id = parse_tic_id(target_id)
    if tic_id is None:
        tic_id = parse_tic_from_product_uri(product_uri)
    if tic_id is None:
        raise ValueError(
            f"TRICERATOPS requires a numeric TIC id; none found in target {target_id!r} or its product URI"
        )
    sector = parse_tess_sector(product_uri)
    if sector is None:
        raise ValueError("TRICERATOPS requires a TESS sector parsed from the selected product URI")

    folded_time = _phase_time(np.asarray(time, dtype=np.float64), candidate)
    binned_time, binned_flux, flux_err = _bin_for_triceratops(folded_time, np.asarray(flux, dtype=np.float64))
    target = tr.target(ID=tic_id, sectors=np.asarray([sector], dtype=int))
    aperture_pixels = _aperture_pixels(aperture_mask)
    calc_depths_used = False
    calc_depths_detail = None
    if aperture_pixels is not None and hasattr(target, "calc_depths"):
        try:
            target.calc_depths(tdepth=float(candidate.depth), all_ap_pixels=aperture_pixels)
            calc_depths_used = True
        except (TypeError, ValueError, RuntimeError, AttributeError) as exc:
            calc_depths_detail = str(exc)
    target.calc_probs(
        time=binned_time,
        flux_0=binned_flux,
        flux_err_0=flux_err,
        P_orb=float(candidate.period),
        N=int(samples),
        parallel=parallel,
        verbose=0,
    )
    probs = getattr(target, "probs", None)
    probabilities = probs.to_dict(orient="records") if hasattr(probs, "to_dict") else None
    return {
        "status": "complete",
        "engine": "triceratops",
        "target_id": tic_id,
        "sector": sector,
        "fpp": float(target.FPP),
        "nfpp": float(target.NFPP),
        "samples": int(samples),
        "parallel": parallel,
        "fpp_uncertainty": None,
        "nfpp_uncertainty": None,
        "aperture_used": aperture_pixels is not None,
        "aperture_pixel_count": int(aperture_pixels.shape[0]) if aperture_pixels is not None else 0,
        "calc_depths_used": calc_depths_used,
        "calc_depths_detail": calc_depths_detail,
        "contrast_curve_used": False,
        "flux_err": flux_err,
        "probabilities": probabilities,
        "scenario_probabilities": probabilities,
        "validation_thresholds": {"fpp_max": 0.015, "nfpp_max": 0.001},
        "source": "TRICERATOPS calc_depths + calc_probs" if calc_depths_used else "TRICERATOPS calc_probs",
    }
