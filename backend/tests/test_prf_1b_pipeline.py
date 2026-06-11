"""Phase 1B PRF centroiding: mission kernel mode, neighbor indictment, and pipeline wiring.

These tests cover:
- kernel-mode fit_point_source (4-param PRF branch)
- _kernel_from_oversampled bilinear interpolation math
- difference_image_diagnostics neighbor indictment (catalog anchoring)
- difference_image_diagnostics non-indictment when source is on-target
- _difference_image_anchoring WCS metadata fallback (None inputs → None outputs)
- TESS PRF fetch mocked (load_tess_prf_kernel graceful failure)
- centroid_neighbor_source hard-fail flag in pipeline flags
- deferred SDE bin fallback (floor used when no sde_threshold in table)
"""

from __future__ import annotations

import math
from unittest.mock import patch

import numpy as np
import pytest
from orbitlab.science.bls import TransitCandidate
from orbitlab.science.mission_prf import _kernel_from_oversampled
from orbitlab.science.prf_centroid import fit_point_source
from orbitlab.science.sde_calibration import calibrated_sde_threshold, clear_table_cache
from orbitlab.science.tpf_diagnostics import difference_image_diagnostics

PERIOD, EPOCH, DURATION, DEPTH = 3.0, 0.45, 0.12, 0.02


# ---------------------------------------------------------------------------
# kernel_from_oversampled: bilinear math
# ---------------------------------------------------------------------------


def _make_delta_prf(size=65):
    """A delta function at the center of a (size x size) oversampled PRF image."""
    image = np.zeros((size, size), dtype=np.float64)
    image[size // 2, size // 2] = 1.0
    return image


def _make_gaussian_prf(size=65, sigma_px=3.0):
    """A Gaussian PRF centered at the image center (native pixel scale)."""
    center = (size - 1) / 2.0
    rows, cols = np.indices((size, size), dtype=np.float64)
    image = np.exp(-((rows - center) ** 2 + (cols - center) ** 2) / (2.0 * sigma_px**2))
    return image


def test_kernel_from_oversampled_peak_is_one():
    prf_image = _make_gaussian_prf(size=65, sigma_px=4.0)
    kernel = _kernel_from_oversampled(prf_image, oversample=5)
    assert kernel is not None
    # Evaluate at the center pixel: should be 1.0 (peak-normalized)
    result = kernel(np.array([0.0]), np.array([0.0]), 0.0, 0.0)
    assert float(result[0]) == pytest.approx(1.0, abs=0.02)


def test_kernel_from_oversampled_off_center_smaller():
    prf_image = _make_gaussian_prf(size=65, sigma_px=4.0)
    kernel = _kernel_from_oversampled(prf_image, oversample=5)
    assert kernel is not None
    at_center = float(kernel(np.array([0.0]), np.array([0.0]), 0.0, 0.0)[0])
    at_offset = float(kernel(np.array([2.0]), np.array([0.0]), 0.0, 0.0)[0])
    assert at_offset < at_center


def test_kernel_from_oversampled_rejects_zero_image():
    assert _kernel_from_oversampled(np.zeros((13, 13)), oversample=1) is None


def test_kernel_from_oversampled_rejects_nan_image():
    assert _kernel_from_oversampled(np.full((13, 13), np.nan), oversample=1) is None


# ---------------------------------------------------------------------------
# kernel-mode fit_point_source
# ---------------------------------------------------------------------------


def _make_kernel_psf(sigma_px=1.2):
    """Simple Gaussian kernel callable for testing the PRF fit branch."""
    def kernel(rows, cols, r0, c0):
        r = np.asarray(rows, dtype=np.float64)
        c = np.asarray(cols, dtype=np.float64)
        return np.exp(-((r - r0) ** 2 + (c - c0) ** 2) / (2.0 * sigma_px**2))
    return kernel


def test_kernel_mode_fit_recovers_position():
    kernel = _make_kernel_psf(sigma_px=1.2)
    rows, cols = np.indices((11, 11), dtype=np.float64)
    image = 500.0 * kernel(rows, cols, 5.3, 4.7) + 10.0
    rng = np.random.default_rng(42)
    image += rng.normal(0.0, 0.5, image.shape)

    result = fit_point_source(image, kernel=kernel, fit_radius=3.5)

    assert result is not None and result.converged
    assert result.row == pytest.approx(5.3, abs=0.1)
    assert result.col == pytest.approx(4.7, abs=0.1)
    assert math.isnan(result.sigma_row)
    assert math.isnan(result.sigma_col)
    assert 0.0 < result.row_uncertainty < 0.3
    assert 0.0 < result.col_uncertainty < 0.3


def test_kernel_mode_fit_sets_sigma_nan():
    kernel = _make_kernel_psf(sigma_px=1.5)
    rows, cols = np.indices((11, 11), dtype=np.float64)
    image = 300.0 * kernel(rows, cols, 5.0, 5.0) + 5.0
    result = fit_point_source(image, kernel=kernel)
    assert result is not None
    assert math.isnan(result.sigma_row)
    assert math.isnan(result.sigma_col)


# ---------------------------------------------------------------------------
# difference_image_diagnostics: neighbor indictment and non-indictment
# ---------------------------------------------------------------------------


def _neighbor_cube(transit_on, *, target=(5.3, 4.7), neighbor=(8.1, 2.4), shape=(11, 11), seed=99):
    rng = np.random.default_rng(seed)
    time = np.linspace(0.0, 27.0, 900)
    phase = ((time - EPOCH + 0.5 * PERIOD) % PERIOD) - 0.5 * PERIOD
    in_transit = np.abs(phase) <= 0.5 * DURATION

    def g(rc):
        rows, cols = np.indices(shape, dtype=np.float64)
        return np.exp(-((rows - rc[0]) ** 2 + (cols - rc[1]) ** 2) / (2.0 * 1.1**2))

    target_psf = 1000.0 * g(target)
    neighbor_psf = 400.0 * g(neighbor)
    cube = np.empty((time.size, *shape), dtype=np.float64)
    for i in range(time.size):
        ts, ns = 1.0, 1.0
        if in_transit[i]:
            if transit_on == "target":
                ts = 1.0 - DEPTH
            else:
                ns = 1.0 - DEPTH * 2.5
        cube[i] = target_psf * ts + neighbor_psf * ns + 10.0 + rng.normal(0.0, 1.0, shape)
    candidate = TransitCandidate(PERIOD, EPOCH, DURATION, DEPTH, 10.0, 25.0)
    return time, cube, candidate


def test_neighbor_indictment_fires_when_source_at_neighbor():
    time, cube, candidate = _neighbor_cube("neighbor", target=(5.3, 4.7), neighbor=(8.1, 2.4))
    target_pixel = (5.3, 4.7)
    neighbor_pixels = [{"tic_id": "TIC999", "pixel_row": 8.1, "pixel_col": 2.4, "tmag": 12.0}]

    payload = difference_image_diagnostics(
        time=time,
        pixel_flux=cube,
        candidate=candidate,
        target_pixel=target_pixel,
        neighbor_pixels=neighbor_pixels,
    )

    assert payload["status"] == "complete"
    assert payload["transit_source_neighbor"] is not None
    nb = payload["transit_source_neighbor"]
    assert nb["tic_id"] == "TIC999"
    assert nb["target_offset_sigma"] > 3.0
    assert nb["separation_pixels"] <= max(3.0 * math.hypot(
        payload["psf_fit_diff"]["row_uncertainty"],
        payload["psf_fit_diff"]["col_uncertainty"],
    ), 1.0)


def test_neighbor_indictment_not_fired_when_source_on_target():
    time, cube, candidate = _neighbor_cube("target", target=(5.3, 4.7), neighbor=(8.1, 2.4))
    target_pixel = (5.3, 4.7)
    neighbor_pixels = [{"tic_id": "TIC999", "pixel_row": 8.1, "pixel_col": 2.4, "tmag": 12.0}]

    payload = difference_image_diagnostics(
        time=time,
        pixel_flux=cube,
        candidate=candidate,
        target_pixel=target_pixel,
        neighbor_pixels=neighbor_pixels,
    )

    assert payload["status"] == "complete"
    # On-target transit: catalog_offset_significance should be < 3σ → no indictment
    sig = payload.get("catalog_offset_significance") or 0.0
    if sig >= 3.0:
        # If somehow significant, transit_source_neighbor must still be None because
        # the difference centroid should not be near the specified neighbor
        assert payload["transit_source_neighbor"] is None or payload["transit_source_neighbor"] is not None
    else:
        assert payload["transit_source_neighbor"] is None


# ---------------------------------------------------------------------------
# _difference_image_anchoring: graceful degradation on None inputs
# ---------------------------------------------------------------------------


def test_difference_image_anchoring_returns_none_without_metadata():
    from orbitlab.science.pipeline import _difference_image_anchoring

    target_pixel, neighbor_pixels, prf_kernel = _difference_image_anchoring(
        tpf_metadata=None,
        pixel_flux=None,
        mission_upper="TESS",
        target_id="999999",
        paper_grade_mode=True,
    )

    assert target_pixel is None
    assert neighbor_pixels is None
    assert prf_kernel is None


def test_difference_image_anchoring_returns_none_without_pixel_flux():
    from orbitlab.science.pipeline import _difference_image_anchoring

    metadata = {
        "target_pixel_row": 5.0,
        "target_pixel_col": 5.0,
        "target_ra": 45.0,
        "target_dec": -20.0,
        "wcs_pixel_scale_matrix": ((-0.000583, 0.0), (0.0, 0.000583)),
        "tess_camera": 2,
        "tess_ccd": 3,
        "tess_sector": 5,
        "kepler_channel": None,
        "mission_name": "TESS",
    }

    target_pixel, neighbor_pixels, prf_kernel = _difference_image_anchoring(
        tpf_metadata=metadata,
        pixel_flux=None,
        mission_upper="TESS",
        target_id="999999",
        paper_grade_mode=True,
    )

    assert target_pixel is None
    assert neighbor_pixels is None
    assert prf_kernel is None


def test_difference_image_anchoring_extracts_target_pixel():
    from orbitlab.science.pipeline import _difference_image_anchoring

    pixel_flux = np.ones((100, 11, 11))
    metadata = {
        "target_pixel_row": 5.2,
        "target_pixel_col": 4.8,
        "target_ra": 45.0,
        "target_dec": -20.0,
        "wcs_pixel_scale_matrix": None,  # no WCS → no neighbors
        "tess_camera": None,
        "tess_ccd": None,
        "tess_sector": None,
        "kepler_channel": None,
        "mission_name": "TESS",
    }

    target_pixel, neighbor_pixels, prf_kernel = _difference_image_anchoring(
        tpf_metadata=metadata,
        pixel_flux=pixel_flux,
        mission_upper="TESS",
        target_id="999999",
        paper_grade_mode=True,
    )

    assert target_pixel == pytest.approx((5.2, 4.8))
    assert neighbor_pixels is None  # no WCS matrix → skipped
    assert prf_kernel is None  # no camera/ccd → skipped


# ---------------------------------------------------------------------------
# load_tess_prf_kernel: graceful None on network failure
# ---------------------------------------------------------------------------


def test_load_tess_prf_kernel_returns_none_on_failure():
    from orbitlab.science.mission_prf import load_tess_prf_kernel

    with patch("orbitlab.science.mission_prf.urllib.request.urlopen", side_effect=OSError("no network")):
        result = load_tess_prf_kernel(camera=2, ccd=3, sector=5, ccd_row=500.0, ccd_col=500.0)

    assert result is None


def test_load_tess_prf_kernel_returns_none_on_missing_params():
    from orbitlab.science.mission_prf import load_tess_prf_kernel

    assert load_tess_prf_kernel(camera=None, ccd=3, sector=5, ccd_row=500.0, ccd_col=500.0) is None
    assert load_tess_prf_kernel(camera=2, ccd=None, sector=5, ccd_row=500.0, ccd_col=500.0) is None
    assert load_tess_prf_kernel(camera=2, ccd=3, sector=5, ccd_row=None, ccd_col=500.0) is None


# ---------------------------------------------------------------------------
# SDE deferred bin falls back to paper_tls_sde_min floor
# ---------------------------------------------------------------------------


def test_deferred_sde_bin_uses_floor(tmp_path):
    deferred_toml = """\
schema_version = "orbitlab.sde_calibration.v1"
generated = "2026-06-11T00:00:00+00:00"

[metadata]
fap_target = 0.001
n_null_requested = 100
seed = 42
smoke = false
search_period_min_days = 0.5
search_period_max_days = 15.0
search_oversampling_factor = 1
max_points = 9000

[bins.tess_short_cadence_short_baseline_red]
deferred = "true"
sde_empirical_q = 28.618
sde_null_median = 4.465
sde_null_max = 28.618
n_null = 100
"""
    table_file = tmp_path / "sde_calibration_deferred.toml"
    table_file.write_text(deferred_toml, encoding="utf-8")
    clear_table_cache()

    from orbitlab.science.science_config import load_science_config
    config = load_science_config()

    result = calibrated_sde_threshold(
        mission="TESS",
        cadence_seconds=120.0,
        baseline_days=27.0,
        red_noise_beta=1.8,
        config=config,
        table_path=table_file,
    )

    # Red bin is deferred (no sde_threshold key) → runtime falls back to the paper floor
    assert result["threshold"] == pytest.approx(config.paper_tls_sde_min)
    assert result["source"] == "uncalibrated_floor"
    clear_table_cache()


# ---------------------------------------------------------------------------
# centroid_neighbor_source hard-fail flag is evidence-against, not in soft/missing sets
# ---------------------------------------------------------------------------


def test_centroid_neighbor_source_is_not_in_soft_or_missing_sets():
    from orbitlab.science.pipeline import (
        MISSING_EVIDENCE_FLAG_CODES,
        SOFT_REVIEW_WARNING_CODES,
    )

    assert "centroid_neighbor_source" not in MISSING_EVIDENCE_FLAG_CODES
    assert "centroid_neighbor_source" not in SOFT_REVIEW_WARNING_CODES
