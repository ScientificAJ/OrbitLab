from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from orbitlab.config import settings
from orbitlab.ml.checksum import sha256_path

KEPLER_ASTRONET_MODEL_ID = "kepler-astronet-cnn-bilstm-attention"
K2_EXOMAC_MODEL_ID = "k2-exomac-kkt-randomforest"


@dataclass(frozen=True)
class RegisteredArtifact:
    model_id: str
    mission: str
    path: str
    sha256: str
    source: str
    version: str
    format: str


def _load_registry(path: Path) -> dict:
    if not path.exists():
        return {"artifacts": []}
    return json.loads(path.read_text())


def register_artifact(
    *,
    model_id: str,
    mission: str,
    path: Path,
    source: str,
    version: str,
    registry_path: Path = settings.model_registry_path,
) -> RegisteredArtifact:
    artifact_path = path.expanduser().resolve()
    if not artifact_path.exists():
        raise FileNotFoundError(f"model artifact path does not exist: {artifact_path}")
    checksum = sha256_path(artifact_path)
    suffix = artifact_path.suffix.lower()
    if artifact_path.is_dir() and (artifact_path / "exoplanet_best_model.joblib").exists():
        fmt = "sklearn-joblib-bundle"
    elif artifact_path.is_dir() and list(artifact_path.glob("*.ckpt-*.index")):
        fmt = "tensorflow-checkpoint"
    elif artifact_path.is_dir() and list(artifact_path.glob("*.hdf5")):
        fmt = "keras-hdf5-ensemble"
    elif suffix == ".joblib":
        fmt = "sklearn-joblib"
    elif suffix == ".npz":
        fmt = "numpy-npz"
    elif suffix == ".onnx":
        fmt = "onnx"
    elif suffix in {".h5", ".hdf5", ".keras"}:
        fmt = "keras-hdf5"
    else:
        fmt = "savedmodel"
    artifact = RegisteredArtifact(
        model_id=model_id,
        mission=mission,
        path=str(artifact_path),
        sha256=checksum,
        source=source,
        version=version,
        format=fmt,
    )
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry = _load_registry(registry_path)
    registry["artifacts"] = [
        existing for existing in registry.get("artifacts", []) if existing.get("model_id") != model_id
    ]
    registry["artifacts"].append(asdict(artifact))
    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True))
    return artifact


def get_registered_artifact(model_id: str, registry_path: Path = settings.model_registry_path) -> RegisteredArtifact:
    registry = _load_registry(registry_path)
    for entry in registry.get("artifacts", []):
        if entry.get("model_id") == model_id:
            return RegisteredArtifact(**entry)
    raise KeyError(f"model artifact is not registered: {model_id}")


def artifact_status(model_id: str, registry_path: Path = settings.model_registry_path) -> dict:
    try:
        artifact = get_registered_artifact(model_id, registry_path)
    except (FileNotFoundError, KeyError, ValueError, TypeError) as exc:
        return {"model_id": model_id, "status": "unavailable", "detail": str(exc)}
    path = Path(artifact.path)
    if not path.exists():
        return {"model_id": model_id, "status": "unavailable", "detail": f"artifact path does not exist: {path}"}
    try:
        actual = sha256_path(path)
    except Exception as exc:
        return {"model_id": model_id, "status": "unavailable", "detail": str(exc)}
    if actual.lower() != artifact.sha256.lower():
        return {"model_id": model_id, "status": "unavailable", "detail": "artifact checksum mismatch"}
    payload = asdict(artifact)
    payload.update({"checksum": actual, "status": "ready"})
    return payload
