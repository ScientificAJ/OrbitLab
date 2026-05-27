from __future__ import annotations

import json
import sys
import types

import numpy as np
import pytest
from orbitlab.ml.calibration import apply_probability_calibration
from orbitlab.science.bls import TransitCandidate
from orbitlab.science.injection_recovery import inject_box_transit, run_injection_recovery
from orbitlab.science.tls_refinement import refine_with_tls, search_with_tls


def test_probability_calibration_uses_local_isotonic_bundle(tmp_path, monkeypatch):
    calibration_dir = tmp_path / "calibration"
    calibration_dir.mkdir()
    (calibration_dir / "kepler-probability-calibration.json").write_text(
        json.dumps(
            {
                "method": "isotonic_bins",
                "source": "unit-test-calibration",
                "x": [0.0, 0.5, 1.0],
                "y": [0.0, 0.25, 1.0],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("orbitlab.ml.calibration.CALIBRATION_DIR", calibration_dir)

    payload = apply_probability_calibration(0.5, "Kepler")

    assert payload["raw_ml_probability"] == 0.5
    assert payload["calibrated_ml_probability"] == 0.25
    assert payload["calibration_source"] == "unit-test-calibration"
    assert payload["calibration_method"] == "isotonic_bins"
    assert payload["calibration_checksum"]


def test_injection_recovery_reports_recovered_known_signal():
    time = np.linspace(0, 18, 1800, dtype=np.float32)
    flux = 1.0 + 0.0001 * np.sin(time).astype(np.float32)
    injected = inject_box_transit(time, flux, period_days=3.0, depth_ppm=5000, duration_hours=3.0)
    assert float(np.nanmin(injected)) < float(np.nanmedian(flux))

    result = run_injection_recovery(
        time,
        flux,
        period_days=(3.0,),
        depth_ppm=(5000.0,),
        duration_hours=(3.0,),
        tolerance_fraction=0.2,
    )

    assert result["status"] == "complete"
    assert result["total_cases"] == 1
    assert result["recovered_cases"] == 1
    assert result["completeness"] == 1.0


def test_tls_refinement_reports_unavailable_when_dependency_missing(monkeypatch):
    real_module = sys.modules.pop("transitleastsquares", None)
    monkeypatch.setitem(sys.modules, "transitleastsquares", None)
    candidate = TransitCandidate(period=2.0, epoch=0.1, duration=0.1, depth=0.001, power=1.0, signal_to_noise=8.0)

    try:
        result = refine_with_tls(np.linspace(0, 10, 100), 1.0 + 0.001 * np.sin(np.linspace(0, 4, 100)), candidate)
    finally:
        if real_module is not None:
            sys.modules["transitleastsquares"] = real_module
        else:
            sys.modules.pop("transitleastsquares", None)

    assert result["status"] == "unavailable"
    assert "transitleastsquares" in result["detail"]


def test_tls_refinement_maps_basic_result(monkeypatch):
    class FakeResults:
        period = 2.002
        duration = 0.12
        T0 = 0.11
        depth = 0.0012
        snr = 9.5

    class FakeTls:
        def __init__(self, time, flux):
            self.time = time
            self.flux = flux

        def power(self, *, period_min, period_max):
            assert period_min < 2.0 < period_max
            return FakeResults()

    module = types.SimpleNamespace(transitleastsquares=FakeTls)
    monkeypatch.setitem(sys.modules, "transitleastsquares", module)
    candidate = TransitCandidate(period=2.0, epoch=0.1, duration=0.1, depth=0.001, power=1.0, signal_to_noise=8.0)

    result = refine_with_tls(np.linspace(0, 10, 100), 1.0 + 0.001 * np.sin(np.linspace(0, 4, 100)), candidate)

    assert result["status"] == "complete"
    assert result["period_days"] == 2.002
    assert result["period_agreement_fraction"] < 0.01
    assert result["model_shape_score"] == "planet_like"


def test_tls_full_search_maps_paper_grade_statistics(monkeypatch):
    class FakeResults:
        period = 2.002
        duration = 0.12
        T0 = 0.11
        depth = 0.0012
        snr = 9.5
        SDE = 8.1
        SDE_raw = 8.4
        FAP = 0.001
        transit_count = 5
        distinct_transit_count = 5
        period_uncertainty = 0.002
        periods = np.linspace(1.0, 3.0, 12)

    class FakeTls:
        def __init__(self, time, flux):
            self.time = time
            self.flux = flux

        def power(self, **kwargs):
            assert kwargs["n_transits_min"] == 2
            assert kwargs["transit_depth_min"] == pytest.approx(10e-6)
            assert kwargs["oversampling_factor"] == 3
            assert kwargs["duration_grid_step"] == pytest.approx(1.1)
            return FakeResults()

    module = types.SimpleNamespace(transitleastsquares=FakeTls)
    monkeypatch.setitem(sys.modules, "transitleastsquares", module)

    result = search_with_tls(
        np.linspace(0, 10, 100),
        1.0 + 0.001 * np.sin(np.linspace(0, 4, 100)),
        min_period=0.1,
        max_period=5.0,
    )

    assert result["status"] == "complete"
    assert result["sde"] == 8.1
    assert result["distinct_transit_count"] == 5


def test_tpf_diagnostics_compute_difference_image_and_aperture_stability():
    from orbitlab.science.tpf_diagnostics import aperture_stability_diagnostics, difference_image_diagnostics

    candidate = TransitCandidate(period=2.0, epoch=0.0, duration=0.2, depth=0.01, power=12.0, signal_to_noise=9.0)
    time = np.linspace(0, 10, 500, dtype=np.float32)
    cube = np.ones((time.size, 3, 3), dtype=np.float32) * 1000.0
    cube[:, 1, 1] += 500.0
    phase = ((time - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period
    in_transit = np.abs(phase) <= 0.5 * candidate.duration
    cube[in_transit, 1, 1] -= 80.0
    cube += np.random.default_rng(7).normal(0, 2.0, size=cube.shape).astype(np.float32)

    difference = difference_image_diagnostics(
        time=time,
        pixel_flux=cube,
        candidate=candidate,
        pixel_scale_arcsec=21.0,
    )
    stability = aperture_stability_diagnostics(
        time=time,
        pixel_flux=cube,
        candidate=candidate,
        selected_mask=np.array([[False, False, False], [False, True, False], [False, False, False]]),
        percentiles=(70, 80, 90),
    )

    assert difference["status"] == "complete"
    assert difference["peak_pixel"]["row"] == 1
    assert difference["peak_pixel"]["column"] == 1
    assert difference["peak_pixel"]["snr"] > 5
    assert stability["status"] == "complete"
    assert stability["score"] >= 0
    assert any(row["mask"] == "selected" for row in stability["apertures"])


def test_pipeline_uses_tpf_pixel_diagnostics(monkeypatch):
    candidate = TransitCandidate(period=2.0, epoch=0.0, duration=0.2, depth=0.01, power=12.0, signal_to_noise=9.0)
    time = np.linspace(0, 10, 500, dtype=np.float32)
    flux = (1.0 + 0.0002 * np.sin(time * 3.1) + 0.0001 * np.cos(time * 7.3)).astype(np.float32)
    phase = ((time - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period
    flux[np.abs(phase) <= 0.5 * candidate.duration] -= 0.01
    rng = np.random.default_rng(11)
    cube = np.ones((time.size, 3, 3), dtype=np.float32) * 1000.0
    cube += rng.normal(0, 2.0, size=cube.shape).astype(np.float32)
    cube[:, 1, 1] += 500.0
    cube[np.abs(phase) <= 0.5 * candidate.duration, 1, 1] -= 80.0

    class _BlsResult:
        periodogram = {
            "period": np.array([candidate.period], dtype=np.float32),
            "power": np.array([candidate.power], dtype=np.float32),
            "duration": np.array([candidate.duration], dtype=np.float32),
        }
        search_time = time
        search_flux = flux
        clean_time = time
        clean_flux = flux
        metadata = {"min_period_days": 0.5, "max_period_days": 10.0}

        def __init__(self):
            self.candidate = candidate

    monkeypatch.setattr("orbitlab.science.pipeline.run_bls", lambda *args, **kwargs: _BlsResult())
    monkeypatch.setattr("orbitlab.science.pipeline.find_multi_planet_candidates", lambda *args, **kwargs: [candidate])

    from orbitlab.science.pipeline import analyze_light_curve_arrays

    class Unavailable:
        def predict(self, tensors):
            raise FileNotFoundError("model missing")

    payload = analyze_light_curve_arrays(
        target_id="pixel-diagnostics",
        mission="TESS",
        time=time,
        flux=flux,
        vetting_mode="fast",
        nigraha_service=Unavailable(),
        pixel_flux=cube,
        aperture_mask=np.array([[False, False, False], [False, True, False], [False, False, False]]),
        pixel_scale_arcsec=21.0,
    )

    tce = payload["tces"][0]
    assert tce["aperture_stability"]["status"] == "complete"
    assert tce["vetting"]["difference_image"]["status"] == "complete"
    assert tce["vetting"]["difference_image"]["peak_pixel"]["row"] == 1
    assert tce["vetting"]["centroid"]["centroid_shift_arcsec"] is not None
