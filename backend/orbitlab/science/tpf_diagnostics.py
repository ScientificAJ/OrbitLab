from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from orbitlab.science.bls import TransitCandidate
from orbitlab.science.prf_centroid import fit_point_source


@dataclass(frozen=True)
class TpfLightCurveBundle:
    time: np.ndarray
    flux: np.ndarray
    quality: np.ndarray | None
    pixel_flux: np.ndarray | None
    selected_mask: np.ndarray | None
    pipeline_mask: np.ndarray | None
    threshold_mask: np.ndarray | None
    pixel_scale_arcsec: float | None
    reference_row: float | None
    reference_column: float | None


def _finite_float(value: float | None) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return float(value)


def _robust_scatter(values: np.ndarray) -> float:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return float("nan")
    median = float(np.nanmedian(finite))
    mad = float(np.nanmedian(np.abs(finite - median)))
    if np.isfinite(mad) and mad > 0:
        return 1.4826 * mad
    std = float(np.nanstd(finite))
    return std if np.isfinite(std) and std > 0 else float("nan")


def transit_masks(time: np.ndarray, candidate: TransitCandidate) -> tuple[np.ndarray, np.ndarray]:
    time_arr = np.asarray(time, dtype=np.float64)
    if candidate.period <= 0 or candidate.duration <= 0:
        empty = np.zeros(time_arr.shape, dtype=bool)
        return empty, np.isfinite(time_arr)
    phase_time = ((time_arr - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period
    in_transit = np.isfinite(time_arr) & (np.abs(phase_time) <= 0.5 * candidate.duration)
    out_of_transit = np.isfinite(time_arr) & (np.abs(phase_time) >= candidate.duration)
    return in_transit, out_of_transit


def _centroid(image: np.ndarray) -> tuple[float, float] | None:
    arr = np.asarray(image, dtype=np.float64)
    finite = np.isfinite(arr)
    if not finite.any():
        return None
    floor = float(np.nanpercentile(arr[finite], 5))
    weights = np.where(finite, arr - floor, 0.0)
    weights = np.where(weights > 0, weights, 0.0)
    total = float(np.nansum(weights))
    if total <= 0 or not np.isfinite(total):
        return None
    rows, cols = np.indices(arr.shape, dtype=np.float64)
    return float(np.nansum(rows * weights) / total), float(np.nansum(cols * weights) / total)


def _centroid_series(cube: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    rows: list[float] = []
    cols: list[float] = []
    for image in cube[mask]:
        center = _centroid(image)
        if center is None:
            continue
        rows.append(center[0])
        cols.append(center[1])
    return np.asarray(rows, dtype=np.float64), np.asarray(cols, dtype=np.float64)


def difference_image_diagnostics(
    *,
    time: np.ndarray,
    pixel_flux: np.ndarray | None,
    candidate: TransitCandidate,
    pixel_scale_arcsec: float | None = None,
) -> dict[str, Any]:
    if pixel_flux is None:
        return {"status": "unavailable", "reason": "target pixel flux cube was not provided"}
    cube = np.asarray(pixel_flux, dtype=np.float64)
    if cube.ndim != 3 or cube.shape[0] != np.asarray(time).size:
        return {"status": "unavailable", "reason": "target pixel flux cube shape does not match time array"}
    in_transit, out_of_transit = transit_masks(time, candidate)
    if np.count_nonzero(in_transit) < 2 or np.count_nonzero(out_of_transit) < 2:
        return {"status": "insufficient_data", "in_transit_cadences": int(np.count_nonzero(in_transit))}

    in_image = np.nanmedian(cube[in_transit], axis=0)
    out_image = np.nanmedian(cube[out_of_transit], axis=0)
    diff_image = out_image - in_image
    oot_scatter = np.nanstd(cube[out_of_transit], axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        pixel_snr = diff_image / oot_scatter * math.sqrt(float(np.count_nonzero(in_transit)))
    finite_snr = np.where(np.isfinite(pixel_snr), pixel_snr, -np.inf)
    peak_index = (
        np.unravel_index(int(np.nanargmax(finite_snr)), finite_snr.shape)
        if np.isfinite(finite_snr).any()
        else None
    )

    in_center = _centroid(in_image)
    out_center = _centroid(out_image)
    diff_positive = np.where(diff_image > 0, diff_image, 0.0)
    diff_center = _centroid(diff_positive)
    centroid_shift_pixels = None
    centroid_uncertainty_pixels = None
    centroid_significance = None
    if in_center is not None and out_center is not None:
        row_shift = in_center[0] - out_center[0]
        col_shift = in_center[1] - out_center[1]
        centroid_shift_pixels = math.hypot(row_shift, col_shift)
        in_rows, in_cols = _centroid_series(cube, in_transit)
        out_rows, out_cols = _centroid_series(cube, out_of_transit)
        row_unc = 0.0
        col_unc = 0.0
        if in_rows.size > 1:
            row_unc += (_robust_scatter(in_rows) / math.sqrt(in_rows.size)) ** 2
        if out_rows.size > 1:
            row_unc += (_robust_scatter(out_rows) / math.sqrt(out_rows.size)) ** 2
        if in_cols.size > 1:
            col_unc += (_robust_scatter(in_cols) / math.sqrt(in_cols.size)) ** 2
        if out_cols.size > 1:
            col_unc += (_robust_scatter(out_cols) / math.sqrt(out_cols.size)) ** 2
        centroid_uncertainty_pixels = math.sqrt(row_unc + col_unc)
        if centroid_uncertainty_pixels > 0 and np.isfinite(centroid_uncertainty_pixels):
            centroid_significance = centroid_shift_pixels / centroid_uncertainty_pixels

    # PSF-fit upgrade (DV-style): localize the transit source by fitting a
    # point-source model to the difference image and compare against the
    # fitted out-of-transit target position. When both fits succeed the
    # fitted offset/uncertainty REPLACE the moment-based values consumed by
    # the centroid gates (the moment numbers stay available for audit);
    # otherwise behavior is unchanged and provenance says so.
    centroid_method = "image_moment_fallback"
    # The OOT fit is windowed around the target: a single-source model on the
    # full cutout is biased by neighbor stars. The difference image isolates
    # the varying source by construction, so it uses the full frame.
    psf_out = fit_point_source(out_image, pixel_noise=oot_scatter, initial=out_center, fit_radius=3.5)
    psf_diff = fit_point_source(diff_positive, pixel_noise=oot_scatter, initial=diff_center)
    moment_shift_pixels = centroid_shift_pixels
    moment_uncertainty_pixels = centroid_uncertainty_pixels
    moment_significance = centroid_significance
    psf_offset_pixels = None
    psf_offset_uncertainty = None
    psf_offset_significance = None
    if psf_out is not None and psf_diff is not None:
        psf_offset_pixels = math.hypot(psf_diff.row - psf_out.row, psf_diff.col - psf_out.col)
        psf_offset_uncertainty = math.sqrt(
            psf_out.row_uncertainty**2
            + psf_out.col_uncertainty**2
            + psf_diff.row_uncertainty**2
            + psf_diff.col_uncertainty**2
        )
        if psf_offset_uncertainty > 0 and np.isfinite(psf_offset_uncertainty):
            psf_offset_significance = psf_offset_pixels / psf_offset_uncertainty
            centroid_method = "psf_fit"
            centroid_shift_pixels = psf_offset_pixels
            centroid_uncertainty_pixels = psf_offset_uncertainty
            centroid_significance = psf_offset_significance

    payload: dict[str, Any] = {
        "status": "complete",
        "in_transit_cadences": int(np.count_nonzero(in_transit)),
        "out_of_transit_cadences": int(np.count_nonzero(out_of_transit)),
        "centroid_shift_pixels": _finite_float(centroid_shift_pixels),
        "centroid_uncertainty_pixels": _finite_float(centroid_uncertainty_pixels),
        "centroid_significance": _finite_float(centroid_significance),
        "centroid_shift_arcsec": _finite_float(
            centroid_shift_pixels * pixel_scale_arcsec
            if centroid_shift_pixels is not None and pixel_scale_arcsec is not None
            else None
        ),
        "difference_centroid_row": _finite_float(diff_center[0] if diff_center else None),
        "difference_centroid_column": _finite_float(diff_center[1] if diff_center else None),
        "oot_centroid_row": _finite_float(out_center[0] if out_center else None),
        "oot_centroid_column": _finite_float(out_center[1] if out_center else None),
        "centroid_method": centroid_method,
        "moment_centroid_shift_pixels": _finite_float(moment_shift_pixels),
        "moment_centroid_uncertainty_pixels": _finite_float(moment_uncertainty_pixels),
        "moment_centroid_significance": _finite_float(moment_significance),
        "psf_offset_pixels": _finite_float(psf_offset_pixels),
        "psf_offset_uncertainty_pixels": _finite_float(psf_offset_uncertainty),
        "psf_offset_significance": _finite_float(psf_offset_significance),
        "psf_fit_out": psf_out.as_dict() if psf_out is not None else None,
        "psf_fit_diff": psf_diff.as_dict() if psf_diff is not None else None,
    }
    if peak_index is not None:
        payload["peak_pixel"] = {
            "row": int(peak_index[0]),
            "column": int(peak_index[1]),
            "snr": _finite_float(float(finite_snr[peak_index])),
            "depth_flux": _finite_float(float(diff_image[peak_index])),
        }
    return payload


def _mask_light_curve(cube: np.ndarray, mask: np.ndarray) -> np.ndarray:
    return np.nansum(cube[:, mask], axis=1).astype(np.float64)


def _candidate_snr_from_flux(time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate) -> float | None:
    in_transit, out_of_transit = transit_masks(time, candidate)
    if np.count_nonzero(in_transit) == 0 or np.count_nonzero(out_of_transit) < 2:
        return None
    baseline = float(np.nanmedian(flux[out_of_transit]))
    depth = baseline - float(np.nanmedian(flux[in_transit]))
    scatter = _robust_scatter(flux[out_of_transit] - baseline)
    if not np.isfinite(depth) or depth <= 0 or not np.isfinite(scatter) or scatter <= 0:
        return None
    return float(depth / scatter * math.sqrt(np.count_nonzero(in_transit)))


def aperture_stability_diagnostics(
    *,
    time: np.ndarray,
    pixel_flux: np.ndarray | None,
    candidate: TransitCandidate,
    selected_mask: np.ndarray | None = None,
    percentiles: tuple[int, ...] = (80, 85, 90, 92, 95),
) -> dict[str, Any]:
    if pixel_flux is None:
        return {"status": "unavailable", "reason": "target pixel flux cube was not provided"}
    cube = np.asarray(pixel_flux, dtype=np.float64)
    if cube.ndim != 3 or cube.shape[0] != np.asarray(time).size:
        return {"status": "unavailable", "reason": "target pixel flux cube shape does not match time array"}
    median_image = np.nanmedian(cube, axis=0)
    finite = np.isfinite(median_image)
    if not finite.any():
        return {"status": "insufficient_data", "reason": "median target pixel image has no finite pixels"}

    records: list[dict[str, Any]] = []
    masks: list[tuple[str, np.ndarray]] = []
    if selected_mask is not None:
        selected = np.asarray(selected_mask, dtype=bool)
        if selected.shape == median_image.shape and selected.any():
            masks.append(("selected", selected))
    for percentile in percentiles:
        threshold = float(np.nanpercentile(median_image[finite], percentile))
        mask = finite & (median_image >= threshold)
        if mask.any():
            masks.append((f"p{percentile}", mask))

    seen: set[bytes] = set()
    for label, mask in masks:
        key = np.asarray(mask, dtype=np.uint8).tobytes()
        if key in seen:
            continue
        seen.add(key)
        flux = _mask_light_curve(cube, mask)
        snr = _candidate_snr_from_flux(np.asarray(time), flux, candidate)
        records.append({
            "mask": label,
            "selected_pixels": int(np.count_nonzero(mask)),
            "snr": _finite_float(snr),
        })

    snrs = np.asarray([row["snr"] for row in records if row.get("snr") is not None], dtype=np.float64)
    if snrs.size == 0:
        return {"status": "insufficient_data", "apertures": records}
    median_snr = float(np.nanmedian(snrs))
    relative_scatter = float(np.nanstd(snrs) / abs(median_snr)) if median_snr else float("inf")
    selected_snr = next((row["snr"] for row in records if row["mask"] == "selected"), None)
    score = 1.0 - min(max(relative_scatter, 0.0), 1.0)
    if selected_snr is not None and median_snr > 0:
        score *= max(0.0, min(float(selected_snr) / median_snr, 1.25)) / 1.25
    return {
        "status": "complete",
        "score": float(np.clip(score, 0.0, 1.0)),
        "median_snr": median_snr,
        "relative_snr_scatter": relative_scatter,
        "apertures": records,
    }


def bundle_asdict(bundle: TpfLightCurveBundle) -> dict[str, Any]:
    return asdict(bundle)
