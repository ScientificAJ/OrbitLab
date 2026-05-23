from __future__ import annotations

import json
import sys
import types

import numpy as np
from orbitlab.ml.calibration import apply_probability_calibration
from orbitlab.science.bls import TransitCandidate
from orbitlab.science.injection_recovery import inject_box_transit, run_injection_recovery
from orbitlab.science.tls_refinement import refine_with_tls


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
