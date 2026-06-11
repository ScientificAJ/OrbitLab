from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("science_config.toml")
CORE_CONFIG_KEYS = {
    "promotion_snr",
    "borderline_snr_min",
    "aperture_percentiles",
    "max_duration_period_ratio",
    "secondary_eclipse_hard_fail_snr",
    "odd_even_hard_fail_sigma",
    "odd_even_large_effect_fraction",
    "transit_support_depth_fraction",
    "centroid_hard_fail_pixels",
    "quality_flag_dominance_fraction",
    "red_noise_warning_beta",
    "forced_period_tolerance_fraction",
    "paper_promotion_snr",
    "paper_tls_sde_min",
    "paper_min_transits",
    "paper_ml_threshold",
    "paper_sweet_sigma",
    "paper_model_shift_objects",
    "paper_triceratops_fpp_max",
    "paper_triceratops_nfpp_max",
    "paper_triceratops_fpp_reject",
    "paper_triceratops_nfpp_reject",
    "paper_triceratops_samples",
    "paper_catalog_radius_arcsec",
}


@dataclass(frozen=True)
class SearchProfile:
    name: str
    min_period: float
    max_period: float
    period_samples: int
    max_period_samples: int
    min_transits: float
    max_search_cadences: int
    warning: str = ""


@dataclass(frozen=True)
class ScienceConfig:
    promotion_snr: float
    borderline_snr_min: float
    aperture_percentiles: tuple[int, ...]
    max_duration_period_ratio: float
    secondary_eclipse_hard_fail_snr: float
    odd_even_hard_fail_sigma: float
    odd_even_large_effect_fraction: float
    transit_support_depth_fraction: float
    centroid_hard_fail_pixels: float
    quality_flag_dominance_fraction: float
    red_noise_warning_beta: float
    forced_period_tolerance_fraction: float
    paper_promotion_snr: float
    paper_tls_sde_min: float
    paper_min_transits: int
    paper_ml_threshold: float
    paper_sweet_sigma: float
    paper_model_shift_objects: int
    paper_triceratops_fpp_max: float
    paper_triceratops_nfpp_max: float
    paper_triceratops_fpp_reject: float
    paper_triceratops_nfpp_reject: float
    paper_triceratops_samples: int
    paper_catalog_radius_arcsec: float
    search_profiles: dict[str, SearchProfile]


def load_science_config(path: Path = CONFIG_PATH) -> ScienceConfig:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    profiles = {
        name: SearchProfile(
            name=name,
            min_period=float(payload["min_period"]),
            max_period=float(payload["max_period"]),
            period_samples=int(payload["period_samples"]),
            max_period_samples=int(payload["max_period_samples"]),
            min_transits=float(payload["min_transits"]),
            max_search_cadences=int(payload["max_search_cadences"]),
            warning=str(payload.get("warning", "")),
        )
        for name, payload in data.get("search_profiles", {}).items()
    }
    return ScienceConfig(
        promotion_snr=float(data["promotion_snr"]),
        borderline_snr_min=float(data["borderline_snr_min"]),
        aperture_percentiles=tuple(int(value) for value in data["aperture_percentiles"]),
        max_duration_period_ratio=float(data["max_duration_period_ratio"]),
        secondary_eclipse_hard_fail_snr=float(data["secondary_eclipse_hard_fail_snr"]),
        odd_even_hard_fail_sigma=float(data["odd_even_hard_fail_sigma"]),
        odd_even_large_effect_fraction=float(data["odd_even_large_effect_fraction"]),
        transit_support_depth_fraction=float(data["transit_support_depth_fraction"]),
        centroid_hard_fail_pixels=float(data["centroid_hard_fail_pixels"]),
        quality_flag_dominance_fraction=float(data["quality_flag_dominance_fraction"]),
        red_noise_warning_beta=float(data["red_noise_warning_beta"]),
        forced_period_tolerance_fraction=float(data["forced_period_tolerance_fraction"]),
        paper_promotion_snr=float(data["paper_promotion_snr"]),
        paper_tls_sde_min=float(data["paper_tls_sde_min"]),
        paper_min_transits=int(data["paper_min_transits"]),
        paper_ml_threshold=float(data["paper_ml_threshold"]),
        paper_sweet_sigma=float(data["paper_sweet_sigma"]),
        paper_model_shift_objects=int(data["paper_model_shift_objects"]),
        paper_triceratops_fpp_max=float(data["paper_triceratops_fpp_max"]),
        paper_triceratops_nfpp_max=float(data["paper_triceratops_nfpp_max"]),
        paper_triceratops_fpp_reject=float(data["paper_triceratops_fpp_reject"]),
        paper_triceratops_nfpp_reject=float(data["paper_triceratops_nfpp_reject"]),
        paper_triceratops_samples=int(data["paper_triceratops_samples"]),
        paper_catalog_radius_arcsec=float(data["paper_catalog_radius_arcsec"]),
        search_profiles=profiles,
    )


def science_config_hash(path: Path = CONFIG_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config_usage_audit(path: Path = CONFIG_PATH) -> dict[str, list[str]]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    configured = {key for key in data if key != "search_profiles"}
    dataclass_keys = {field.name for field in fields(ScienceConfig)} - {"search_profiles"}
    active = sorted(configured & CORE_CONFIG_KEYS & dataclass_keys)
    missing = sorted(CORE_CONFIG_KEYS - configured)
    inactive = sorted(configured - CORE_CONFIG_KEYS)
    return {
        "active_science_config_keys": active,
        "inactive_science_config_keys": inactive,
        "missing_science_config_keys": missing,
    }


def get_search_profile(config: ScienceConfig, name: str) -> SearchProfile:
    try:
        return config.search_profiles[name]
    except KeyError as exc:
        available = ", ".join(sorted(config.search_profiles))
        raise ValueError(f"unknown search profile {name!r}; available profiles: {available}") from exc
