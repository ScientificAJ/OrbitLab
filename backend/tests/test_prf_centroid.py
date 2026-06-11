"""PSF-fit difference-image centroiding: the DV-style upgrade over moments.

The cases pin the two physical scenarios the diagnostic exists to separate:
a transit on the target (offset insignificant) and a transit on a blended
neighbor (offset significant, pointing at the neighbor), plus the honest
fallback path when a fit cannot be supported.
"""

from __future__ import annotations

import numpy as np
import pytest
from orbitlab.science.bls import TransitCandidate
from orbitlab.science.prf_centroid import fit_point_source
from orbitlab.science.tpf_diagnostics import difference_image_diagnostics

PERIOD, EPOCH, DURATION, DEPTH = 3.0, 0.45, 0.12, 0.02


def _gaussian(shape, row, col, sigma, amplitude):
    rows, cols = np.indices(shape, dtype=np.float64)
    return amplitude * np.exp(-(((rows - row) ** 2 + (cols - col) ** 2) / (2.0 * sigma**2)))


def _cube(dip_on, *, shape=(11, 11), target=(5.3, 4.7), neighbor=(8.1, 2.4), seed=3):
    rng = np.random.default_rng(seed)
    time = np.linspace(0.0, 27.0, 900)
    phase = ((time - EPOCH + 0.5 * PERIOD) % PERIOD) - 0.5 * PERIOD
    in_transit = np.abs(phase) <= 0.5 * DURATION

    target_psf = _gaussian(shape, *target, sigma=1.1, amplitude=1000.0)
    neighbor_psf = _gaussian(shape, *neighbor, sigma=1.1, amplitude=400.0)
    cube = np.empty((time.size, *shape), dtype=np.float64)
    for index in range(time.size):
        t_scale = 1.0
        n_scale = 1.0
        if in_transit[index]:
            if dip_on == "target":
                t_scale = 1.0 - DEPTH
            else:
                n_scale = 1.0 - DEPTH * 2.5  # same blended depth from a fainter star
        cube[index] = (
            target_psf * t_scale + neighbor_psf * n_scale + 10.0 + rng.normal(0.0, 1.0, shape)
        )
    candidate = TransitCandidate(PERIOD, EPOCH, DURATION, DEPTH, 10.0, 25.0)
    return time, cube, candidate, target, neighbor


def test_psf_fit_recovers_position_and_uncertainty():
    image = _gaussian((11, 11), 5.3, 4.7, sigma=1.1, amplitude=500.0) + 20.0
    image += np.random.default_rng(1).normal(0.0, 0.5, image.shape)

    fit = fit_point_source(image)

    assert fit is not None and fit.converged
    assert fit.row == pytest.approx(5.3, abs=0.05)
    assert fit.col == pytest.approx(4.7, abs=0.05)
    assert 0.0 < fit.row_uncertainty < 0.2
    assert 0.0 < fit.col_uncertainty < 0.2
    assert fit.background == pytest.approx(20.0, abs=2.0)


def test_on_target_transit_yields_insignificant_psf_offset():
    time, cube, candidate, target, _ = _cube("target")

    payload = difference_image_diagnostics(time=time, pixel_flux=cube, candidate=candidate)

    assert payload["status"] == "complete"
    assert payload["centroid_method"] == "psf_fit"
    diff_fit = payload["psf_fit_diff"]
    assert diff_fit["row"] == pytest.approx(target[0], abs=0.2)
    assert diff_fit["col"] == pytest.approx(target[1], abs=0.2)
    assert payload["psf_offset_significance"] < 3.0
    # The gate-facing keys carry the PSF numbers when the fit succeeds.
    assert payload["centroid_shift_pixels"] == payload["psf_offset_pixels"]


def test_neighbor_transit_is_localized_onto_the_neighbor():
    time, cube, candidate, target, neighbor = _cube("neighbor")

    payload = difference_image_diagnostics(time=time, pixel_flux=cube, candidate=candidate)

    assert payload["status"] == "complete"
    assert payload["centroid_method"] == "psf_fit"
    diff_fit = payload["psf_fit_diff"]
    assert diff_fit["row"] == pytest.approx(neighbor[0], abs=0.3)
    assert diff_fit["col"] == pytest.approx(neighbor[1], abs=0.3)
    true_offset = np.hypot(neighbor[0] - target[0], neighbor[1] - target[1])
    assert payload["psf_offset_pixels"] == pytest.approx(true_offset, abs=0.4)
    assert payload["psf_offset_significance"] > 3.0
    # Moments smear the difference centroid toward the bright target: the
    # fitted offset must exceed the moment offset, which is why the PSF fit
    # is the primary method.
    assert payload["psf_offset_pixels"] > payload["moment_centroid_shift_pixels"]


def test_degenerate_inputs_fall_back_to_moments_with_full_payload():
    rng = np.random.default_rng(7)
    time = np.linspace(0.0, 27.0, 300)
    flat = np.full((time.size, 3, 3), 50.0) + rng.normal(0.0, 0.1, (time.size, 3, 3))
    candidate = TransitCandidate(PERIOD, EPOCH, DURATION, DEPTH, 10.0, 25.0)

    payload = difference_image_diagnostics(time=time, pixel_flux=flat, candidate=candidate)

    assert payload["status"] == "complete"
    assert payload["centroid_method"] == "image_moment_fallback"
    # Pre-existing contract keys must all survive the fallback path.
    for key in (
        "centroid_shift_pixels",
        "centroid_uncertainty_pixels",
        "centroid_significance",
        "difference_centroid_row",
        "oot_centroid_row",
        "in_transit_cadences",
        "out_of_transit_cadences",
    ):
        assert key in payload
    assert fit_point_source(np.full((3, 3), np.nan)) is None
    assert fit_point_source(np.ones((2, 2))) is None
