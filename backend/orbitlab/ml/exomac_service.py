from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from orbitlab.config import Settings, settings
from orbitlab.exceptions import ModelArtifactError
from orbitlab.ml.artifact_registry import K2_EXOMAC_MODEL_ID, get_registered_artifact
from orbitlab.ml.checksum import sha256_path
from orbitlab.science.bls import TransitCandidate

EXOMAC_SOURCE = "ZapatoProgramming/ExoMAC-KKT pretrained NASA Kepler/K2/TESS catalog classifier"
EXOMAC_VERSION = "5cda5310d5a163679c6915f9463a4d6afc312483"
EXOMAC_CITATION = (
    "ExoMAC-KKT Hugging Face artifact; mission-agnostic RandomForest classifier trained on "
    "NASA Kepler, K2, and TESS candidate catalogs."
)


@dataclass(frozen=True)
class ExoMACModelInfo:
    model_id: str
    version: str
    source: str
    checksum: str
    schema_version: str
    status: str


@dataclass(frozen=True)
class ExoMACVerdict:
    probability: float
    threshold: float
    label: str
    model_version: str
    model_source: str
    input_tensor_checksum: str
    preprocessing_compatible: bool
    citation: str
    class_probabilities: dict[str, float]


def _finite_or_nan(value: float | int | None) -> float:
    if value is None:
        return float("nan")
    value_float = float(value)
    return value_float if math.isfinite(value_float) else float("nan")


def _safe_log10(value: float | int | None) -> float:
    value_float = _finite_or_nan(value)
    if not math.isfinite(value_float) or value_float <= 0:
        return float("nan")
    return math.log10(value_float)


def _checksum_features(features: dict[str, float]) -> str:
    normalized = {
        key: (None if not math.isfinite(value) else round(float(value), 12))
        for key, value in sorted(features.items())
    }
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_exomac_features(
    candidate: TransitCandidate,
    *,
    stellar_radius_solar: float | None = None,
    stellar_mass_solar: float | None = None,
    stellar_teff: float | None = None,
    stellar_logg: float | None = None,
    stellar_metallicity: float | None = None,
    planet_radius_earth: float | None = None,
    semi_major_axis_au: float | None = None,
) -> dict[str, float]:
    period_days = _finite_or_nan(candidate.period)
    duration_hours = _finite_or_nan(candidate.duration) * 24.0
    depth = _finite_or_nan(candidate.depth)
    snr = _finite_or_nan(candidate.signal_to_noise)
    duty_cycle = duration_hours / (period_days * 24.0) if period_days > 0 else float("nan")
    teq_proxy = _finite_or_nan(stellar_teff)
    return {
        "koi_depth": depth,
        "koi_duration": duration_hours,
        "koi_impact": float("nan"),
        "koi_period": period_days,
        "koi_prad": _finite_or_nan(planet_radius_earth),
        "koi_slogg": _finite_or_nan(stellar_logg),
        "koi_sma": _finite_or_nan(semi_major_axis_au),
        "koi_smet": _finite_or_nan(stellar_metallicity),
        "koi_snr": snr,
        "koi_srad": _finite_or_nan(stellar_radius_solar),
        "koi_steff": _finite_or_nan(stellar_teff),
        "duty_cycle": duty_cycle,
        "log_koi_period": _safe_log10(period_days),
        "log_koi_depth": _safe_log10(depth),
        "log_koi_snr": _safe_log10(snr),
        "teq_proxy": teq_proxy,
    }


class ExoMACService:
    def __init__(self, config: Settings = settings, model_id: str = K2_EXOMAC_MODEL_ID):
        self.config = config
        self.model_id = model_id
        self.model_path: Path | None = None
        self.model_checksum: str | None = None
        self.model_source = EXOMAC_SOURCE
        self.model_version = EXOMAC_VERSION
        try:
            artifact = get_registered_artifact(model_id, config.model_registry_path)
        except (FileNotFoundError, KeyError, ValueError, TypeError):
            artifact = None
        if artifact is not None:
            self.model_path = Path(artifact.path)
            self.model_checksum = artifact.sha256
            self.model_source = artifact.source
            self.model_version = artifact.version
        self._model: Any | None = None
        self._feature_columns: list[str] | None = None
        self._class_labels: list[str] | None = None

    def validate_artifact(self) -> ExoMACModelInfo:
        if self.model_path is None:
            raise ModelArtifactError(f"{self.model_id} is not registered")
        if not self.model_path.exists():
            raise ModelArtifactError(f"model artifact does not exist: {self.model_path}")
        if not self.model_path.is_dir():
            raise ModelArtifactError("ExoMAC artifact must be a directory bundle")
        required = [
            "exoplanet_best_model.joblib",
            "exoplanet_feature_columns.json",
            "exoplanet_class_labels.json",
            "exoplanet_metadata.json",
        ]
        missing = [name for name in required if not (self.model_path / name).exists()]
        if missing:
            raise ModelArtifactError(f"ExoMAC artifact is missing files: {', '.join(missing)}")
        if not self.model_checksum:
            raise ModelArtifactError("registered ExoMAC artifact checksum is required")
        actual = sha256_path(self.model_path)
        if actual.lower() != self.model_checksum.lower():
            raise ModelArtifactError("ExoMAC artifact checksum mismatch")
        return ExoMACModelInfo(
            model_id=self.model_id,
            version=self.model_version,
            source=self.model_source,
            checksum=actual,
            schema_version="orbitlab.exomac-kkt.v1",
            status="ready",
        )

    def load(self) -> ExoMACModelInfo:
        info = self.validate_artifact()
        try:
            import joblib
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ModelArtifactError("joblib is required to load ExoMAC artifacts") from exc
        assert self.model_path is not None
        self._model = joblib.load(self.model_path / "exoplanet_best_model.joblib")
        self._feature_columns = json.loads((self.model_path / "exoplanet_feature_columns.json").read_text())
        self._class_labels = json.loads((self.model_path / "exoplanet_class_labels.json").read_text())
        return info

    def predict(self, features: dict[str, float], *, threshold: float = 0.5) -> ExoMACVerdict:
        if self._model is None or self._feature_columns is None or self._class_labels is None:
            self.load()
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ModelArtifactError("pandas is required to run ExoMAC inference") from exc
        assert self._model is not None
        assert self._feature_columns is not None
        assert self._class_labels is not None
        row = {column: _finite_or_nan(features.get(column)) for column in self._feature_columns}
        frame = pd.DataFrame([row], columns=self._feature_columns, dtype=float)
        raw_prediction = np.asarray(self._model.predict(frame)).reshape(-1)[0]
        if isinstance(raw_prediction, str):
            predicted_label = raw_prediction
        else:
            predicted_label = self._class_labels[int(raw_prediction)]
        probabilities: dict[str, float] = {}
        if hasattr(self._model, "predict_proba"):
            proba = np.asarray(self._model.predict_proba(frame), dtype=float).reshape(-1)
            probabilities = {
                label: float(np.clip(proba[index], 0.0, 1.0))
                for index, label in enumerate(self._class_labels)
            }
        probability = probabilities.get(predicted_label, 1.0)
        normalized_label = predicted_label.lower().replace(" ", "-")
        return ExoMACVerdict(
            probability=float(probability),
            threshold=threshold,
            label=normalized_label if probability >= threshold else "low-confidence",
            model_version=self.model_version,
            model_source=self.model_source,
            input_tensor_checksum=_checksum_features(row),
            preprocessing_compatible=True,
            citation=EXOMAC_CITATION,
            class_probabilities=probabilities,
        )
