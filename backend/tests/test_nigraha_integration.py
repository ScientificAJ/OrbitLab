import json
from pathlib import Path

import numpy as np
from orbitlab.ml.nigraha_adapter import build_nigraha_tensors
from orbitlab.ml.nigraha_service import NigrahaNumpyModel
from orbitlab.science.bls import TransitCandidate


def transit_curve():
    rng = np.random.default_rng(123)
    time = np.linspace(0.0, 30.0, 3000, dtype=np.float32)
    period = 2.75
    epoch = 0.4
    duration = 0.12
    flux = 1.0 + rng.normal(0.0, 0.001, size=time.size).astype(np.float32)
    phase_time = np.abs(((time - epoch + 0.5 * period) % period) - 0.5 * period)
    flux[phase_time < duration / 2.0] -= 0.01
    return time, flux, TransitCandidate(period, epoch, duration, 0.01, 24.0, 10.0)


def test_nigraha_adapter_shapes_and_imputation():
    time, flux, candidate = transit_curve()
    tensors = build_nigraha_tensors(time, flux, candidate)

    assert tensors.global_view.shape == (1, 201, 1)
    assert tensors.local_view.shape == (1, 81, 1)
    assert tensors.odd_even_view.shape == (1, 162, 1)
    assert tensors.scalar_features["Depth"].shape == (1, 1)
    assert "Teff" in tensors.imputed_features
    assert np.isfinite(tensors.global_view).all()
    assert np.isfinite(tensors.local_view).all()
    assert np.isfinite(tensors.odd_even_view).all()


def test_nigraha_numpy_model_forward_pass():
    path = ".orbitlab/models/nigraha/global_nodropout/binary/models_1.hdf5"
    time, flux, candidate = transit_curve()
    tensors = build_nigraha_tensors(time, flux, candidate)
    model = NigrahaNumpyModel(path)

    probability = model.predict(tensors.as_inputs())

    assert 0.0 <= probability <= 1.0


def test_nigraha_numpy_matches_original_keras_golden_fixture():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "nigraha_golden_model1.json").read_text())
    path = ".orbitlab/models/nigraha/global_nodropout/binary/models_1.hdf5"
    time, flux, candidate = transit_curve()
    tensors = build_nigraha_tensors(time, flux, candidate)
    model = NigrahaNumpyModel(path)

    probability = model.predict(tensors.as_inputs())

    assert tensors.checksum == fixture["input_tensor_checksum"]
    np.testing.assert_allclose(
        [probability],
        [fixture["probability"]],
        atol=fixture["absolute_tolerance"],
        rtol=0.0,
    )
