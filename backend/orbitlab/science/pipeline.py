from __future__ import annotations

from dataclasses import asdict

import numpy as np

from orbitlab.exceptions import ModelArtifactError
from orbitlab.ml.astronet_adapter import build_astronet_tensors
from orbitlab.ml.exomac_service import ExoMACService, build_exomac_features
from orbitlab.ml.nigraha_adapter import build_nigraha_tensors
from orbitlab.ml.nigraha_service import NigrahaService
from orbitlab.ml.service import AstroNetService, KeplerAstroNetService
from orbitlab.science.bls import find_multi_planet_candidates, run_bls
from orbitlab.science.data_quality import clean_light_curve
from orbitlab.science.folding import bin_phase_curve, phase_fold
from orbitlab.science.physics import infer_planet_physics
from orbitlab.science.science_config import load_science_config, science_config_hash
from orbitlab.science.validation import validate_candidate


def _ml_unavailable_payload(mission: str, exc: Exception) -> dict:
    detail = str(exc) or exc.__class__.__name__
    return {
        "probability": None,
        "threshold": None,
        "label": "ml-unavailable",
        "model_version": "unavailable",
        "model_source": f"{mission} model artifact unavailable",
        "input_tensor_checksum": None,
        "preprocessing_compatible": False,
        "citation": "Model artifact unavailable; OrbitLab preserved BLS, physics, and validation outputs.",
        "detail": detail,
    }


def _finite_float(value: float | None) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return float(value)


def _data_quality_payload(
    time: np.ndarray,
    flux: np.ndarray,
    quality: np.ndarray | None,
    clean_time: np.ndarray,
) -> dict:
    finite = np.isfinite(time) & np.isfinite(flux)
    baseline_days = float(np.nanmax(time[finite]) - np.nanmin(time[finite])) if finite.any() else 0.0
    quality_bad = np.zeros(np.asarray(time).shape, dtype=bool)
    if quality is not None:
        q = np.asarray(quality)
        if q.shape == np.asarray(time).shape:
            quality_bad = q != 0
    scatter_ppm = float(np.nanstd(clean_light_curve(time, flux, quality)[1] - 1.0) * 1_000_000)
    return {
        "raw_cadence_count": int(np.asarray(time).size),
        "used_cadence_count": int(clean_time.size),
        "baseline_days": baseline_days,
        "gap_fraction": 0.0,
        "quality_flag_fraction": float(np.mean(quality_bad)) if quality_bad.size else 0.0,
        "scatter_ppm": scatter_ppm,
        "red_noise_beta": 1.0,
    }


def _flag(code: str, severity: str, message: str) -> dict:
    return {"code": code, "severity": severity, "message": message}


def _structured_flags(candidate, validation: dict, config) -> list[dict]:
    flags: list[dict] = []
    duration_ratio = candidate.duration / candidate.period if candidate.period else float("inf")
    if candidate.signal_to_noise < config.promotion_snr:
        flags.append(_flag("low_snr", "warning", "Signal is below the planet-candidate promotion threshold."))
    if duration_ratio > config.max_duration_period_ratio or not validation.get("duration_plausible", False):
        flags.append(
            _flag("implausible_duration", "hard_fail", "Transit duration is too large for the detected period.")
        )
    if validation.get("harmonic_flag"):
        flags.append(_flag("stellar_rotation_harmonic", "warning", "Period is close to a stellar rotation harmonic."))
    secondary_depth = validation.get("secondary_depth")
    if (
        isinstance(secondary_depth, (int, float))
        and np.isfinite(secondary_depth)
        and secondary_depth > 0
        and secondary_depth / max(candidate.depth, np.finfo(float).eps) * candidate.signal_to_noise
        >= config.secondary_eclipse_hard_fail_snr
    ):
        flags.append(_flag("secondary_eclipse", "hard_fail", "Secondary eclipse evidence exceeds hard-fail threshold."))
    odd_even_delta = validation.get("odd_even_depth_delta")
    if (
        isinstance(odd_even_delta, (int, float))
        and np.isfinite(odd_even_delta)
        and candidate.depth > 0
        and odd_even_delta / candidate.depth >= config.odd_even_hard_fail_sigma
    ):
        flags.append(
            _flag("odd_even_depth_mismatch", "hard_fail", "Odd/even depth mismatch exceeds hard-fail threshold.")
        )
    centroid_shift = validation.get("centroid_shift_pixels")
    if (
        isinstance(centroid_shift, (int, float))
        and np.isfinite(centroid_shift)
        and centroid_shift > config.centroid_hard_fail_pixels
    ):
        flags.append(_flag("centroid_shift", "hard_fail", "Centroid shift exceeds hard-fail threshold."))
    return flags


def _disposition(candidate, flags: list[dict], config) -> tuple[str, str, str, float]:
    has_hard_fail = any(flag["severity"] == "hard_fail" for flag in flags)
    if has_hard_fail:
        return "rejected_signal", "none", "low", min(candidate.signal_to_noise / config.promotion_snr, 1.0)
    score = min(max(candidate.signal_to_noise / config.promotion_snr, 0.0), 1.0)
    if candidate.signal_to_noise >= config.promotion_snr:
        return "planet_candidate", "follow_up_needed", "high", score
    if candidate.signal_to_noise >= config.borderline_snr_min:
        return "borderline_tce", "review_needed", "medium", score
    return "rejected_signal", "none", "low", score


def analyze_light_curve_arrays(
    *,
    target_id: str,
    mission: str,
    time: np.ndarray,
    flux: np.ndarray,
    quality: np.ndarray | None = None,
    stellar_radius_solar: float | None = None,
    stellar_mass_solar: float | None = None,
    stellar_teff: float | None = None,
    stellar_logg: float | None = None,
    stellar_luminosity_solar: float | None = None,
    stellar_density_solar: float | None = None,
    stellar_rotation_period: float | None = None,
    max_candidates: int = 4,
    vetting_mode: str = "fast",
    ml_service: AstroNetService | None = None,
    nigraha_service: NigrahaService | None = None,
    k2_service: ExoMACService | None = None,
) -> dict:
    config = load_science_config()
    clean_time, clean_flux = clean_light_curve(time, flux, quality)

    bls_result = run_bls(clean_time, clean_flux)
    primary = bls_result.candidate
    periodogram = bls_result.periodogram

    ledger_candidates = find_multi_planet_candidates(
        clean_time,
        clean_flux,
        max_candidates=max_candidates,
        initial_candidate=primary,
        min_period=bls_result.metadata["min_period_days"],
        max_period=bls_result.metadata["max_period_days"],
        min_signal_to_noise=config.borderline_snr_min,
        preserve_initial_candidate=True,
    )

    folded_curves: dict[str, dict[str, list[float]]] = {}
    tce_payloads = []
    planet_candidate_payloads = []
    mission_upper = mission.upper()
    if mission_upper not in {"TESS", "KEPLER", "K2"}:
        raise ValueError(f"unsupported mission: {mission}")

    service = ml_service
    tess_service = nigraha_service

    for index, candidate in enumerate(ledger_candidates, start=1):
        candidate_id = f"{mission.lower()}-{target_id}-tce-{index}"
        phase, folded_flux = phase_fold(
            bls_result.search_time,
            bls_result.search_flux,
            candidate.period,
            candidate.epoch,
        )
        binned_phase, binned_flux = bin_phase_curve(phase, folded_flux, 401)
        folded_curves[candidate_id] = {
            "phase": binned_phase.astype(float).tolist(),
            "flux": binned_flux.astype(float).tolist(),
        }
        physics = None
        if stellar_radius_solar and stellar_mass_solar:
            physics = asdict(
                infer_planet_physics(
                    depth=candidate.depth,
                    period_days=candidate.period,
                    stellar_radius_solar=stellar_radius_solar,
                    stellar_mass_solar=stellar_mass_solar,
                    stellar_teff=stellar_teff,
                )
            )
        validation = asdict(
            validate_candidate(
                clean_time,
                clean_flux,
                candidate,
                stellar_rotation_period=stellar_rotation_period,
            )
        )
        flags = _structured_flags(candidate, validation, config)
        disposition, action_label, confidence_band, disposition_score = _disposition(candidate, flags, config)

        try:
            if mission_upper == "TESS":
                tensors = build_nigraha_tensors(
                    clean_time,
                    clean_flux,
                    candidate,
                    stellar_teff=stellar_teff,
                    stellar_radius_solar=stellar_radius_solar,
                    stellar_logg=stellar_logg,
                    stellar_mass_solar=stellar_mass_solar,
                    stellar_luminosity_solar=stellar_luminosity_solar,
                    stellar_density_solar=stellar_density_solar,
                )
                if tess_service is None:
                    tess_service = NigrahaService()
                ml = asdict(tess_service.predict(tensors))

            elif mission_upper == "KEPLER":
                tensors = build_astronet_tensors(
                    clean_time,
                    clean_flux,
                    candidate,
                    stellar_radius_solar=stellar_radius_solar,
                    stellar_mass_solar=stellar_mass_solar,
                )
                if service is None:
                    service = KeplerAstroNetService()
                ml = asdict(service.predict(tensors))

            elif mission_upper == "K2":
                exomac_features = build_exomac_features(
                    candidate,
                    stellar_radius_solar=stellar_radius_solar,
                    stellar_mass_solar=stellar_mass_solar,
                    stellar_teff=stellar_teff,
                    stellar_logg=stellar_logg,
                    planet_radius_earth=physics.get("planet_radius_earth") if physics else None,
                    semi_major_axis_au=physics.get("semi_major_axis_au") if physics else None,
                )
                if k2_service is None:
                    k2_service = ExoMACService()
                ml = asdict(k2_service.predict(exomac_features))

            else:
                raise AssertionError(f"unreachable mission branch: {mission_upper}")

        except (ModelArtifactError, KeyError, FileNotFoundError, RuntimeError, ImportError, ValueError) as exc:
            ml = _ml_unavailable_payload(mission_upper, exc)

        duration_period_ratio = candidate.duration / candidate.period if candidate.period else None
        tce_payload = {
            "candidate_id": candidate_id,
            "tce_id": candidate_id,
            "period": candidate.period,
            "epoch": candidate.epoch,
            "duration": candidate.duration,
            "depth": candidate.depth,
            "signal_to_noise": candidate.signal_to_noise,
            "period_days": candidate.period,
            "epoch_days": candidate.epoch,
            "duration_days": candidate.duration,
            "depth_fraction": candidate.depth,
            "depth_ppm": candidate.depth * 1_000_000,
            "bls_power": candidate.power,
            "bls_snr": candidate.signal_to_noise,
            "sde": candidate.power,
            "local_noise_snr": candidate.signal_to_noise,
            "duration_period_ratio": duration_period_ratio,
            "transit_count": int(np.floor((np.nanmax(clean_time) - np.nanmin(clean_time)) / candidate.period))
            if candidate.period > 0
            else 0,
            "alias_flags": [],
            "disposition": disposition,
            "action_label": action_label,
            "disposition_score": disposition_score,
            "confidence_band": confidence_band,
            "flags": flags,
            "detection_metrics": {
                "bls_snr": candidate.signal_to_noise,
                "sde": candidate.power,
                "transit_count": int(np.floor((np.nanmax(clean_time) - np.nanmin(clean_time)) / candidate.period))
                if candidate.period > 0
                else 0,
                "local_noise_snr": candidate.signal_to_noise,
                "duration_period_ratio": duration_period_ratio,
                "alias_flags": [],
            },
            "aperture_stability": {
                "pipeline_mask": "pipeline",
                "percentiles": list(config.aperture_percentiles),
                "status": "not_computed",
            },
            "vetting": {
                "odd_even": {"depth_delta_fraction": _finite_float(validation.get("odd_even_depth_delta"))},
                "secondary_eclipse": {"depth_fraction": _finite_float(validation.get("secondary_depth"))},
                "centroid": {
                    "centroid_shift_pixels": _finite_float(validation.get("centroid_shift_pixels")),
                    "centroid_shift_arcsec": None,
                },
                "difference_image": {"status": "unavailable"},
                "quality_cadence_dominance": {"status": "not_computed"},
            },
            "catalog_context": {
                "tic": target_id if mission_upper == "TESS" else None,
                "gaia": {"status": "unavailable"},
                "exofop_toi": {"status": "unavailable"},
                "nasa_exoplanet_archive": {"status": "unavailable"},
                "eb_catalog": {"status": "unavailable"},
            },
            "fpp": {"status": "skipped" if vetting_mode == "fast" else "unavailable", "engine": "triceratops"},
            "physics": physics,
            "validation": validation,
            "ml": ml,
        }
        tce_payloads.append(tce_payload)
        if disposition == "planet_candidate":
            planet_candidate_payloads.append(tce_payload)

    return {
        "schema_version": "orbitlab.analysis_result.v2",
        "pipeline_version": "orbitlab-tce-vetting-0.1.0",
        "science_config_hash": science_config_hash(),
        "target_id": target_id,
        "mission": mission,
        "vetting_mode": vetting_mode,
        "data_quality": _data_quality_payload(np.asarray(time), np.asarray(flux), quality, clean_time),
        "tces": tce_payloads,
        "planet_candidates": planet_candidate_payloads,
        "validation_status": "complete",
        "engine_status": {
            "bls": {"status": "complete"},
            "tls": {"status": "skipped" if vetting_mode == "fast" else "unavailable"},
            "wotan": {"status": "skipped" if vetting_mode == "fast" else "unavailable"},
            "triceratops": {"status": "skipped" if vetting_mode == "fast" else "unavailable"},
            "ml": {"status": "complete" if tce_payloads else "skipped"},
        },
        "deep_mode_progress": {
            "mode": vetting_mode,
            "complete": vetting_mode == "fast",
            "steps": ["fast_bls", "tce_ledger", "core_vetting", "ml_diagnostic"],
        },
        "periodogram": {
            "period": periodogram["period"].astype(float).tolist(),
            "power": periodogram["power"].astype(float).tolist(),
            "duration": periodogram["duration"].astype(float).tolist(),
        },
        "folded_curves": folded_curves,
        "light_curve": {
            "time": clean_time.astype(float).tolist(),
            "flux": clean_flux.astype(float).tolist(),
        },
        "bls_light_curve": {
            "time": bls_result.search_time.astype(float).tolist(),
            "flux": bls_result.search_flux.astype(float).tolist(),
        },
        "stellar_context": {
            "radius_solar": stellar_radius_solar,
            "mass_solar": stellar_mass_solar,
            "teff": stellar_teff,
            "logg": stellar_logg,
            "luminosity_solar": stellar_luminosity_solar,
            "density_solar": stellar_density_solar,
            "rotation_period": stellar_rotation_period,
        },
        "preprocessing": bls_result.metadata,
    }
