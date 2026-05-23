from __future__ import annotations

from dataclasses import asdict
from typing import Any

import numpy as np

from orbitlab.exceptions import ModelArtifactError
from orbitlab.ml.astronet_adapter import build_astronet_tensors
from orbitlab.ml.calibration import attach_probability_calibration
from orbitlab.ml.exomac_service import ExoMACService, build_exomac_features
from orbitlab.ml.nigraha_adapter import build_nigraha_tensors
from orbitlab.ml.nigraha_service import NigrahaService
from orbitlab.ml.service import AstroNetService, KeplerAstroNetService
from orbitlab.science.bls import find_multi_planet_candidates, run_bls
from orbitlab.science.data_quality import clean_light_curve
from orbitlab.science.evidence import build_candidate_evidence, estimate_red_noise_beta
from orbitlab.science.folding import bin_phase_curve, phase_fold
from orbitlab.science.injection_recovery import run_injection_recovery
from orbitlab.science.physics import infer_planet_physics
from orbitlab.science.science_config import (
    config_usage_audit,
    get_search_profile,
    load_science_config,
    science_config_hash,
)
from orbitlab.science.tls_refinement import refine_with_tls
from orbitlab.science.validation import validate_candidate


def _ml_unavailable_payload(mission: str, exc: Exception) -> dict:
    detail = str(exc) or exc.__class__.__name__
    return {
        "probability": None,
        "raw_ml_probability": None,
        "calibrated_ml_probability": None,
        "calibration_source": None,
        "calibration_method": None,
        "calibration_checksum": None,
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
    clean_flux: np.ndarray,
) -> dict:
    finite = np.isfinite(time) & np.isfinite(flux)
    baseline_days = float(np.nanmax(time[finite]) - np.nanmin(time[finite])) if finite.any() else 0.0
    quality_bad = np.zeros(np.asarray(time).shape, dtype=bool)
    if quality is not None:
        q = np.asarray(quality)
        if q.shape == np.asarray(time).shape:
            quality_bad = q != 0
    clean_residuals = np.asarray(clean_flux, dtype=np.float64) - np.nanmedian(clean_flux)
    cadence = np.diff(np.sort(clean_time))
    cadence = cadence[np.isfinite(cadence) & (cadence > 0)]
    expected_cadences = int(np.floor(baseline_days / np.nanmedian(cadence))) + 1 if cadence.size else clean_time.size
    gap_fraction = (
        0.0 if expected_cadences <= 0 else float(np.clip(1.0 - clean_time.size / expected_cadences, 0.0, 1.0))
    )
    return {
        "raw_cadence_count": int(np.asarray(time).size),
        "used_cadence_count": int(clean_time.size),
        "baseline_days": baseline_days,
        "gap_fraction": gap_fraction,
        "quality_flag_fraction": float(np.mean(quality_bad)) if quality_bad.size else 0.0,
        "scatter_ppm": float(np.nanstd(clean_residuals) * 1_000_000),
        "red_noise_beta": estimate_red_noise_beta(clean_residuals),
    }


def _flag(code: str, severity: str, message: str) -> dict:
    return {"code": code, "severity": severity, "message": message}


def _observed_transit_count(time: np.ndarray, candidate) -> int:
    if candidate.period <= 0 or candidate.duration <= 0:
        return 0
    phase_number = np.floor((np.asarray(time) - candidate.epoch) / candidate.period).astype(int)
    phase = ((np.asarray(time) - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period
    in_transit = np.abs(phase) <= 0.5 * candidate.duration
    return int(np.unique(phase_number[in_transit]).size)


def _period_alias_code(candidate, accepted_candidates) -> str | None:
    if candidate.period <= 0:
        return None
    for accepted in accepted_candidates:
        if accepted.period <= 0:
            continue
        ratio = candidate.period / accepted.period
        for harmonic in (0.25, 0.5, 1.0, 2.0, 4.0):
            if abs(ratio - harmonic) <= 0.015:
                return "duplicate_period" if harmonic == 1.0 else "period_harmonic"
    return None


def _stellar_context_for_physics(
    *,
    stellar_radius_solar: float | None,
    stellar_mass_solar: float | None,
    stellar_teff: float | None,
) -> tuple[float, float, float | None, str]:
    radius = stellar_radius_solar if stellar_radius_solar and stellar_radius_solar > 0 else 1.0
    mass = stellar_mass_solar if stellar_mass_solar and stellar_mass_solar > 0 else 1.0
    teff = stellar_teff if stellar_teff and stellar_teff > 0 else 5778.0
    source = "user_supplied" if stellar_radius_solar and stellar_mass_solar else "solar_like_fallback"
    return radius, mass, teff, source


def _apply_habitability_caution(physics: dict[str, Any], physics_source: str) -> dict[str, Any]:
    next_physics = dict(physics)
    if physics_source == "solar_like_fallback":
        next_physics["habitability"] = {
            "status": "insufficient_stellar_data",
            "reason": "stellar parameters are fallback solar values",
        }
        next_physics["is_in_habitable_zone"] = None
        next_physics["is_temperature_habitable"] = None
    else:
        next_physics["habitability"] = {
            "status": "assessed",
            "reason": "stellar parameters were supplied for this run",
        }
    return next_physics


def _structured_flags(candidate, validation: dict, config, support: dict | None = None) -> list[dict]:
    flags: list[dict] = []
    support = support or {}
    effective_snr = float(support.get("effective_snr", candidate.signal_to_noise))
    duration_ratio = candidate.duration / candidate.period if candidate.period else float("inf")
    if effective_snr < config.promotion_snr:
        flags.append(_flag("low_snr", "warning", "Effective signal is below the planet-candidate promotion threshold."))
    if support.get("red_noise_beta", 1.0) >= config.red_noise_warning_beta:
        flags.append(_flag("red_noise", "warning", "Correlated noise reduces the effective transit significance."))
    if support.get("quality_flag_fraction", 0.0) >= config.quality_flag_dominance_fraction:
        flags.append(_flag("quality_flag_dominance", "warning", "Quality-flagged cadences dominate this light curve."))
    if duration_ratio > config.max_duration_period_ratio or not validation.get("duration_plausible", False):
        flags.append(
            _flag("implausible_duration", "hard_fail", "Transit duration is too large for the detected period.")
        )
    observed_transits = support.get("observed_transit_count")
    if isinstance(observed_transits, int) and observed_transits < 2:
        flags.append(
            _flag("single_transit", "hard_fail", "Fewer than two observed transit events support this period.")
        )
    alias_code = support.get("period_alias_code")
    if alias_code == "duplicate_period":
        flags.append(_flag("duplicate_period", "hard_fail", "Period duplicates an already stronger detected signal."))
    elif alias_code == "period_harmonic":
        flags.append(_flag("period_harmonic", "hard_fail", "Period is a simple harmonic of another detected signal."))
    candidate_rank = support.get("candidate_rank")
    primary_snr = support.get("primary_signal_to_noise")
    if (
        isinstance(candidate_rank, int)
        and candidate_rank > 1
        and isinstance(primary_snr, (int, float))
        and np.isfinite(primary_snr)
        and effective_snr < max(config.promotion_snr * 1.25, primary_snr * 0.15)
    ):
        flags.append(
            _flag("weak_residual_signal", "warning", "Residual signal is weak relative to the primary transit.")
        )
    if validation.get("harmonic_flag"):
        flags.append(_flag("stellar_rotation_harmonic", "warning", "Period is close to a stellar rotation harmonic."))
    existing_codes = {flag["code"] for flag in flags}
    for validation_flag in validation.get("false_positive_flags", ()) or ():
        if validation_flag not in existing_codes:
            flags.append(_flag(str(validation_flag), "warning", "Validation marked this signal for follow-up review."))
            existing_codes.add(str(validation_flag))
    secondary_snr = validation.get("secondary_snr")
    secondary_depth = validation.get("secondary_depth")
    if (
        isinstance(secondary_snr, (int, float))
        and np.isfinite(secondary_snr)
        and secondary_snr >= config.secondary_eclipse_hard_fail_snr
    ):
        flags.append(_flag("secondary_eclipse", "hard_fail", "Secondary eclipse SNR exceeds hard-fail threshold."))
    elif (
        isinstance(secondary_depth, (int, float))
        and np.isfinite(secondary_depth)
        and secondary_depth > 0
        and secondary_depth / max(candidate.depth, np.finfo(float).eps) * candidate.signal_to_noise
        >= config.secondary_eclipse_hard_fail_snr
    ):
        flags.append(_flag("secondary_eclipse", "hard_fail", "Secondary eclipse evidence exceeds hard-fail threshold."))
    odd_even_sigma = validation.get("odd_even_sigma")
    if (
        isinstance(odd_even_sigma, (int, float))
        and np.isfinite(odd_even_sigma)
        and odd_even_sigma >= config.odd_even_hard_fail_sigma
    ):
        flags.append(_flag("odd_even_depth_mismatch", "hard_fail", "Odd/even depth mismatch exceeds sigma threshold."))
    centroid_significance = validation.get("centroid_significance")
    if isinstance(centroid_significance, (int, float)) and np.isfinite(centroid_significance):
        if centroid_significance >= 3.0:
            flags.append(_flag("centroid_shift", "hard_fail", "Centroid shift exceeds 3 sigma."))
        elif centroid_significance >= 2.0:
            flags.append(_flag("centroid_shift", "warning", "Centroid shift exceeds 2 sigma."))
    else:
        centroid_shift = validation.get("centroid_shift_pixels")
        if (
            isinstance(centroid_shift, (int, float))
            and np.isfinite(centroid_shift)
            and centroid_shift > config.centroid_hard_fail_pixels
        ):
            flags.append(_flag("centroid_shift", "hard_fail", "Centroid shift exceeds pixel fallback threshold."))
    return flags


def _disposition(
    candidate, flags: list[dict], config, evidence: dict[str, Any] | None = None
) -> tuple[str, str, str, float]:
    has_hard_fail = any(flag["severity"] == "hard_fail" for flag in flags)
    effective_snr = float((evidence or {}).get("effective_snr", candidate.signal_to_noise))
    final_score = float((evidence or {}).get("final_score", min(max(effective_snr / config.promotion_snr, 0.0), 1.0)))
    if has_hard_fail:
        return "rejected_signal", "none", "low", min(final_score, 0.44)
    has_review_warning = any(flag["severity"] == "warning" for flag in flags)
    if final_score >= 0.80 and effective_snr >= 7.1 and not has_review_warning:
        return "planet_candidate", "follow_up_needed", "high", final_score
    if final_score >= 0.65 and effective_snr >= config.promotion_snr and not has_review_warning:
        return "planet_candidate", "follow_up_needed", "high", final_score
    if final_score >= 0.45 and effective_snr >= config.borderline_snr_min:
        return "borderline_tce", "review_needed", "medium", final_score
    if candidate.signal_to_noise >= config.borderline_snr_min:
        return "borderline_tce", "review_needed", "medium", final_score
    return "rejected_signal", "none", "low", final_score


def _resolve_secondary_period_alias(
    time: np.ndarray, flux: np.ndarray, candidate, config, *, min_period: float, max_period: float
):
    validation = asdict(validate_candidate(time, flux, candidate))
    if "secondary_eclipse" not in validation.get("false_positive_flags", ()):
        return candidate
    half_period = candidate.period / 2.0
    if half_period < min_period or half_period > max_period:
        return candidate
    tolerance = config.forced_period_tolerance_fraction
    window_min = max(min_period, half_period * (1.0 - max(0.02, tolerance)))
    window_max = min(max_period, half_period * (1.0 + max(0.02, tolerance)))
    if window_max <= window_min:
        return candidate
    try:
        alias_result = run_bls(
            time, flux, min_period=window_min, max_period=window_max, period_samples=2048, max_period_samples=4096
        )
    except (RuntimeError, ValueError):
        return candidate
    alias = alias_result.candidate
    if alias.signal_to_noise >= config.borderline_snr_min and alias.signal_to_noise >= candidate.signal_to_noise * 0.75:
        return alias
    return candidate


def _ml_payload_for_candidate(
    *,
    mission_upper: str,
    clean_time: np.ndarray,
    clean_flux: np.ndarray,
    candidate,
    physics: dict[str, Any],
    stellar_teff: float | None,
    stellar_radius_solar: float | None,
    stellar_logg: float | None,
    stellar_mass_solar: float | None,
    stellar_luminosity_solar: float | None,
    stellar_density_solar: float | None,
    service: AstroNetService | None,
    tess_service: NigrahaService | None,
    k2_service: ExoMACService | None,
) -> tuple[dict, AstroNetService | None, NigrahaService | None, ExoMACService | None]:
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
        ml = attach_probability_calibration(ml, mission_upper)
    except (ModelArtifactError, KeyError, FileNotFoundError, RuntimeError, ImportError, ValueError) as exc:
        ml = _ml_unavailable_payload(mission_upper, exc)
    return ml, service, tess_service, k2_service


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
    search_profile: str | None = None,
    ml_service: AstroNetService | None = None,
    nigraha_service: NigrahaService | None = None,
    k2_service: ExoMACService | None = None,
) -> dict:
    config = load_science_config()
    profile_name = search_profile or ("science_deep" if vetting_mode == "deep" else "science_standard")
    profile = get_search_profile(config, profile_name)
    clean_time, clean_flux = clean_light_curve(time, flux, quality)
    data_quality = _data_quality_payload(np.asarray(time), np.asarray(flux), quality, clean_time, clean_flux)

    try:
        bls_result = run_bls(
            clean_time,
            clean_flux,
            min_period=profile.min_period,
            max_period=profile.max_period,
            period_samples=profile.period_samples,
            max_period_samples=profile.max_period_samples,
            min_transits=profile.min_transits,
            max_search_cadences=profile.max_search_cadences,
        )
    except TypeError:
        # Some tests monkeypatch run_bls with the old narrow signature.
        bls_result = run_bls(clean_time, clean_flux)
    bls_result.metadata.update(
        {
            "search_profile": profile.name,
            "search_profile_warning": profile.warning,
            "period_samples_requested": profile.period_samples,
        }
    )
    primary = _resolve_secondary_period_alias(
        clean_time,
        clean_flux,
        bls_result.candidate,
        config,
        min_period=bls_result.metadata["min_period_days"],
        max_period=bls_result.metadata["max_period_days"],
    )

    ledger_candidates = find_multi_planet_candidates(
        clean_time,
        clean_flux,
        max_candidates=max_candidates,
        initial_candidate=primary,
        min_period=bls_result.metadata["min_period_days"],
        max_period=bls_result.metadata["max_period_days"],
        period_samples=profile.period_samples,
        max_period_samples=profile.max_period_samples,
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
    promoted_candidates = []
    evaluated_candidates = []
    primary_signal_to_noise = ledger_candidates[0].signal_to_noise if ledger_candidates else 0.0
    tls_results: dict[str, dict] = {}

    for index, candidate in enumerate(ledger_candidates, start=1):
        candidate_id = f"{mission.lower()}-{target_id}-tce-{index}"
        phase, folded_flux = phase_fold(
            bls_result.search_time, bls_result.search_flux, candidate.period, candidate.epoch
        )
        binned_phase, binned_flux = bin_phase_curve(phase, folded_flux, 401)
        folded_curves[candidate_id] = {
            "phase": binned_phase.astype(float).tolist(),
            "flux": binned_flux.astype(float).tolist(),
        }

        physics_radius, physics_mass, physics_teff, physics_source = _stellar_context_for_physics(
            stellar_radius_solar=stellar_radius_solar,
            stellar_mass_solar=stellar_mass_solar,
            stellar_teff=stellar_teff,
        )
        physics = asdict(
            infer_planet_physics(
                depth=candidate.depth,
                period_days=candidate.period,
                stellar_radius_solar=physics_radius,
                stellar_mass_solar=physics_mass,
                stellar_teff=physics_teff,
            )
        )
        physics["stellar_context_source"] = physics_source
        physics = _apply_habitability_caution(physics, physics_source)
        validation = asdict(
            validate_candidate(clean_time, clean_flux, candidate, stellar_rotation_period=stellar_rotation_period)
        )
        observed_transits = _observed_transit_count(bls_result.search_time, candidate)
        period_alias_code = _period_alias_code(candidate, evaluated_candidates)
        alias_flags = [period_alias_code] if period_alias_code else []
        red_noise_beta = estimate_red_noise_beta(
            np.asarray(bls_result.search_flux) - np.nanmedian(bls_result.search_flux)
        )
        effective_snr = candidate.signal_to_noise / red_noise_beta if red_noise_beta else candidate.signal_to_noise
        support = {
            "observed_transit_count": observed_transits,
            "period_alias_code": period_alias_code,
            "candidate_rank": index,
            "primary_signal_to_noise": primary_signal_to_noise,
            "effective_snr": effective_snr,
            "red_noise_beta": red_noise_beta,
            "quality_flag_fraction": data_quality["quality_flag_fraction"],
        }
        flags = _structured_flags(candidate, validation, config, support)
        ml, service, tess_service, k2_service = _ml_payload_for_candidate(
            mission_upper=mission_upper,
            clean_time=clean_time,
            clean_flux=clean_flux,
            candidate=candidate,
            physics=physics,
            stellar_teff=stellar_teff,
            stellar_radius_solar=stellar_radius_solar,
            stellar_logg=stellar_logg,
            stellar_mass_solar=stellar_mass_solar,
            stellar_luminosity_solar=stellar_luminosity_solar,
            stellar_density_solar=stellar_density_solar,
            service=service,
            tess_service=tess_service,
            k2_service=k2_service,
        )
        evidence_obj = build_candidate_evidence(
            candidate=candidate,
            search_time=bls_result.search_time,
            search_flux=bls_result.search_flux,
            validation=validation,
            physics=physics,
            flags=flags,
            ml=ml,
            observed_transits=observed_transits,
            quality_flag_fraction=data_quality["quality_flag_fraction"],
            config=config,
        )
        evidence = asdict(evidence_obj)
        if vetting_mode == "deep":
            tls_results[candidate_id] = refine_with_tls(clean_time, clean_flux, candidate)
            evidence["tls"] = tls_results[candidate_id]
        disposition, action_label, confidence_band, disposition_score = _disposition(candidate, flags, config, evidence)

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
            "duration_hours": candidate.duration * 24.0,
            "depth_fraction": candidate.depth,
            "depth_ppm": candidate.depth * 1_000_000,
            "bls_power": candidate.power,
            "bls_snr": candidate.signal_to_noise,
            "raw_snr": candidate.signal_to_noise,
            "red_noise_beta": evidence["red_noise_beta"],
            "effective_snr": evidence["effective_snr"],
            "sde": candidate.power,
            "local_noise_snr": evidence["effective_snr"],
            "duration_period_ratio": duration_period_ratio,
            "transit_count": observed_transits,
            "phase_coverage_score": evidence["phase_coverage_score"],
            "alias_flags": alias_flags,
            "disposition": disposition,
            "action_label": action_label,
            "disposition_score": disposition_score,
            "final_score": evidence["final_score"],
            "confidence_band": confidence_band,
            "flags": flags,
            "explanation": list(evidence["explanation"]),
            "evidence": evidence,
            "evidence_scores": {
                "detection": evidence["detection_score"],
                "vetting": evidence["vetting_score"],
                "data_quality": evidence["data_quality_score"],
                "centroid": evidence["centroid_score"],
                "physics_plausibility": evidence["physics_plausibility_score"],
                "ml": evidence["ml_score"],
            },
            "detection_metrics": {
                "bls_snr": candidate.signal_to_noise,
                "raw_snr": candidate.signal_to_noise,
                "effective_snr": evidence["effective_snr"],
                "red_noise_beta": evidence["red_noise_beta"],
                "sde": candidate.power,
                "transit_count": observed_transits,
                "observed_transit_count": observed_transits,
                "local_noise_snr": evidence["effective_snr"],
                "duration_period_ratio": duration_period_ratio,
                "phase_coverage_score": evidence["phase_coverage_score"],
                "alias_flags": alias_flags,
                "candidate_rank": index,
                "primary_signal_to_noise": primary_signal_to_noise,
            },
            "aperture_stability": {
                "pipeline_mask": "pipeline",
                "percentiles": list(config.aperture_percentiles),
                "status": "not_computed",
            },
            "vetting": {
                "odd_even": {
                    "depth_delta_fraction": _finite_float(validation.get("odd_even_depth_delta")),
                    "sigma": _finite_float(validation.get("odd_even_sigma")),
                },
                "secondary_eclipse": {
                    "depth_fraction": _finite_float(validation.get("secondary_depth")),
                    "snr": _finite_float(validation.get("secondary_snr")),
                },
                "centroid": {
                    "centroid_shift_pixels": _finite_float(validation.get("centroid_shift_pixels")),
                    "centroid_uncertainty_pixels": _finite_float(validation.get("centroid_uncertainty_pixels")),
                    "centroid_significance": _finite_float(validation.get("centroid_significance")),
                    "centroid_shift_arcsec": None,
                },
                "difference_image": {"status": "unavailable"},
                "quality_cadence_dominance": {
                    "status": "warning"
                    if data_quality["quality_flag_fraction"] >= config.quality_flag_dominance_fraction
                    else "pass",
                    "quality_flag_fraction": data_quality["quality_flag_fraction"],
                    "threshold": config.quality_flag_dominance_fraction,
                },
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
        evaluated_candidates.append(candidate)
        if disposition == "planet_candidate":
            planet_candidate_payloads.append(tce_payload)
            promoted_candidates.append(candidate)

    injection_recovery = {"status": "skipped", "engine": "box_injection_recovery"}
    if vetting_mode == "deep":
        injection_recovery = run_injection_recovery(
            clean_time,
            clean_flux,
            tolerance_fraction=config.forced_period_tolerance_fraction,
        )

    config_audit = config_usage_audit()
    engine_status = {
        "bls": {"status": "complete", "search_profile": profile.name},
        "tls": {"status": "skipped" if vetting_mode == "fast" else ("complete" if tls_results else "unavailable")},
        "injection_recovery": {"status": injection_recovery["status"]},
        "wotan": {"status": "skipped" if vetting_mode == "fast" else "unavailable"},
        "triceratops": {"status": "skipped" if vetting_mode == "fast" else "unavailable"},
        "ml": {"status": "complete" if tce_payloads else "skipped"},
    }
    return {
        "schema_version": "orbitlab.analysis_result.v2",
        "pipeline_version": "orbitlab-stormbreaker-0.2.0",
        "science_config_hash": science_config_hash(),
        **config_audit,
        "target_id": target_id,
        "mission": mission,
        "vetting_mode": vetting_mode,
        "search_profile": profile.name,
        "data_quality": data_quality,
        "tces": tce_payloads,
        "planet_candidates": planet_candidate_payloads,
        "validation_status": "complete",
        "engine_status": engine_status,
        "deep_mode_progress": {
            "mode": vetting_mode,
            "complete": vetting_mode == "fast" or injection_recovery["status"] in {"complete", "skipped"},
            "steps": ["profiled_bls", "tce_ledger", "core_vetting", "evidence_scoring", "ml_calibration"]
            + (["tls_refinement", "injection_recovery"] if vetting_mode == "deep" else []),
        },
        "injection_recovery": injection_recovery,
        "periodogram": {
            "period": bls_result.periodogram["period"].astype(float).tolist(),
            "power": bls_result.periodogram["power"].astype(float).tolist(),
            "duration": bls_result.periodogram["duration"].astype(float).tolist(),
        },
        "folded_curves": folded_curves,
        "light_curve": {"time": clean_time.astype(float).tolist(), "flux": clean_flux.astype(float).tolist()},
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
            "effective_radius_solar": stellar_radius_solar or 1.0,
            "effective_mass_solar": stellar_mass_solar or 1.0,
            "effective_teff": stellar_teff or 5778.0,
            "physics_source": "user_supplied" if stellar_radius_solar and stellar_mass_solar else "solar_like_fallback",
        },
        "preprocessing": bls_result.metadata,
    }
