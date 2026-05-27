from pathlib import Path

import numpy as np
import pytest
from orbitlab.config import Settings
from orbitlab.exceptions import ModelArtifactError
from orbitlab.ml.artifact_registry import K2_EXOMAC_MODEL_ID, register_artifact
from orbitlab.ml.astronet_adapter import GLOBAL_BINS, LOCAL_BINS, AstroNetTensors
from orbitlab.ml.checksum import sha256_path
from orbitlab.ml.exomac_service import ExoMACService, ExoMACVerdict, build_exomac_features
from orbitlab.ml.service import AstroNetService
from orbitlab.science import pipeline
from orbitlab.science.bls import BlsResult, TransitCandidate


class TinyExoMACModel:
    def predict(self, frame):
        return np.asarray([0])

    def predict_proba(self, frame):
        return np.asarray([[0.7, 0.2, 0.1]], dtype=float)


class TinyK2Service:
    def predict(self, features):
        assert features["koi_duration"] == pytest.approx(3.0)
        return ExoMACVerdict(
            probability=0.7,
            threshold=0.5,
            label="candidate",
            model_version="test",
            model_source="test",
            input_tensor_checksum="feature-checksum",
            preprocessing_compatible=True,
            citation="test citation",
            class_probabilities={"CANDIDATE": 0.7, "CONFIRMED": 0.2, "FALSE POSITIVE": 0.1},
        )


def test_model_artifact_checksum_validation(tmp_path: Path):
    artifact = tmp_path / "model.onnx"
    artifact.write_bytes(b"real checkpoint bytes for checksum contract")
    checksum = sha256_path(artifact)
    service = AstroNetService(
        Settings(
            astronet_model_path=artifact,
            astronet_model_sha256=checksum,
            astronet_model_source="test AstroNet artifact",
            astronet_model_version="test-v1",
        )
    )

    info = service.validate_artifact()

    assert info.status == "ready"
    assert info.checksum == checksum
    assert info.schema_version == "orbitlab.astronet.v1"


def test_model_artifact_refuses_missing_checksum(tmp_path: Path):
    artifact = tmp_path / "model.onnx"
    artifact.write_bytes(b"checkpoint")
    service = AstroNetService(Settings(astronet_model_path=artifact, astronet_model_sha256=None))

    with pytest.raises(ModelArtifactError):
        service.validate_artifact()


def test_numpy_astronet_runtime_predicts_without_tensorflow(tmp_path: Path):
    artifact = tmp_path / "kepler.npz"
    np.savez(
        artifact,
        global_kernel=np.zeros((GLOBAL_BINS,), dtype=np.float32),
        local_kernel=np.zeros((LOCAL_BINS,), dtype=np.float32),
        metadata_kernel=np.zeros((7,), dtype=np.float32),
        bias=np.asarray([0.0], dtype=np.float32),
    )
    checksum = sha256_path(artifact)
    service = AstroNetService(
        Settings(
            astronet_model_path=artifact,
            astronet_model_sha256=checksum,
            astronet_model_source="converted Kepler AstroNet",
            astronet_model_version="npz-test",
        )
    )
    tensors = AstroNetTensors(
        global_view=np.zeros((1, GLOBAL_BINS, 1), dtype=np.float32),
        local_view=np.zeros((1, LOCAL_BINS, 1), dtype=np.float32),
        metadata=np.zeros((1, 7), dtype=np.float32),
        checksum="tensor-checksum",
    )

    verdict = service.predict(tensors)

    assert verdict.probability == pytest.approx(0.5)
    assert verdict.preprocessing_compatible is True


def test_savedmodel_runtime_requires_conversion(tmp_path: Path):
    artifact = tmp_path / "saved_model"
    artifact.mkdir()
    (artifact / "saved_model.pb").write_bytes(b"tensorflow graph")
    service = AstroNetService(
        Settings(
            astronet_model_path=artifact,
            astronet_model_sha256=sha256_path(artifact),
        )
    )

    with pytest.raises(ModelArtifactError, match="TensorFlow checkpoint artifact"):
        service.load()


def test_exomac_feature_builder_uses_catalog_units():
    candidate = TransitCandidate(period=10.0, epoch=1.0, duration=0.125, depth=0.001, power=9.0, signal_to_noise=12.0)

    features = build_exomac_features(
        candidate,
        stellar_radius_solar=1.0,
        stellar_teff=5778.0,
        stellar_logg=4.44,
        planet_radius_earth=3.45,
        semi_major_axis_au=0.09,
    )

    assert features["koi_duration"] == pytest.approx(3.0)
    assert features["duty_cycle"] == pytest.approx(0.0125)
    assert features["log_koi_period"] == pytest.approx(1.0)
    assert np.isfinite(features["log_koi_depth"])


def test_exomac_service_loads_registered_joblib_bundle(tmp_path: Path):
    import joblib

    bundle = tmp_path / "exomac"
    bundle.mkdir()
    joblib.dump(TinyExoMACModel(), bundle / "exoplanet_best_model.joblib")
    (bundle / "exoplanet_feature_columns.json").write_text(
        '["koi_depth","koi_duration","koi_impact","koi_period","koi_prad","koi_slogg","koi_sma",'
        '"koi_smet","koi_snr","koi_srad","koi_steff","duty_cycle","log_koi_period",'
        '"log_koi_depth","log_koi_snr","teq_proxy"]'
    )
    (bundle / "exoplanet_class_labels.json").write_text('["CANDIDATE","CONFIRMED","FALSE POSITIVE"]')
    (bundle / "exoplanet_metadata.json").write_text('{"best_model_name":"RandomForest","n_features":16}')
    registry_path = tmp_path / "models.json"
    register_artifact(
        model_id=K2_EXOMAC_MODEL_ID,
        mission="K2",
        path=bundle,
        source="test ExoMAC artifact",
        version="test",
        registry_path=registry_path,
    )
    service = ExoMACService(Settings(model_registry_path=registry_path))
    features = build_exomac_features(
        TransitCandidate(period=10.0, epoch=1.0, duration=0.125, depth=0.001, power=9.0, signal_to_noise=12.0)
    )

    verdict = service.predict(features)

    assert verdict.label == "candidate"
    assert verdict.probability == pytest.approx(0.7)
    assert verdict.class_probabilities["FALSE POSITIVE"] == pytest.approx(0.1)


def test_k2_pipeline_uses_exomac_service(monkeypatch: pytest.MonkeyPatch):
    candidate = TransitCandidate(period=10.0, epoch=1.0, duration=0.125, depth=0.001, power=9.0, signal_to_noise=12.0)

    def fake_run_bls(clean_time, clean_flux):
        return BlsResult(
            candidate=candidate,
            periodogram={
                "period": np.asarray([10.0], dtype=np.float32),
                "power": np.asarray([9.0], dtype=np.float32),
                "duration": np.asarray([0.125], dtype=np.float32),
            },
            search_time=np.asarray(clean_time, dtype=np.float32),
            search_flux=np.asarray(clean_flux, dtype=np.float32),
            clean_time=np.asarray(clean_time, dtype=np.float32),
            clean_flux=np.asarray(clean_flux, dtype=np.float32),
            metadata={
                "min_period_days": 0.5,
                "max_period_days": 10.0,
                "baseline_days": 20.0,
                "cadence_days": 0.1,
                "period_grid_source": "test",
            },
        )

    monkeypatch.setattr(pipeline, "run_bls", fake_run_bls)

    monkeypatch.setattr(
        pipeline,
        "find_multi_planet_candidates",
        lambda clean_time, clean_flux, max_candidates, initial_candidate, min_period, max_period, **kwargs: [
            initial_candidate
        ],
    )

    result = pipeline.analyze_light_curve_arrays(
        target_id="EPIC-test",
        mission="K2",
        time=np.linspace(0, 20, 200),
        flux=1.0 + 0.001 * np.sin(np.linspace(0, 12, 200)),
        stellar_radius_solar=1.0,
        stellar_mass_solar=1.0,
        stellar_teff=5778.0,
        stellar_logg=4.44,
        stellar_luminosity_solar=1.0,
        stellar_density_solar=1.0,
        stellar_rotation_period=10.0,
        vetting_mode="fast",
        k2_service=TinyK2Service(),
    )

    assert "candidates" not in result
    assert result["tces"][0]["ml"]["label"] == "candidate"
    assert result["tces"][0]["ml"]["class_probabilities"]["CANDIDATE"] == pytest.approx(0.7)
    assert result["stellar_context"]["teff"] == pytest.approx(5778.0)
    assert result["stellar_context"]["rotation_period"] == pytest.approx(10.0)
