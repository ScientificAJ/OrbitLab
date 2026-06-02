from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from orbitlab.config import Settings, settings
from orbitlab.exceptions import ModelArtifactError
from orbitlab.ml.artifact_registry import KEPLER_ASTRONET_MODEL_ID, get_registered_artifact
from orbitlab.ml.astronet_adapter import SCHEMA_VERSION, AstroNetTensors
from orbitlab.ml.checksum import sha256_path


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    version: str
    source: str
    checksum: str
    schema_version: str
    status: str


@dataclass(frozen=True)
class AstroNetVerdict:
    probability: float
    threshold: float
    label: str
    model_version: str
    model_source: str
    input_tensor_checksum: str
    preprocessing_compatible: bool
    citation: str


class AstroNetService:
    def __init__(self, config: Settings = settings, model_id: str | None = None):
        self.config = config
        self.model_id = model_id or config.astronet_model_id
        self.model_path = config.astronet_model_path
        self.model_checksum = config.astronet_model_sha256
        self.model_source = config.astronet_model_source
        self.model_version = config.astronet_model_version
        if self.model_path is None or self.model_checksum is None:
            try:
                artifact = get_registered_artifact(self.model_id, config.model_registry_path)
            except (FileNotFoundError, KeyError, ValueError, TypeError):
                artifact = None
            if artifact is not None:
                self.model_path = Path(artifact.path)
                self.model_checksum = artifact.sha256
                self.model_source = artifact.source
                self.model_version = artifact.version
        self._runtime = None
        self._backend = None

    def validate_artifact(self) -> ModelInfo:
        if self.model_path is None:
            raise ModelArtifactError("ORBITLAB_ASTRONET_MODEL_PATH is required")
        if not self.model_path.exists():
            raise ModelArtifactError(f"model artifact does not exist: {self.model_path}")
        if not self.model_checksum:
            raise ModelArtifactError("ORBITLAB_ASTRONET_MODEL_SHA256 is required")
        actual = sha256_path(self.model_path)
        if actual.lower() != self.model_checksum.lower():
            raise ModelArtifactError("model artifact checksum mismatch")
        suffix = self.model_path.suffix.lower()
        if suffix not in {".npz", ".onnx"} and not _is_tensorflow_checkpoint_dir(self.model_path):
            raise ModelArtifactError(
                "AstroNet runtime requires a registered .npz, .onnx, or TensorFlow checkpoint artifact"
            )
        return ModelInfo(
            model_id=self.model_id,
            version=self.model_version,
            source=self.model_source,
            checksum=actual,
            schema_version=SCHEMA_VERSION,
            status="ready",
        )

    def load(self) -> ModelInfo:
        info = self.validate_artifact()
        suffix = self.model_path.suffix.lower() if self.model_path else ""
        if self.model_path.is_dir() and _is_tensorflow_checkpoint_dir(self.model_path):
            self._runtime = DockerTensorFlowAstroNetRuntime(self.model_path)
            self._backend = "tensorflow-docker"
        elif suffix == ".npz":
            self._runtime = NumpyAstroNetRuntime(self.model_path)
            self._backend = "numpy"
        elif suffix == ".onnx":
            try:
                import onnxruntime as ort
            except ImportError as exc:  # pragma: no cover - optional runtime
                raise ModelArtifactError("onnxruntime is required to load ONNX AstroNet artifacts") from exc
            self._runtime = ort.InferenceSession(str(self.model_path), providers=["CPUExecutionProvider"])
            self._backend = "onnx"
        else:
            raise ModelArtifactError(
                "AstroNet runtime requires a registered .npz or .onnx artifact; convert TensorFlow checkpoints first"
            )
        return info

    def predict(self, tensors: AstroNetTensors, *, threshold: float = 0.5) -> AstroNetVerdict:
        if tensors.schema_version != SCHEMA_VERSION:
            raise ModelArtifactError("AstroNet tensor schema is incompatible")
        if self._runtime is None:
            self.load()
        if self._backend in {"numpy", "tensorflow-docker"}:
            probability = self._runtime.predict(tensors)
        elif self._backend == "onnx":
            input_map = tensors.as_inputs()
            outputs = self._runtime.run(None, input_map)
            probability = float(np.asarray(outputs[0]).reshape(-1)[0])
        else:  # pragma: no cover
            raise ModelArtifactError("model runtime is not loaded")
        probability = min(max(probability, 0.0), 1.0)
        return AstroNetVerdict(
            probability=probability,
            threshold=threshold,
            label="planet-candidate" if probability >= threshold else "not-transit-like",
            model_version=self.model_version,
            model_source=self.model_source,
            input_tensor_checksum=tensors.checksum,
            preprocessing_compatible=True,
            citation="Google Research exoplanet-ml AstroNet; AstroNet-Triage/Vetting family where mission-compatible.",
        )


class NumpyAstroNetRuntime:
    """Small NumPy inference runner for converted OrbitLab AstroNet artifacts."""

    def __init__(self, path: Path):
        self.path = path
        self.weights = np.load(path, allow_pickle=False)
        required = {"global_kernel", "local_kernel", "metadata_kernel", "bias"}
        missing = required - set(self.weights.files)
        if missing:
            raise ModelArtifactError(f"NumPy AstroNet artifact missing arrays: {', '.join(sorted(missing))}")

    @staticmethod
    def _sigmoid(x: float) -> float:
        return float(1.0 / (1.0 + np.exp(-np.clip(x, -60.0, 60.0))))

    def predict(self, tensors: AstroNetTensors) -> float:
        global_view = tensors.global_view.reshape(1, -1).astype(np.float32)
        local_view = tensors.local_view.reshape(1, -1).astype(np.float32)
        metadata = np.nan_to_num(tensors.metadata.reshape(1, -1).astype(np.float32), nan=0.0)
        score = np.asarray(self.weights["bias"], dtype=np.float32).reshape(-1)[0]
        weighted_inputs = (
            (global_view, "global_kernel"),
            (local_view, "local_kernel"),
            (metadata, "metadata_kernel"),
        )
        for view, kernel_name in weighted_inputs:
            kernel = np.asarray(self.weights[kernel_name], dtype=np.float32).reshape(-1, 1)
            score += float((view @ kernel).reshape(-1)[0])
        return self._sigmoid(score)


def _is_tensorflow_checkpoint_dir(path: Path) -> bool:
    return path.is_dir() and bool(list(path.glob("*.ckpt-*.index")))


class DockerTensorFlowAstroNetRuntime:
    def __init__(self, checkpoint_dir: Path):
        self.checkpoint_dir = checkpoint_dir
        self.image = os.getenv("ORBITLAB_KEPLER_TF_IMAGE", "tensorflow/tensorflow:1.5.0-py3")
        indexes = sorted(checkpoint_dir.glob("*.ckpt-*.index"))
        if not indexes:
            raise ModelArtifactError(f"TensorFlow checkpoint directory has no .index file: {checkpoint_dir}")
        self.checkpoint_prefix = indexes[-1].with_suffix("")
        if shutil.which("docker") is None:
            raise ModelArtifactError("Docker is required to run the Kepler TensorFlow checkpoint on this CPU")

    def predict(self, tensors: AstroNetTensors) -> float:
        repo_root = Path(__file__).resolve().parents[3]
        script = repo_root / "scripts" / "predict_kepler_astronet_tf.py"
        if not script.exists():
            raise ModelArtifactError(f"Kepler TensorFlow prediction helper is missing: {script}")
        try:
            relative_prefix = self.checkpoint_prefix.resolve().relative_to(repo_root)
        except ValueError as exc:
            raise ModelArtifactError(
                "Kepler checkpoint must be inside the OrbitLab workspace for Docker inference"
            ) from exc
        with tempfile.TemporaryDirectory(prefix="orbitlab-kepler-") as temp_name:
            temp_dir = Path(temp_name)
            input_path = temp_dir / "input.npz"
            output_path = temp_dir / "output.json"
            np.savez(
                input_path,
                global_view=np.asarray(tensors.global_view, dtype=np.float32),
                local_view=np.asarray(tensors.local_view, dtype=np.float32),
            )
            command = [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{repo_root}:/workspace:ro",
                "-v",
                f"{temp_dir}:/orbitlab-tmp",
                "-w",
                "/workspace",
                self.image,
                "python",
                "scripts/predict_kepler_astronet_tf.py",
                "--checkpoint-prefix",
                f"/workspace/{relative_prefix}",
                "--input",
                "/orbitlab-tmp/input.npz",
                "--output",
                "/orbitlab-tmp/output.json",
            ]
            try:
                subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
            except subprocess.CalledProcessError as exc:
                detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
                raise ModelArtifactError(f"Kepler TensorFlow Docker inference failed: {detail}") from exc
            except subprocess.TimeoutExpired as exc:
                raise ModelArtifactError("Kepler TensorFlow Docker inference timed out") from exc
            return float(json.loads(output_path.read_text())["probability"])


class KeplerAstroNetService(AstroNetService):
    def __init__(self, config: Settings = settings):
        super().__init__(config=config, model_id=KEPLER_ASTRONET_MODEL_ID)
