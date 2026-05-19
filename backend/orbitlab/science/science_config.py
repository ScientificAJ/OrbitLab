from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("science_config.toml")


@dataclass(frozen=True)
class ScienceConfig:
    promotion_snr: float
    borderline_snr_min: float
    aperture_percentiles: tuple[int, ...]
    max_duration_period_ratio: float
    secondary_eclipse_hard_fail_snr: float
    odd_even_hard_fail_sigma: float
    centroid_hard_fail_pixels: float
    quality_flag_dominance_fraction: float
    red_noise_warning_beta: float
    forced_period_tolerance_fraction: float


def load_science_config(path: Path = CONFIG_PATH) -> ScienceConfig:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return ScienceConfig(
        promotion_snr=float(data["promotion_snr"]),
        borderline_snr_min=float(data["borderline_snr_min"]),
        aperture_percentiles=tuple(int(value) for value in data["aperture_percentiles"]),
        max_duration_period_ratio=float(data["max_duration_period_ratio"]),
        secondary_eclipse_hard_fail_snr=float(data["secondary_eclipse_hard_fail_snr"]),
        odd_even_hard_fail_sigma=float(data["odd_even_hard_fail_sigma"]),
        centroid_hard_fail_pixels=float(data["centroid_hard_fail_pixels"]),
        quality_flag_dominance_fraction=float(data["quality_flag_dominance_fraction"]),
        red_noise_warning_beta=float(data["red_noise_warning_beta"]),
        forced_period_tolerance_fraction=float(data["forced_period_tolerance_fraction"]),
    )


def science_config_hash(path: Path = CONFIG_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
