from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import numpy as np

from orbitlab.science.bls import TransitCandidate
from orbitlab.science.data_quality import clean_light_curve
from orbitlab.science.folding import bin_phase_curve, phase_fold


GLOBAL_BINS = 2001
LOCAL_BINS = 201
SCHEMA_VERSION = "orbitlab.astronet.v1"


@dataclass(frozen=True)
class AstroNetTensors:
    global_view: np.ndarray
    local_view: np.ndarray
    metadata: np.ndarray
    checksum: str
    schema_version: str = SCHEMA_VERSION

    def as_inputs(self) -> dict[str, np.ndarray]:
        return {
            "global_view": self.global_view,
            "local_view": self.local_view,
            "metadata": self.metadata,
        }


def _normalize_view(flux: np.ndarray) -> np.ndarray:
    arr = np.asarray(flux, dtype=np.float32)
    median = np.nanmedian(arr)
    scale = np.nanpercentile(np.abs(arr - median), 95)
    if not np.isfinite(scale) or scale == 0:
        scale = np.nanstd(arr)
    if not np.isfinite(scale) or scale == 0:
        raise ValueError("cannot normalize a flat or invalid folded view")
    return ((arr - median) / scale).astype(np.float32)


def _checksum(global_view: np.ndarray, local_view: np.ndarray, metadata: np.ndarray) -> str:
    digest = hashlib.sha256()
    for arr in (global_view, local_view, metadata):
        digest.update(np.ascontiguousarray(arr).tobytes())
    return digest.hexdigest()


def build_astronet_tensors(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    *,
    stellar_radius_solar: float | None = None,
    stellar_mass_solar: float | None = None,
) -> AstroNetTensors:
    t, f = clean_light_curve(time, flux)
    phase, folded_flux = phase_fold(t, f, candidate.period, candidate.epoch)
    _, global_flux = bin_phase_curve(phase, folded_flux, GLOBAL_BINS)

    local_half_width = max(2.5 * candidate.duration / candidate.period, 0.015)
    local_mask = np.abs(phase) <= local_half_width
    if local_mask.sum() < 16:
        raise ValueError("candidate has insufficient local transit samples for AstroNet adapter")
    local_phase = phase[local_mask] / (2 * local_half_width)
    _, local_flux = bin_phase_curve(local_phase, folded_flux[local_mask], LOCAL_BINS)

    global_view = _normalize_view(global_flux).reshape(1, GLOBAL_BINS, 1).astype(np.float32)
    local_view = _normalize_view(local_flux).reshape(1, LOCAL_BINS, 1).astype(np.float32)
    metadata = np.asarray(
        [
            candidate.period,
            candidate.epoch,
            candidate.duration,
            candidate.depth,
            candidate.signal_to_noise,
            stellar_radius_solar or np.nan,
            stellar_mass_solar or np.nan,
        ],
        dtype=np.float32,
    ).reshape(1, 7)
    if not np.isfinite(global_view).all() or not np.isfinite(local_view).all():
        raise ValueError("AstroNet tensors contain NaN or infinite values")
    checksum = _checksum(global_view, local_view, metadata)
    return AstroNetTensors(global_view, local_view, metadata, checksum)


def tensor_schema() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "inputs": {
            "global_view": [1, GLOBAL_BINS, 1],
            "local_view": [1, LOCAL_BINS, 1],
            "metadata": [1, 7],
        },
        "dtype": "float32",
    }


def tensor_schema_json() -> str:
    return json.dumps(tensor_schema(), sort_keys=True)

