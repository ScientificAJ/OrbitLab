from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np

from orbitlab.config import settings
from orbitlab.ml.checksum import sha256_path

CALIBRATION_DIR = settings.model_registry_path.parent / "models" / "calibration"


@dataclass(frozen=True)
class ProbabilityCalibration:
    mission: str
    method: str
    source: str
    path: Path
    checksum: str
    payload: dict[str, Any]


def _calibration_path(mission: str, root: Path = CALIBRATION_DIR) -> Path:
    return root / f"{mission.lower()}-probability-calibration.json"


def load_probability_calibration(mission: str, root: Path = CALIBRATION_DIR) -> ProbabilityCalibration | None:
    path = _calibration_path(mission, root)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ProbabilityCalibration(
        mission=mission.upper(),
        method=str(payload.get("method", "unknown")),
        source=str(payload.get("source", path.name)),
        path=path,
        checksum=sha256_path(path),
        payload=payload,
    )


def apply_probability_calibration(probability: float | None, mission: str) -> dict[str, Any]:
    if probability is None or not np.isfinite(probability):
        return {
            "raw_ml_probability": probability,
            "calibrated_ml_probability": None,
            "calibration_source": None,
            "calibration_method": None,
            "calibration_checksum": None,
        }
    calibration = load_probability_calibration(mission)
    raw = float(np.clip(probability, 0.0, 1.0))
    if calibration is None:
        return {
            "raw_ml_probability": raw,
            "calibrated_ml_probability": raw,
            "calibration_source": "identity_no_local_calibration_bundle",
            "calibration_method": "identity",
            "calibration_checksum": None,
        }
    payload = calibration.payload
    if calibration.method == "isotonic_bins":
        x = np.asarray(payload["x"], dtype=float)
        y = np.asarray(payload["y"], dtype=float)
        calibrated = float(np.interp(raw, x, y, left=y[0], right=y[-1]))
    elif calibration.method == "sigmoid":
        coef = float(payload["coef"])
        intercept = float(payload["intercept"])
        calibrated = float(1.0 / (1.0 + np.exp(-(coef * raw + intercept))))
    else:
        calibrated = raw
    return {
        "raw_ml_probability": raw,
        "calibrated_ml_probability": float(np.clip(calibrated, 0.0, 1.0)),
        "calibration_source": calibration.source,
        "calibration_method": calibration.method,
        "calibration_checksum": calibration.checksum,
    }


def attach_probability_calibration(ml: dict[str, Any], mission: str) -> dict[str, Any]:
    next_ml = dict(ml)
    calibration = apply_probability_calibration(next_ml.get("probability"), mission)
    next_ml.update(calibration)
    return next_ml
