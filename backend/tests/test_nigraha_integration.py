import json
from pathlib import Path

import numpy as np
from orbitlab.ml.nigraha_adapter import build_nigraha_tensors
from orbitlab.ml.nigraha_service import NigrahaNumpyModel, NigrahaService
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


def _candidate(depth, period, dur, seed):
    rng = np.random.default_rng(seed)
    time = np.linspace(0.0, 27.0, 3000, dtype=np.float32)
    epoch = 0.4
    flux = 1.0 + rng.normal(0.0, 0.001, size=time.size).astype(np.float32)
    phase_time = np.abs(((time - epoch + 0.5 * period) % period) - 0.5 * period)
    flux[phase_time < dur / 2.0] -= depth
    return time, flux, TransitCandidate(period, epoch, dur, depth, dur * 24.0, 10.0)


def test_stellar_context_overrides_solar_imputation():
    """Supplying real stellar params must shrink the imputed-feature set.

    This is the wiring guarantee behind Fix 1: when Teff/R*/mass/logg flow in
    from the job/known-target/TIC path, the adapter no longer imputes them.
    """
    time, flux, candidate = _candidate(0.01, 2.75, 0.12, seed=11)
    imputed_solar = build_nigraha_tensors(time, flux, candidate).imputed_features
    imputed_real = build_nigraha_tensors(
        time,
        flux,
        candidate,
        stellar_teff=3200.0,
        stellar_radius_solar=0.4,
        stellar_mass_solar=0.42,
        stellar_logg=4.9,
    ).imputed_features

    assert "Teff" in imputed_solar and "Radius" in imputed_solar
    assert "Teff" not in imputed_real
    assert "Radius" not in imputed_real
    assert set(imputed_real).issubset(set(imputed_solar))


def test_nigraha_service_flags_saturated_score_honestly():
    """Fix 1 (honest gating): the released CNN is fed un-normalized scalars, so
    its logit saturates and the probability does not discriminate. The service
    must flag this rather than presenting the score as trustworthy ML evidence.
    """
    time, flux, candidate = _candidate(0.012, 3.10, 0.10, seed=21)
    tensors = build_nigraha_tensors(
        time,
        flux,
        candidate,
        stellar_teff=3200.0,
        stellar_radius_solar=0.4,
        stellar_mass_solar=0.42,
        stellar_logg=4.9,
    )
    verdict = NigrahaService().predict(tensors, threshold=0.4)

    assert verdict.saturated is True
    assert verdict.score_confidence == "degenerate_saturated"
    # The existing OOD/evidence-fusion logic keys off preprocessing_compatible,
    # so flipping it False routes the degenerate score into the inconclusive path.
    assert verdict.preprocessing_compatible is False
    assert verdict.mean_logit is not None and abs(verdict.mean_logit) >= 50.0
    assert verdict.score_caveat and "MNRAS 502, 2845" in verdict.score_caveat
