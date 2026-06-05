from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from orbitlab.config import settings
from orbitlab.science.bls import TransitCandidate
from orbitlab.science.data_quality import clean_light_curve
from orbitlab.science.folding import bin_phase_curve, phase_fold

NIGRAHA_SCHEMA_VERSION = "orbitlab.nigraha.v2-standardized"
NIGRAHA_MODEL_ID = "nigraha-tess-global-nodropout-binary-ensemble"
NIGRAHA_FEATURES = (
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

# Upstream ExoplanetML/Nigraha standardizes only the stellar-catalog scalar
# features before the dense head (subtract training median, divide by training
# std); the transit features Depth/Duration/rp_rs/DepthEven/DepthOdd are in
# upstream `raw_columns` and pass through unchanged. The standardization
# constants are recovered from the committed upstream training catalog by
# scripts/recover_nigraha_norm_stats.py (Rao et al. 2021, MNRAS 502, 2845).
NIGRAHA_STANDARDIZED_FEATURES = ("Teff", "Radius", "logg", "Mass", "lum", "rho")


# Cache of parsed norm-stats keyed by resolved artifact path. Mirrors the
# service's _GLOBAL_NIGRAHA_CACHE so we parse the JSON once per process.
_NORM_STATS_CACHE: dict[str, dict[str, tuple[float, float]] | None] = {}


# Committed norm-stats artifact bundled with the package — available in all
# environments including CI without needing to run the recovery script first.
_BUNDLED_NORM_STATS = Path(__file__).parent / "data" / "nigraha_norm_stats.json"


def load_norm_stats(path: Path | None = None) -> dict[str, tuple[float, float]] | None:
    """Load per-feature (median, std) standardization constants.

    Resolution order:
    1. Explicit ``path`` argument (for tests / overrides).
    2. ``settings.nigraha_norm_stats_path`` if it exists on disk.
    3. ``_BUNDLED_NORM_STATS`` — the committed fallback that works in CI.

    Returns ``None`` only when all three are absent or unreadable, at which
    point the caller falls back to the honest saturation gate.
    """
    if path is None:
        settings_path = settings.nigraha_norm_stats_path
        path = settings_path if settings_path.exists() else _BUNDLED_NORM_STATS
    resolved = path
    key = str(resolved)
    if key in _NORM_STATS_CACHE:
        return _NORM_STATS_CACHE[key]

    stats: dict[str, tuple[float, float]] | None = None
    try:
        payload = json.loads(Path(resolved).read_text())
        parsed: dict[str, tuple[float, float]] = {}
        for name in NIGRAHA_STANDARDIZED_FEATURES:
            entry = payload.get("features", {}).get(name)
            if not entry or not entry.get("standardized"):
                continue
            std = float(entry["std"])
            if math.isfinite(std) and std > 0:
                parsed[name] = (float(entry["median"]), std)
        if parsed:
            stats = parsed
    except (OSError, ValueError, KeyError, TypeError):
        stats = None

    _NORM_STATS_CACHE[key] = stats
    return stats


def clear_norm_stats_cache() -> None:
    """Clear the parsed norm-stats cache (test hygiene)."""
    _NORM_STATS_CACHE.clear()


@dataclass(frozen=True)
class NigrahaTensors:
    global_view: np.ndarray
    local_view: np.ndarray
    odd_even_view: np.ndarray
    scalar_features: dict[str, np.ndarray]
    imputed_features: tuple[str, ...]
    checksum: str
    schema_version: str = NIGRAHA_SCHEMA_VERSION
    # True when upstream-recovered standardization was applied to the stellar
    # scalar features. False means the norm-stats artifact was unavailable and
    # raw values were fed (saturated regime) -> the service falls back to the
    # honest saturation gate.
    standardized: bool = False
    standardized_features: tuple[str, ...] = ()

    def as_inputs(self) -> dict[str, np.ndarray]:
        inputs = {
            "global_view": self.global_view,
            "local_view": self.local_view,
            "odd_even_view": self.odd_even_view,
        }
        inputs.update(self.scalar_features)
        return inputs


def _nigraha_scale(flux: np.ndarray) -> np.ndarray:
    arr = np.asarray(flux, dtype=np.float32)
    arr = arr - float(np.nanmedian(arr))
    minimum = np.nanmin(arr)
    scale = abs(float(minimum))
    if not np.isfinite(scale) or scale == 0:
        scale = float(np.nanstd(arr))
    if not np.isfinite(scale) or scale == 0:
        raise ValueError("Nigraha view cannot be scaled from a flat curve")
    scaled = (arr / scale) * 2.0 + 1.0
    return scaled.astype(np.float32)


def _centered_local_view(
    phase: np.ndarray,
    flux: np.ndarray,
    *,
    duration_days: float,
    period_days: float,
    bins: int,
) -> np.ndarray:
    fractional_duration = duration_days / period_days
    half_width = max(2.0 * fractional_duration, 0.015)
    mask = (phase > -half_width) & (phase < half_width)
    if mask.sum() < 8:
        raise ValueError("Nigraha local view has too few in-window cadences")
    local_phase = phase[mask] / (2.0 * half_width)
    _, binned = bin_phase_curve(local_phase, flux[mask], bins)
    return binned


def _transit_depths(time: np.ndarray, flux: np.ndarray, candidate: TransitCandidate) -> tuple[float, float]:
    transit_number = np.floor((time - candidate.epoch) / candidate.period).astype(int)
    phase_time = np.abs(((time - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period)
    in_transit = phase_time < 0.5 * candidate.duration
    out_of_transit = phase_time > 1.5 * candidate.duration
    baseline = float(np.nanmedian(flux[out_of_transit])) if out_of_transit.any() else float(np.nanmedian(flux))
    depths = []
    for parity in (0, 1):
        mask = in_transit & (transit_number % 2 == parity)
        if mask.any():
            depths.append(max(0.0, baseline - float(np.nanmedian(flux[mask]))))
        else:
            depths.append(float("nan"))
    return depths[0], depths[1]


def _scalar(value: float | None, name: str, imputed: list[str], default: float = 0.0) -> np.ndarray:
    if value is None or not math.isfinite(float(value)):
        imputed.append(name)
        value = default
    return np.asarray([[float(value)]], dtype=np.float32)


def _standardize(
    tensor: np.ndarray,
    name: str,
    stats: dict[str, tuple[float, float]] | None,
) -> np.ndarray:
    """Apply upstream (median, std) standardization to a stellar scalar feature.

    Standardization runs *after* imputation, so solar-fallback defaults are
    z-scored exactly as upstream's median-filled values would be. No-op when
    stats are unavailable or this feature was not standardized upstream.
    """
    if not stats or name not in stats:
        return tensor
    median, std = stats[name]
    return ((tensor - median) / std).astype(np.float32)


def _checksum(parts: list[np.ndarray]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(np.ascontiguousarray(part).tobytes())
    return digest.hexdigest()


def build_nigraha_tensors(
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    *,
    stellar_teff: float | None = None,
    stellar_radius_solar: float | None = None,
    stellar_logg: float | None = None,
    stellar_mass_solar: float | None = None,
    stellar_luminosity_solar: float | None = None,
    stellar_density_solar: float | None = None,
    norm_stats_path: Path | None = None,
) -> NigrahaTensors:
    clean_time, clean_flux = clean_light_curve(time, flux)
    phase, folded_flux = phase_fold(clean_time, clean_flux, candidate.period, candidate.epoch)
    _, global_flux = bin_phase_curve(phase, folded_flux, 201)
    local_flux = _centered_local_view(
        phase,
        folded_flux,
        duration_days=candidate.duration,
        period_days=candidate.period,
        bins=81,
    )

    half_phase, half_flux = phase_fold(
        clean_time,
        clean_flux,
        candidate.period,
        candidate.epoch - 0.5 * candidate.period,
    )
    half_local_flux = _centered_local_view(
        half_phase,
        half_flux,
        duration_days=candidate.duration,
        period_days=candidate.period,
        bins=81,
    )
    primary_local_flux = _centered_local_view(
        phase,
        folded_flux,
        duration_days=candidate.duration,
        period_days=candidate.period,
        bins=81,
    )
    odd_even_flux = np.concatenate([half_local_flux, primary_local_flux]).astype(np.float32)

    global_view = _nigraha_scale(global_flux).reshape(1, 201, 1)
    local_view = _nigraha_scale(local_flux).reshape(1, 81, 1)
    odd_even_view = _nigraha_scale(odd_even_flux).reshape(1, 162, 1)
    depth_even, depth_odd = _transit_depths(clean_time, clean_flux, candidate)
    imputed: list[str] = []
    rp_rs = math.sqrt(candidate.depth) if candidate.depth > 0 else None
    # Raw scalar tensors (post-imputation, pre-standardization). The five transit
    # features stay raw (upstream `raw_columns`); the six stellar features are
    # standardized below using the upstream-recovered (median, std) constants.
    scalars = {
        "Depth": _scalar(candidate.depth, "Depth", imputed, default=0.0),
        "Duration": _scalar(candidate.duration * 24.0, "Duration", imputed, default=0.0),
        "Teff": _scalar(stellar_teff, "Teff", imputed, default=5778.0),
        "Radius": _scalar(stellar_radius_solar, "Radius", imputed, default=1.0),
        "logg": _scalar(stellar_logg, "logg", imputed, default=4.44),
        "Mass": _scalar(stellar_mass_solar, "Mass", imputed, default=1.0),
        "lum": _scalar(stellar_luminosity_solar, "lum", imputed, default=1.0),
        "rho": _scalar(stellar_density_solar, "rho", imputed, default=1.0),
        "rp_rs": _scalar(rp_rs, "rp_rs", imputed, default=0.0),
        "DepthEven": _scalar(depth_even, "DepthEven", imputed, default=candidate.depth),
        "DepthOdd": _scalar(depth_odd, "DepthOdd", imputed, default=candidate.depth),
    }

    stats = load_norm_stats(norm_stats_path)
    standardized_features: tuple[str, ...] = ()
    if stats:
        applied = []
        for name in NIGRAHA_STANDARDIZED_FEATURES:
            if name in stats:
                scalars[name] = _standardize(scalars[name], name, stats)
                applied.append(name)
        standardized_features = tuple(applied)

    parts = [global_view, local_view, odd_even_view] + [scalars[name] for name in NIGRAHA_FEATURES]
    if not all(np.isfinite(part).all() for part in parts):
        raise ValueError("Nigraha tensors contain NaN or infinite values")
    return NigrahaTensors(
        global_view=global_view.astype(np.float32),
        local_view=local_view.astype(np.float32),
        odd_even_view=odd_even_view.astype(np.float32),
        scalar_features=scalars,
        imputed_features=tuple(imputed),
        checksum=_checksum(parts),
        standardized=bool(standardized_features),
        standardized_features=standardized_features,
    )


def nigraha_tensor_schema() -> dict:
    return {
        "schema_version": NIGRAHA_SCHEMA_VERSION,
        "inputs": {
            "global_view": [1, 201, 1],
            "local_view": [1, 81, 1],
            "odd_even_view": [1, 162, 1],
            **{name: [1, 1] for name in NIGRAHA_FEATURES},
        },
        "dtype": "float32",
    }
