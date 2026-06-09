import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import orbitlab.ml.nigraha_service as nigraha_service_module
import pytest
from orbitlab.config import Settings
from orbitlab.exceptions import ModelArtifactError
from orbitlab.ml.artifact_registry import K2_EXOMAC_MODEL_ID, KEPLER_ASTRONET_MODEL_ID, register_artifact
from orbitlab.ml.astronet_adapter import GLOBAL_BINS, LOCAL_BINS, AstroNetTensors
from orbitlab.ml.checksum import sha256_path
from orbitlab.ml.exomac_service import ExoMACModelInfo, ExoMACService, ExoMACVerdict, build_exomac_features
from orbitlab.ml.nigraha_adapter import NIGRAHA_SCHEMA_VERSION, NigrahaTensors
from orbitlab.ml.nigraha_service import NigrahaModelInfo, NigrahaNumpyModel, NigrahaService
from orbitlab.ml.service import (
    AstroNetService,
    DockerTensorFlowAstroNetRuntime,
    KeplerAstroNetService,
    NumpyAstroNetRuntime,
)
from orbitlab.science import pipeline
from orbitlab.science.bls import BlsResult, TransitCandidate


class TinyExoMACModel:
    def predict(self, frame):
        return np.asarray([0])

    def predict_proba(self, frame):
        return np.asarray([[0.7, 0.2, 0.1]], dtype=float)


class StringOnlyExoMACModel:
    def predict(self, frame):
        return np.asarray(["False Positive"], dtype=object)


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


def test_model_artifact_refuses_absent_configuration():
    service = AstroNetService(Settings(astronet_model_path=None, astronet_model_sha256=None))

    with pytest.raises(ModelArtifactError, match="MODEL_PATH is required"):
        service.validate_artifact()


def test_service_loads_registered_artifact_when_config_path_is_absent(tmp_path: Path):
    artifact = tmp_path / "registered.npz"
    np.savez(
        artifact,
        global_kernel=np.zeros((GLOBAL_BINS,), dtype=np.float32),
        local_kernel=np.zeros((LOCAL_BINS,), dtype=np.float32),
        metadata_kernel=np.zeros((7,), dtype=np.float32),
        bias=np.asarray([0.0], dtype=np.float32),
    )
    registry_path = tmp_path / "models.json"
    register_artifact(
        model_id=KEPLER_ASTRONET_MODEL_ID,
        mission="Kepler",
        path=artifact,
        source="registered source",
        version="registered-v1",
        registry_path=registry_path,
    )

    service = AstroNetService(
        Settings(astronet_model_path=None, astronet_model_sha256=None, model_registry_path=registry_path),
        model_id=KEPLER_ASTRONET_MODEL_ID,
    )

    info = service.validate_artifact()

    assert info.source == "registered source"
    assert info.version == "registered-v1"


def test_model_artifact_refuses_missing_path_and_bad_checksum(tmp_path: Path):
    missing = tmp_path / "missing.onnx"
    service = AstroNetService(Settings(astronet_model_path=missing, astronet_model_sha256="deadbeef"))
    with pytest.raises(ModelArtifactError, match="does not exist"):
        service.validate_artifact()

    artifact = tmp_path / "model.onnx"
    artifact.write_bytes(b"checkpoint")
    service = AstroNetService(Settings(astronet_model_path=artifact, astronet_model_sha256="deadbeef"))
    with pytest.raises(ModelArtifactError, match="checksum mismatch"):
        service.validate_artifact()


def test_model_artifact_refuses_unsupported_suffix(tmp_path: Path):
    artifact = tmp_path / "model.txt"
    artifact.write_text("not a supported model artifact")
    service = AstroNetService(Settings(astronet_model_path=artifact, astronet_model_sha256=sha256_path(artifact)))

    with pytest.raises(ModelArtifactError, match="registered .npz, .onnx, or TensorFlow"):
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


def test_numpy_astronet_runtime_rejects_missing_arrays(tmp_path: Path):
    artifact = tmp_path / "broken.npz"
    np.savez(artifact, global_kernel=np.zeros((GLOBAL_BINS,), dtype=np.float32))

    with pytest.raises(ModelArtifactError, match="missing arrays"):
        NumpyAstroNetRuntime(artifact)


def test_astronet_predict_rejects_incompatible_tensor_schema(tmp_path: Path):
    artifact = tmp_path / "kepler.npz"
    np.savez(
        artifact,
        global_kernel=np.zeros((GLOBAL_BINS,), dtype=np.float32),
        local_kernel=np.zeros((LOCAL_BINS,), dtype=np.float32),
        metadata_kernel=np.zeros((7,), dtype=np.float32),
        bias=np.asarray([0.0], dtype=np.float32),
    )
    service = AstroNetService(
        Settings(
            astronet_model_path=artifact,
            astronet_model_sha256=sha256_path(artifact),
        )
    )
    tensors = AstroNetTensors(
        global_view=np.zeros((1, GLOBAL_BINS, 1), dtype=np.float32),
        local_view=np.zeros((1, LOCAL_BINS, 1), dtype=np.float32),
        metadata=np.zeros((1, 7), dtype=np.float32),
        checksum="tensor-checksum",
        schema_version="old-schema",
    )

    with pytest.raises(ModelArtifactError, match="schema is incompatible"):
        service.predict(tensors)


def test_astronet_loads_onnx_runtime_and_predicts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    artifact = tmp_path / "model.onnx"
    artifact.write_bytes(b"onnx bytes")

    class FakeInferenceSession:
        def __init__(self, path, providers):
            assert path == str(artifact)
            assert providers == ["CPUExecutionProvider"]

        def run(self, _outputs, input_map):
            assert "global_view" in input_map
            return [np.asarray([[1.25]], dtype=np.float32)]

    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        types.SimpleNamespace(InferenceSession=FakeInferenceSession),
    )
    service = AstroNetService(
        Settings(
            astronet_model_path=artifact,
            astronet_model_sha256=sha256_path(artifact),
            astronet_model_source="onnx-test",
            astronet_model_version="onnx-v1",
        )
    )
    tensors = AstroNetTensors(
        global_view=np.zeros((1, GLOBAL_BINS, 1), dtype=np.float32),
        local_view=np.zeros((1, LOCAL_BINS, 1), dtype=np.float32),
        metadata=np.zeros((1, 7), dtype=np.float32),
        checksum="tensor-checksum",
    )

    verdict = service.predict(tensors)

    assert verdict.probability == 1.0
    assert verdict.label == "planet-candidate"


def test_astronet_service_runtime_defensive_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    artifact = tmp_path / "model.txt"
    artifact.write_text("unsupported", encoding="utf-8")
    service = AstroNetService(Settings(astronet_model_path=artifact, astronet_model_sha256=sha256_path(artifact)))
    monkeypatch.setattr(
        service,
        "validate_artifact",
        lambda: types.SimpleNamespace(status="ready"),
    )

    with pytest.raises(ModelArtifactError, match="registered .npz or .onnx"):
        service.load()

    class FakeRuntime:
        def predict(self, tensors):
            return -0.5

    service._runtime = FakeRuntime()
    service._backend = "numpy"
    tensors = AstroNetTensors(
        global_view=np.zeros((1, GLOBAL_BINS, 1), dtype=np.float32),
        local_view=np.zeros((1, LOCAL_BINS, 1), dtype=np.float32),
        metadata=np.zeros((1, 7), dtype=np.float32),
        checksum="tensor-checksum",
    )

    verdict = service.predict(tensors)
    assert verdict.probability == 0.0
    assert verdict.label == "not-transit-like"


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


def test_tensorflow_checkpoint_runtime_requires_docker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "model.ckpt-1.index").write_text("index")
    monkeypatch.setattr("orbitlab.ml.service.shutil.which", lambda _: None)

    with pytest.raises(ModelArtifactError, match="Docker is required"):
        DockerTensorFlowAstroNetRuntime(checkpoint)


def test_tensorflow_checkpoint_runtime_rejects_empty_checkpoint_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    monkeypatch.setattr("orbitlab.ml.service.shutil.which", lambda _: "/usr/bin/docker")

    with pytest.raises(ModelArtifactError, match="no .index file"):
        DockerTensorFlowAstroNetRuntime(checkpoint)


def test_astronet_loads_tensorflow_checkpoint_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "model.ckpt-1.index").write_text("index")
    monkeypatch.setattr("orbitlab.ml.service.shutil.which", lambda _: "/usr/bin/docker")
    service = AstroNetService(
        Settings(
            astronet_model_path=checkpoint,
            astronet_model_sha256=sha256_path(checkpoint),
        )
    )

    info = service.load()

    assert info.status == "ready"
    assert service._backend == "tensorflow-docker"


def test_tensorflow_checkpoint_runtime_reports_missing_helper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "model.ckpt-1.index").write_text("index")
    monkeypatch.setattr("orbitlab.ml.service.shutil.which", lambda _: "/usr/bin/docker")
    runtime = DockerTensorFlowAstroNetRuntime(checkpoint)
    tensors = AstroNetTensors(
        global_view=np.zeros((1, GLOBAL_BINS, 1), dtype=np.float32),
        local_view=np.zeros((1, LOCAL_BINS, 1), dtype=np.float32),
        metadata=np.zeros((1, 7), dtype=np.float32),
        checksum="tensor-checksum",
    )

    with pytest.raises(ModelArtifactError, match="inside the OrbitLab workspace"):
        runtime.predict(tensors)


def test_tensorflow_checkpoint_runtime_reports_missing_helper_inside_workspace(monkeypatch: pytest.MonkeyPatch):
    repo_root = Path(__file__).resolve().parents[2]
    checkpoint = repo_root / ".pytest-cache" / "tf-checkpoint-missing-helper"
    checkpoint.mkdir(parents=True, exist_ok=True)
    (checkpoint / "model.ckpt-1.index").write_text("index")
    monkeypatch.setattr("orbitlab.ml.service.shutil.which", lambda _: "/usr/bin/docker")
    runtime = DockerTensorFlowAstroNetRuntime(checkpoint)
    tensors = AstroNetTensors(
        global_view=np.zeros((1, GLOBAL_BINS, 1), dtype=np.float32),
        local_view=np.zeros((1, LOCAL_BINS, 1), dtype=np.float32),
        metadata=np.zeros((1, 7), dtype=np.float32),
        checksum="tensor-checksum",
    )
    real_exists = Path.exists

    def fake_exists(path):
        if path.name == "predict_kepler_astronet_tf.py":
            return False
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)

    with pytest.raises(ModelArtifactError, match="prediction helper is missing"):
        runtime.predict(tensors)


def test_tensorflow_checkpoint_runtime_reports_subprocess_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    checkpoint = repo_root / ".pytest-cache" / "tf-checkpoint-test"
    checkpoint.mkdir(parents=True, exist_ok=True)
    (checkpoint / "model.ckpt-1.index").write_text("index")
    monkeypatch.setattr("orbitlab.ml.service.shutil.which", lambda _: "/usr/bin/docker")
    runtime = DockerTensorFlowAstroNetRuntime(checkpoint)
    tensors = AstroNetTensors(
        global_view=np.zeros((1, GLOBAL_BINS, 1), dtype=np.float32),
        local_view=np.zeros((1, LOCAL_BINS, 1), dtype=np.float32),
        metadata=np.zeros((1, 7), dtype=np.float32),
        checksum="tensor-checksum",
    )

    def fail_run(*args, **kwargs):
        raise subprocess.CalledProcessError(2, args[0], stderr="docker failed")

    monkeypatch.setattr("orbitlab.ml.service.subprocess.run", fail_run)
    with pytest.raises(ModelArtifactError, match="docker failed"):
        runtime.predict(tensors)

    def timeout_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=180)

    monkeypatch.setattr("orbitlab.ml.service.subprocess.run", timeout_run)
    with pytest.raises(ModelArtifactError, match="timed out"):
        runtime.predict(tensors)


def test_tensorflow_checkpoint_runtime_reads_probability_output(monkeypatch: pytest.MonkeyPatch):
    repo_root = Path(__file__).resolve().parents[2]
    checkpoint = repo_root / ".pytest-cache" / "tf-checkpoint-success"
    checkpoint.mkdir(parents=True, exist_ok=True)
    (checkpoint / "model.ckpt-1.index").write_text("index")
    monkeypatch.setattr("orbitlab.ml.service.shutil.which", lambda _: "/usr/bin/docker")
    runtime = DockerTensorFlowAstroNetRuntime(checkpoint)
    tensors = AstroNetTensors(
        global_view=np.zeros((1, GLOBAL_BINS, 1), dtype=np.float32),
        local_view=np.zeros((1, LOCAL_BINS, 1), dtype=np.float32),
        metadata=np.zeros((1, 7), dtype=np.float32),
        checksum="tensor-checksum",
    )

    def write_output(command, **kwargs):
        # The Docker path is mounted to the temporary directory, which appears in
        # the command volume just before it.
        temp_mount = next(part for part in command if part.endswith(":/orbitlab-tmp"))
        temp_dir = Path(temp_mount.split(":", 1)[0])
        (temp_dir / "output.json").write_text('{"probability": 0.42}')

    monkeypatch.setattr("orbitlab.ml.service.subprocess.run", write_output)

    assert runtime.predict(tensors) == pytest.approx(0.42)


def test_kepler_astronet_service_uses_registered_model_id(tmp_path: Path):
    service = KeplerAstroNetService(Settings(model_registry_path=tmp_path / "missing.json"))

    assert service.model_id == KEPLER_ASTRONET_MODEL_ID


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


def test_exomac_feature_builder_marks_nonpositive_logs_as_nan():
    candidate = TransitCandidate(period=0.0, epoch=1.0, duration=0.125, depth=0.0, power=9.0, signal_to_noise=0.0)

    features = build_exomac_features(candidate)

    assert np.isnan(features["log_koi_period"])
    assert np.isnan(features["log_koi_depth"])
    assert np.isnan(features["log_koi_snr"])


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


def test_exomac_service_artifact_validation_edges(tmp_path: Path):
    service = ExoMACService(Settings(model_registry_path=tmp_path / "missing-registry.json"))
    with pytest.raises(ModelArtifactError, match="not registered"):
        service.validate_artifact()

    service.model_path = tmp_path / "missing"
    service.model_checksum = "deadbeef"
    with pytest.raises(ModelArtifactError, match="does not exist"):
        service.validate_artifact()

    file_artifact = tmp_path / "exomac-file"
    file_artifact.write_text("not a directory", encoding="utf-8")
    service.model_path = file_artifact
    with pytest.raises(ModelArtifactError, match="directory bundle"):
        service.validate_artifact()

    bundle = tmp_path / "exomac-incomplete"
    bundle.mkdir()
    service.model_path = bundle
    with pytest.raises(ModelArtifactError, match="missing files"):
        service.validate_artifact()

    for name in (
        "exoplanet_best_model.joblib",
        "exoplanet_feature_columns.json",
        "exoplanet_class_labels.json",
        "exoplanet_metadata.json",
    ):
        (bundle / name).write_text("{}", encoding="utf-8")
    service.model_checksum = None
    with pytest.raises(ModelArtifactError, match="checksum is required"):
        service.validate_artifact()

    service.model_checksum = "deadbeef"
    with pytest.raises(ModelArtifactError, match="checksum mismatch"):
        service.validate_artifact()


def test_exomac_predict_handles_string_labels_without_probabilities():
    service = ExoMACService.__new__(ExoMACService)
    service.model_id = K2_EXOMAC_MODEL_ID
    service.model_path = None
    service.model_checksum = None
    service.model_source = "unit"
    service.model_version = "unit-v1"
    service._model = StringOnlyExoMACModel()
    service._feature_columns = ["koi_period", "koi_depth"]
    service._class_labels = ["CANDIDATE", "False Positive"]

    verdict = service.predict({"koi_period": 3.0}, threshold=0.5)

    assert verdict.label == "false-positive"
    assert verdict.probability == pytest.approx(1.0)
    assert verdict.class_probabilities == {}


def test_exomac_predict_loads_on_demand(monkeypatch: pytest.MonkeyPatch):
    service = ExoMACService.__new__(ExoMACService)
    service.model_id = K2_EXOMAC_MODEL_ID
    service.model_path = None
    service.model_checksum = None
    service.model_source = "unit"
    service.model_version = "unit-v1"
    service._model = None
    service._feature_columns = None
    service._class_labels = None

    def fake_load():
        service._model = TinyExoMACModel()
        service._feature_columns = ["koi_period"]
        service._class_labels = ["CANDIDATE", "CONFIRMED", "FALSE POSITIVE"]
        return ExoMACModelInfo(K2_EXOMAC_MODEL_ID, "unit-v1", "unit", "checksum", "schema", "ready")

    monkeypatch.setattr(service, "load", fake_load)

    assert service.predict({"koi_period": 3.0}).label == "candidate"


def test_nigraha_service_validation_cache_and_schema_edges(tmp_path: Path):
    service = NigrahaService.__new__(NigrahaService)
    service.model_id = "nigraha-test"
    service.artifact = types.SimpleNamespace(sha256="deadbeef", version="unit-v1", source="unit")

    service.model_path = tmp_path / "missing"
    with pytest.raises(ModelArtifactError, match="does not exist"):
        service.validate_artifact()

    file_artifact = tmp_path / "nigraha-file"
    file_artifact.write_text("not a directory", encoding="utf-8")
    service.model_path = file_artifact
    with pytest.raises(ModelArtifactError, match="must be a directory"):
        service.validate_artifact()

    bundle = tmp_path / "nigraha"
    bundle.mkdir()
    service.model_path = bundle
    with pytest.raises(ModelArtifactError, match="requires 10"):
        service.validate_artifact()

    for index in range(10):
        (bundle / f"models_{index}.hdf5").write_bytes(b"not-real-hdf5")
    with pytest.raises(ModelArtifactError, match="checksum mismatch"):
        service.validate_artifact()

    info = NigrahaModelInfo("nigraha-test", "unit-v1", "unit", "deadbeef", NIGRAHA_SCHEMA_VERSION, "ready")
    cache_key = f"{service.model_id}:{service.artifact.sha256}:{service.model_path}"
    old_cache = dict(nigraha_service_module._GLOBAL_NIGRAHA_CACHE)
    try:
        nigraha_service_module._GLOBAL_NIGRAHA_CACHE.clear()
        nigraha_service_module._GLOBAL_NIGRAHA_CACHE[cache_key] = (info, [])
        assert service.load() is info
    finally:
        nigraha_service_module._GLOBAL_NIGRAHA_CACHE.clear()
        nigraha_service_module._GLOBAL_NIGRAHA_CACHE.update(old_cache)

    tensors = NigrahaTensors(
        global_view=np.zeros((1, 2001, 1), dtype=np.float32),
        local_view=np.zeros((1, 201, 1), dtype=np.float32),
        odd_even_view=np.zeros((1, 201, 1), dtype=np.float32),
        scalar_features={
            name: np.zeros((1, 1), dtype=np.float32)
            for name in (
                "Depth",
                "Duration",
                "Teff",
                "Radius",
                "logg",
                "Mass",
                "lum",
                "rho",
                "rp_rs",
                "DepthEven",
                "DepthOdd",
            )
        },
        imputed_features=(),
        checksum="tensor-checksum",
        schema_version="old-schema",
    )
    with pytest.raises(ModelArtifactError, match="schema is incompatible"):
        service.predict(tensors)


def test_nigraha_numpy_model_defensive_math_edges():
    model = NigrahaNumpyModel.__new__(NigrahaNumpyModel)

    with pytest.raises(ModelArtifactError, match="channel mismatch"):
        model._conv1d_same(np.zeros((1, 5, 2), dtype=np.float32), np.zeros((3, 1, 1), dtype=np.float32), np.zeros(1))

    model.weights = {"dense": (np.asarray([[2.0]], dtype=np.float32), np.asarray([-1.0], dtype=np.float32))}
    sigmoid = model._dense(np.asarray([[1.0]], dtype=np.float32), "dense", activation="sigmoid")
    linear = model._dense(np.asarray([[1.0]], dtype=np.float32), "dense", activation="linear")

    assert sigmoid == pytest.approx(np.asarray([[1.0 / (1.0 + np.exp(-1.0))]], dtype=np.float32))
    assert linear == pytest.approx(np.asarray([[1.0]], dtype=np.float32))


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
