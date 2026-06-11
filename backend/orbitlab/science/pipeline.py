from __future__ import annotations

from dataclasses import asdict, is_dataclass, replace
from typing import Any

import numpy as np

from orbitlab.exceptions import ModelArtifactError
from orbitlab.ml.astronet_adapter import build_astronet_tensors
from orbitlab.ml.calibration import attach_probability_calibration
from orbitlab.ml.exomac_service import ExoMACService, build_exomac_features
from orbitlab.ml.nigraha_adapter import build_nigraha_tensors
from orbitlab.ml.nigraha_service import NigrahaService
from orbitlab.ml.service import AstroNetService, KeplerAstroNetService
from orbitlab.science.bls import TransitCandidate, find_multi_planet_candidates, run_bls
from orbitlab.science.catalog_context import query_tic_catalog_context, query_tic_stellar_context
from orbitlab.science.data_quality import clean_light_curve
from orbitlab.science.dave_vetting import run_model_shift, run_sweet_test
from orbitlab.science.detrending import detrend_with_wotan
from orbitlab.science.detrending_sensitivity import run_detrending_sensitivity
from orbitlab.science.evidence import build_candidate_evidence, estimate_red_noise_beta, out_of_transit_residuals
from orbitlab.science.folding import bin_phase_curve, phase_fold
from orbitlab.science.injection_recovery import run_injection_recovery
from orbitlab.science.known_targets import (
    KnownPlanetPrior,
    KnownTarget,
    known_target_payload,
    match_known_planet,
    resolve_known_target,
)
from orbitlab.science.mission_prf import load_kepler_prf_kernel, load_tess_prf_kernel
from orbitlab.science.physics import infer_planet_physics
from orbitlab.science.science_config import (
    config_usage_audit,
    get_search_profile,
    load_science_config,
    science_config_hash,
)
from orbitlab.science.sde_calibration import calibrated_sde_threshold
from orbitlab.science.sector_consistency import SectorObservation, infer_sector_id, summarize_sector_consistency
from orbitlab.science.tls_refinement import refine_with_tls, search_with_tls
from orbitlab.science.tpf_diagnostics import aperture_stability_diagnostics, difference_image_diagnostics
from orbitlab.science.triceratops_fpp import run_triceratops_fpp
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


_FLAG_SEVERITY_RANK = {"info": 0, "warning": 1, "hard_fail": 2}


def _add_flag(flags: list[dict], code: str, severity: str, message: str) -> None:
    for flag in flags:
        if flag["code"] != code:
            continue
        if _FLAG_SEVERITY_RANK.get(severity, 0) > _FLAG_SEVERITY_RANK.get(flag["severity"], 0):
            flag["severity"] = severity
            flag["message"] = message
        return
    flags.append(_flag(code, severity, message))


def _observed_transit_count(time: np.ndarray, candidate) -> int:
    if candidate.period <= 0 or candidate.duration <= 0:
        return 0
    # Nearest-integer event numbering: floor() splits an epoch-centered
    # event across two transit numbers and overcounts observed transits.
    phase_number = np.round((np.asarray(time) - candidate.epoch) / candidate.period).astype(int)
    phase = ((np.asarray(time) - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period
    in_transit = np.abs(phase) <= 0.5 * candidate.duration
    return int(np.unique(phase_number[in_transit]).size)


def _supported_transit_count(
    time: np.ndarray,
    flux: np.ndarray,
    candidate,
    *,
    min_depth_fraction: float,
) -> int:
    """Count distinct events whose measured median depth supports the period."""
    if candidate.period <= 0 or candidate.duration <= 0 or candidate.depth <= 0:
        return 0
    time_arr = np.asarray(time)
    flux_arr = np.asarray(flux)
    finite = np.isfinite(time_arr) & np.isfinite(flux_arr)
    time_arr = time_arr[finite]
    flux_arr = flux_arr[finite]
    phase_number = np.round((time_arr - candidate.epoch) / candidate.period).astype(int)
    phase = ((time_arr - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period
    in_transit = np.abs(phase) <= 0.5 * candidate.duration
    out_of_transit = np.abs(phase) >= candidate.duration
    baseline = (
        float(np.nanmedian(flux_arr[out_of_transit])) if np.any(out_of_transit) else float(np.nanmedian(flux_arr))
    )
    minimum_depth = candidate.depth * min_depth_fraction
    return sum(
        baseline - float(np.nanmedian(flux_arr[in_transit & (phase_number == event)])) >= minimum_depth
        for event in np.unique(phase_number[in_transit])
    )


def _vetting_arrays_for_candidate(
    time: np.ndarray,
    flux: np.ndarray,
    candidate,
    ledger_candidates,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Remove sibling TCEs' in-transit cadences before per-TCE vetting.

    Kepler/TESS DV vets each TCE on a light curve with the other detected
    signals removed. Without this, a sibling planet's transits read as a
    "significant secondary" in ModShift and as secondary/odd-even structure
    in validation, falsely rejecting real members of multi-planet systems
    (live: L 98-59 d was rejected on dave_sig_sec_in_model_shift because
    planet c's transits were still in its vetting flux).

    Returns (time, flux, masked_sibling_count). Falls back to the unmasked
    arrays when masking would gut the candidate's own in-transit coverage
    (commensurate periods / overlapping windows).
    """
    time_arr = np.asarray(time)
    flux_arr = np.asarray(flux)
    keep = np.ones(time_arr.shape, dtype=bool)
    masked = 0
    for other in ledger_candidates:
        if other is candidate or other.period <= 0 or other.duration <= 0:
            continue
        other_phase = ((time_arr - other.epoch + 0.5 * other.period) % other.period) - 0.5 * other.period
        window = np.abs(other_phase) <= other.duration
        if np.any(window):
            keep &= ~window
            masked += 1
    if masked == 0:
        return time_arr, flux_arr, 0
    if candidate.period > 0 and candidate.duration > 0:
        own_phase = ((time_arr - candidate.epoch + 0.5 * candidate.period) % candidate.period) - (
            0.5 * candidate.period
        )
        own_in_transit = np.abs(own_phase) <= 0.5 * candidate.duration
        before = int(np.count_nonzero(own_in_transit))
        after = int(np.count_nonzero(own_in_transit & keep))
        if before > 0 and (after < 6 or after < 0.5 * before):
            return time_arr, flux_arr, 0
    return time_arr[keep], flux_arr[keep], masked


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


def _candidate_with_metadata(candidate, **metadata):
    next_metadata = dict(candidate.metadata or {})
    next_metadata.update({key: value for key, value in metadata.items() if value is not None})
    return replace(candidate, metadata=next_metadata)


def _tls_primary_candidate(tls: dict[str, Any]) -> TransitCandidate:
    if tls.get("status") != "complete":
        raise RuntimeError(f"TLS-primary paper-grade search did not complete: {tls.get('detail') or tls.get('status')}")
    period = _finite_float(tls.get("period_days"))
    epoch = _finite_float(tls.get("epoch_days"))
    duration = _finite_float(tls.get("duration_days"))
    depth = _finite_float(tls.get("depth_fraction"))
    snr = _finite_float(tls.get("snr"))
    if period is None or epoch is None or duration is None or depth is None:
        raise RuntimeError("TLS-primary paper-grade search did not return period, epoch, duration, and depth")
    return TransitCandidate(
        period=period,
        epoch=epoch,
        duration=duration,
        depth=max(depth, 0.0),
        power=float(tls.get("sde") or tls.get("sde_raw") or snr or 0.0),
        signal_to_noise=float(snr or tls.get("sde") or 0.0),
        metadata={
            "period_source": "tls_full_search",
            "signal_origin": "tls_primary_search",
            "is_residual": False,
            "display_priority": 0,
            "depth_source": tls.get("depth_source"),
            "model_depth_fraction": tls.get("model_depth_fraction"),
            "measured_depth_fraction": tls.get("measured_depth_fraction"),
        },
    )


def _known_planet_payload(
    target: KnownTarget | None, planet: KnownPlanetPrior | None, candidate
) -> dict[str, Any] | None:
    if target is None or planet is None:
        return None
    return {
        "target": target.canonical_name,
        "planet": planet.name,
        "period_days": planet.period_days,
        "period_delta_fraction": abs(candidate.period - planet.period_days) / planet.period_days,
        "allow_planetary_secondary": planet.allow_planetary_secondary,
    }


def _cadence_days_from_time(time: np.ndarray) -> float:
    ordered = np.sort(np.asarray(time, dtype=np.float64))
    diffs = np.diff(ordered)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if diffs.size == 0:
        return 0.020833333333333332
    return float(np.nanmedian(diffs))


def _duration_grid_for_prior(time: np.ndarray, planet: KnownPlanetPrior) -> np.ndarray | None:
    if planet.expected_duration_days is None:
        return None
    cadence_days = _cadence_days_from_time(time)
    center = max(planet.expected_duration_days, 2.0 * cadence_days, 0.005)
    low = max(2.0 * cadence_days, center * 0.55, 0.005)
    high = max(low * 1.2, center * 1.8)
    return np.unique(np.geomspace(low, high, 8).astype(np.float64))


def _guided_known_candidates(
    clean_time: np.ndarray,
    clean_flux: np.ndarray,
    known_target: KnownTarget | None,
    config,
    profile,
    bls_runner=None,
):
    if known_target is None:
        return []
    bls_runner = bls_runner or run_bls

    candidates = []
    for planet in known_target.planets:
        tolerance = max(config.forced_period_tolerance_fraction, planet.period_tolerance_fraction)
        window_min = max(profile.min_period, planet.period_days * (1.0 - tolerance))
        window_max = min(profile.max_period, planet.period_days * (1.0 + tolerance))
        if window_max <= window_min:
            continue
        try:
            result = bls_runner(
                clean_time,
                clean_flux,
                min_period=window_min,
                max_period=window_max,
                duration_grid=_duration_grid_for_prior(clean_time, planet),
                period_samples=min(profile.period_samples, 4096),
                max_period_samples=min(profile.max_period_samples, 4096),
                min_transits=profile.min_transits,
                max_search_cadences=profile.max_search_cadences,
            )
        except (RuntimeError, ValueError):
            continue

        candidate = result.candidate
        matched_planet = match_known_planet(known_target, candidate.period) or planet
        candidates.append(
            _candidate_with_metadata(
                candidate,
                period_source="known_ephemeris",
                signal_origin="guided_known_period",
                catalog_match=_known_planet_payload(known_target, matched_planet, candidate),
                known_period_low_snr=candidate.signal_to_noise < config.borderline_snr_min,
                is_residual=False,
                display_priority=0,
            )
        )

    return sorted(candidates, key=lambda item: item.signal_to_noise, reverse=True)


def _candidate_duplicate(candidate, existing, *, tolerance_fraction: float = 0.015) -> bool:
    if candidate.period <= 0:
        return False
    for other in existing:
        if other.period <= 0:
            continue
        if abs(candidate.period - other.period) / other.period <= tolerance_fraction:
            return True
    return False


def _annotate_ledger_candidates(candidates, known_target: KnownTarget | None):
    annotated = []
    for index, candidate in enumerate(candidates, start=1):
        metadata = dict(candidate.metadata or {})
        known_planet = match_known_planet(known_target, candidate.period)
        if known_planet and not metadata.get("catalog_match"):
            metadata["catalog_match"] = _known_planet_payload(known_target, known_planet, candidate)
        if "is_residual" not in metadata:
            metadata["is_residual"] = index > 1
        if "period_source" not in metadata:
            metadata["period_source"] = "residual_bls" if metadata["is_residual"] else "blind_bls"
        if "signal_origin" not in metadata:
            metadata["signal_origin"] = "residual_search" if metadata["is_residual"] else "broad_periodogram"
        if "display_priority" not in metadata:
            metadata["display_priority"] = 20 if metadata["is_residual"] else 10
        annotated.append(replace(candidate, metadata=metadata))
    return annotated


def _select_primary_candidate(
    clean_time: np.ndarray,
    clean_flux: np.ndarray,
    known_target: KnownTarget | None,
    config,
    profile,
    bls_runner=None,
):
    bls_runner = bls_runner or run_bls
    guided_candidates = _guided_known_candidates(
        clean_time, clean_flux, known_target, config, profile, bls_runner=bls_runner
    )
    bls_result = bls_runner(
        clean_time,
        clean_flux,
        min_period=profile.min_period,
        max_period=profile.max_period,
        period_samples=profile.period_samples,
        max_period_samples=profile.max_period_samples,
        min_transits=profile.min_transits,
        max_search_cadences=profile.max_search_cadences,
    )
    bls_result.metadata.update(
        {
            "guided_known_candidates": len(guided_candidates),
            "known_target": known_target_payload(known_target),
        }
    )
    blind_candidate = _resolve_secondary_period_alias(
        clean_time,
        clean_flux,
        bls_result.candidate,
        config,
        min_period=bls_result.metadata["min_period_days"],
        max_period=bls_result.metadata["max_period_days"],
    )
    known_planet = match_known_planet(known_target, blind_candidate.period)
    blind_candidate = _candidate_with_metadata(
        blind_candidate,
        period_source="blind_bls",
        signal_origin="broad_periodogram",
        catalog_match=_known_planet_payload(known_target, known_planet, blind_candidate),
        is_residual=False,
        display_priority=10,
    )
    primary = guided_candidates[0] if guided_candidates else blind_candidate
    return primary, bls_result, guided_candidates


def _positive(value: float | None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) and number > 0 else None


def _effective_stellar_context(
    *,
    job_stellar: dict[str, float | None],
    known_target: KnownTarget | None,
    catalog_stellar: dict[str, Any] | None,
) -> tuple[dict[str, float | None], dict[str, str]]:
    """Merge stellar parameters from the highest-trust available source.

    Priority per field: (1) the analysis-job value (an explicit user override),
    (2) the curated ``known_targets`` entry when the target resolves to one, and
    (3) the live TIC catalog row. Solar defaults are NOT applied here; that
    imputation stays inside ``build_nigraha_tensors`` so its ``imputed_features``
    list keeps reporting honestly. Returns the merged values plus a per-field
    provenance map so the report can show where each scalar came from.
    """
    fields = ("teff", "radius_solar", "logg", "mass_solar", "luminosity_solar", "density_solar")
    known_map: dict[str, float | None] = {}
    if known_target is not None:
        known_map = {
            "teff": getattr(known_target, "stellar_teff", None),
            "radius_solar": getattr(known_target, "stellar_radius_solar", None),
            "mass_solar": getattr(known_target, "stellar_mass_solar", None),
        }
    catalog_map = catalog_stellar or {}
    merged: dict[str, float | None] = {}
    provenance: dict[str, str] = {}
    for field in fields:
        job_value = _positive(job_stellar.get(field))
        if job_value is not None:
            merged[field] = job_value
            provenance[field] = "job_request"
            continue
        known_value = _positive(known_map.get(field))
        if known_value is not None:
            merged[field] = known_value
            provenance[field] = "known_target"
            continue
        catalog_value = _positive(catalog_map.get(field))
        if catalog_value is not None:
            merged[field] = catalog_value
            # Honour an explicit source hint from the catalog context (e.g.
            # density_solar derived from mass/radius rather than a direct
            # catalog measurement).
            source_hint = catalog_map.get(f"{field}_source")
            provenance[field] = source_hint if isinstance(source_hint, str) else "tic_catalog"
            continue
        merged[field] = None
        provenance[field] = "imputed_solar_default"
    return merged, provenance


_PERIOD_FLOOR_DAYS = 0.05
_PERIOD_CEILING_DAYS = 120.0


def _apply_request_period_window(
    profile,
    *,
    request_min_period: float | None,
    request_max_period: float | None,
) -> tuple[Any, dict[str, Any]]:
    """Honor the analysis request's period bounds against the active profile.

    The user may *narrow* the search window or *extend* it within safe absolute
    bounds (period floor/ceiling). Grid size stays bounded by the profile's
    ``max_period_samples`` regardless of the window, so widening the window never
    explodes runtime. When no request bounds are given, the profile is returned
    unchanged. Returns the (possibly replaced) profile and a provenance dict that
    records what was requested, applied, and why.
    """
    req_min = _positive(request_min_period)
    req_max = _positive(request_max_period)
    request = {
        "requested_min_period_days": req_min,
        "requested_max_period_days": req_max,
        "profile_min_period_days": profile.min_period,
        "profile_max_period_days": profile.max_period,
        "honored": False,
        "clamped": False,
    }
    if req_min is None and req_max is None:
        request["effective_min_period_days"] = profile.min_period
        request["effective_max_period_days"] = profile.max_period
        return profile, request

    effective_min = req_min if req_min is not None else profile.min_period
    effective_max = req_max if req_max is not None else profile.max_period

    clamped = False
    if effective_min < _PERIOD_FLOOR_DAYS:
        effective_min = _PERIOD_FLOOR_DAYS
        clamped = True
    if effective_max > _PERIOD_CEILING_DAYS:
        effective_max = _PERIOD_CEILING_DAYS
        clamped = True
    if effective_min >= effective_max:
        # Incoherent request after clamping: fall back to the profile window.
        request["effective_min_period_days"] = profile.min_period
        request["effective_max_period_days"] = profile.max_period
        request["honored"] = False
        request["clamped"] = clamped
        request["detail"] = "request period window collapsed after clamping; profile window retained"
        return profile, request

    request["effective_min_period_days"] = effective_min
    request["effective_max_period_days"] = effective_max
    request["honored"] = True
    request["clamped"] = clamped
    return replace(profile, min_period=effective_min, max_period=effective_max), request


def _baseline_period_note(
    *,
    baseline_days: float,
    max_period: float,
    min_transits: float,
) -> dict[str, Any] | None:
    """Explain when the searched long-period end cannot yield enough transits.

    A periodic transit needs the observed baseline to span at least
    ``min_transits`` cycles. When ``max_period`` exceeds
    ``baseline_days / min_transits`` the long-period end of the search is
    physically unrecoverable from this data span (e.g. a single-sector TESS
    light curve cannot confirm a 37-day planet). Surfaced as an honest
    diagnostic rather than a silent rejection.
    """
    if not (np.isfinite(baseline_days) and baseline_days > 0):
        return None
    if not (np.isfinite(min_transits) and min_transits > 0):
        return None
    recoverable_max = baseline_days / min_transits
    if max_period <= recoverable_max:
        return None
    return {
        "status": "baseline_limited",
        "baseline_days": float(baseline_days),
        "min_transits_required": float(min_transits),
        "searched_max_period_days": float(max_period),
        "max_recoverable_period_days": float(recoverable_max),
        "note": (
            f"Searched max period {float(max_period):.2f} d exceeds the {float(recoverable_max):.2f} d that this "
            f"{float(baseline_days):.2f} d baseline can yield with >= {float(min_transits):g} transits; long-period "
            f"candidates beyond {float(recoverable_max):.2f} d are not recoverable from this data span "
            "and need a longer (e.g. multi-sector) baseline."
        ),
    }


def _stellar_context_for_physics(
    *,
    stellar_radius_solar: float | None,
    stellar_mass_solar: float | None,
    stellar_teff: float | None,
    provenance: dict[str, str] | None = None,
) -> tuple[float, float, float | None, str]:
    radius = stellar_radius_solar if stellar_radius_solar and stellar_radius_solar > 0 else 1.0
    mass = stellar_mass_solar if stellar_mass_solar and stellar_mass_solar > 0 else 1.0
    teff = stellar_teff if stellar_teff and stellar_teff > 0 else 5778.0
    if not (stellar_radius_solar and stellar_mass_solar):
        return radius, mass, teff, "solar_like_fallback"
    if provenance:
        # Label the dominant origin of the radius/mass pair so habitability
        # caution and evidence scoring can trust real catalog/curated context
        # the same way they trust an explicit user value.
        sources = {provenance.get("radius_solar"), provenance.get("mass_solar")}
        sources.discard(None)
        sources.discard("imputed_solar_default")
        if len(sources) == 1:
            return radius, mass, teff, str(sources.pop())
        if sources:
            return radius, mass, teff, "merged_sources"
    return radius, mass, teff, "user_supplied"


def _apply_habitability_caution(physics: dict[str, Any], physics_source: str) -> dict[str, Any]:
    next_physics = dict(physics)
    if physics_source == "solar_like_fallback":
        next_physics["habitability"] = {
            "status": "insufficient_stellar_data",
            "reason": "stellar parameters are fallback solar values",
        }
        next_physics["interpretation_locked"] = True
        next_physics["locked_reason"] = "stellar_parentage_unknown"
        next_physics["locked_fields"] = [
            "planet_radius_earth",
            "semi_major_axis_au",
            "equilibrium_temperature_k",
            "kopparapu_hz",
        ]
        next_physics["trust_message"] = (
            "Physical properties use solar fallback values and are locked for interpretation until stellar "
            "radius, mass, and temperature are verified."
        )
        next_physics["is_in_habitable_zone"] = None
        next_physics["is_temperature_habitable"] = None
    else:
        next_physics["habitability"] = {
            "status": "assessed",
            "reason": "stellar parameters were supplied for this run",
        }
        next_physics["interpretation_locked"] = False
        next_physics["locked_reason"] = None
        next_physics["locked_fields"] = []
        next_physics["trust_message"] = "Physical properties use supplied stellar context."
    return next_physics


def _candidate_science_readiness(
    *,
    result_kind: str,
    vetting_mode: str,
    flags: list[dict],
    physics: dict[str, Any],
    paper_grade: dict[str, Any] | None,
    fpp: dict[str, Any] | None,
    sector_consistency: dict[str, Any] | None,
    detrending_sensitivity: dict[str, Any] | None,
    ml: dict[str, Any] | None,
) -> dict[str, Any]:
    gaps: list[str] = []
    blockers: list[str] = []
    warnings: list[str] = []

    if result_kind == "preview":
        gaps.extend([
            "paper_grade_tls_not_run",
            "dave_modshift_not_run",
            "triceratops_not_run",
            "ml_not_run",
            "catalog_contamination_not_run",
        ])
        warnings.append("preview_is_detection_only")

    for flag in flags:
        code = str(flag.get("code", "unknown"))
        severity = flag.get("severity")
        if severity == "hard_fail":
            blockers.append(code)
        elif severity == "warning":
            warnings.append(code)

    if physics.get("interpretation_locked"):
        # Unknown stellar parentage locks the physics interpretation fields
        # (radius, semi-major axis, HZ), but the transit detection itself is
        # flux-relative evidence: keep the signal promotable and reviewable
        # instead of vetoing candidacy on missing host-star characterization.
        warnings.append("stellar_context_unverified")

    if vetting_mode == "paper":
        if not paper_grade or paper_grade.get("status") != "pass":
            blockers.append("paper_grade_not_passed")
        if fpp and fpp.get("status") not in {"complete", "skipped"}:
            blockers.append("fpp_incomplete")

    sector_status = (sector_consistency or {}).get("multi_sector_status")
    if sector_status in {"single_sector_only", "insufficient_data"}:
        warnings.append(str(sector_status))
    elif sector_status == "inconsistent":
        blockers.append("sector_inconsistent")

    detrending_status = (detrending_sensitivity or {}).get("status")
    if detrending_status == "unstable_result":
        blockers.append("detrending_unstable")
    elif detrending_status in {"failed", "inconclusive"}:
        warnings.append(f"detrending_{detrending_status}")

    ml_conflicts = (ml or {}).get("evidence_conflicts")
    if isinstance(ml_conflicts, dict) and ml_conflicts.get("status") == "inconclusive":
        conflicts = ml_conflicts.get("conflicts") or []
        warnings.extend(str(conflict) for conflict in conflicts)

    unique_blockers = sorted(set(blockers))
    unique_warnings = sorted(set(warnings))
    unique_gaps = sorted(set(gaps))
    if unique_blockers:
        status = "blocked"
    elif unique_warnings or unique_gaps:
        status = "review"
    else:
        status = "ready"
    return {
        "status": status,
        "result_kind": result_kind,
        "vetting_mode": vetting_mode,
        "blockers": unique_blockers,
        "warnings": unique_warnings,
        "evidence_gaps": unique_gaps,
        "interpretation": (
            "Do not present as a planet candidate until blockers are cleared."
            if unique_blockers
            else "Review warnings and missing evidence before follow-up claims."
            if status == "review"
            else "Evidence gates passed for the selected mode; still not a confirmed planet."
        ),
    }


def _summarize_science_readiness(tces: list[dict], *, result_kind: str, vetting_mode: str) -> dict[str, Any]:
    statuses = [tce.get("science_readiness", {}).get("status") for tce in tces]
    blockers = sorted({
        blocker
        for tce in tces
        for blocker in tce.get("science_readiness", {}).get("blockers", [])
    })
    warnings = sorted({
        warning
        for tce in tces
        for warning in tce.get("science_readiness", {}).get("warnings", [])
    })
    gaps = sorted({
        gap
        for tce in tces
        for gap in tce.get("science_readiness", {}).get("evidence_gaps", [])
    })
    if any(status == "blocked" for status in statuses):
        status = "blocked"
    elif any(status == "review" for status in statuses) or gaps:
        status = "review"
    elif statuses:
        status = "ready"
    else:
        status = "no_signal"
    return {
        "status": status,
        "result_kind": result_kind,
        "vetting_mode": vetting_mode,
        "tce_count": len(tces),
        "blockers": blockers,
        "warnings": warnings,
        "evidence_gaps": gaps,
    }


def _structured_flags(candidate, validation: dict, config, support: dict | None = None) -> list[dict]:
    flags: list[dict] = []
    support = support or {}
    effective_snr = float(support.get("effective_snr", candidate.signal_to_noise))
    duration_ratio = candidate.duration / candidate.period if candidate.period else float("inf")
    if effective_snr < config.promotion_snr:
        _add_flag(flags, "low_snr", "warning", "Effective signal is below the planet-candidate promotion threshold.")
    if support.get("red_noise_beta", 1.0) >= config.red_noise_warning_beta:
        _add_flag(flags, "red_noise", "warning", "Correlated noise reduces the effective transit significance.")
    if support.get("quality_flag_fraction", 0.0) >= config.quality_flag_dominance_fraction:
        _add_flag(
            flags,
            "quality_flag_dominance",
            "warning",
            "Quality-flagged cadences dominate this light curve.",
        )
    if duration_ratio > config.max_duration_period_ratio or not validation.get("duration_plausible", False):
        _add_flag(flags, "implausible_duration", "hard_fail", "Transit duration is too large for the detected period.")
    observed_transits = support.get("observed_transit_count")
    if isinstance(observed_transits, int) and observed_transits < 2:
        _add_flag(flags, "single_transit", "hard_fail", "Fewer than two observed transit events support this period.")
    alias_code = support.get("period_alias_code")
    if alias_code == "duplicate_period":
        _add_flag(flags, "duplicate_period", "hard_fail", "Period duplicates an already stronger detected signal.")
    elif alias_code == "period_harmonic":
        _add_flag(flags, "period_harmonic", "hard_fail", "Period is a simple harmonic of another detected signal.")
    candidate_rank = support.get("candidate_rank")
    primary_snr = support.get("primary_signal_to_noise")
    is_residual = bool(support.get("is_residual"))
    known_planet = support.get("known_planet") if isinstance(support.get("known_planet"), dict) else None
    if known_planet and effective_snr < config.borderline_snr_min:
        _add_flag(
            flags,
            "known_period_low_snr",
            "warning",
            "Known planet period was searched, but this product does not show enough signal for promotion.",
        )
    if is_residual and not known_planet and effective_snr < config.promotion_snr * 1.1:
        _add_flag(
            flags,
            "weak_residual_signal",
            "hard_fail",
            "Residual BLS peak is too weak to display as an independent planet candidate.",
        )
    elif (
        isinstance(candidate_rank, int)
        and candidate_rank > 1
        and isinstance(primary_snr, (int, float))
        and np.isfinite(primary_snr)
        and effective_snr < max(config.promotion_snr * 1.1, primary_snr * 0.75)
    ):
        _add_flag(flags, "weak_residual_signal", "warning", "Residual signal is weak relative to the primary transit.")
    if validation.get("harmonic_flag"):
        _add_flag(flags, "stellar_rotation_harmonic", "warning", "Period is close to a stellar rotation harmonic.")
    secondary_snr = validation.get("secondary_snr")
    secondary_depth = validation.get("secondary_depth")
    secondary_depth_ratio = (
        float(secondary_depth) / max(candidate.depth, np.finfo(float).eps)
        if isinstance(secondary_depth, (int, float)) and np.isfinite(secondary_depth) and secondary_depth > 0
        else 0.0
    )
    secondary_snr_hard = (
        isinstance(secondary_snr, (int, float))
        and np.isfinite(secondary_snr)
        and secondary_snr >= config.secondary_eclipse_hard_fail_snr
    )
    secondary_depth_hard = secondary_depth_ratio * candidate.signal_to_noise >= config.secondary_eclipse_hard_fail_snr
    planetary_secondary_allowed = bool(support.get("planetary_secondary_allowed"))
    binary_like_secondary = secondary_depth_ratio >= 0.75
    if secondary_snr_hard or secondary_depth_hard:
        if planetary_secondary_allowed and not binary_like_secondary:
            _add_flag(
                flags,
                "planetary_secondary",
                "warning",
                "Known hot-planet secondary signal is present; review occultation evidence before promotion.",
            )
        else:
            _add_flag(
                flags, "secondary_eclipse", "hard_fail", "Secondary eclipse evidence exceeds hard-fail threshold."
            )
    odd_even_sigma = validation.get("odd_even_sigma")
    odd_even_pooled_sigma = validation.get("odd_even_pooled_sigma")
    odd_even_delta = validation.get("odd_even_depth_delta")
    odd_even_depth_ratio = (
        float(odd_even_delta) / float(candidate.depth)
        if isinstance(odd_even_delta, (int, float))
        and np.isfinite(odd_even_delta)
        and candidate.depth > 0
        else None
    )
    large_pooled_parity_effect = (
        isinstance(odd_even_pooled_sigma, (int, float))
        and np.isfinite(odd_even_pooled_sigma)
        and odd_even_pooled_sigma >= config.odd_even_hard_fail_sigma
        and odd_even_depth_ratio is not None
        and odd_even_depth_ratio >= config.odd_even_large_effect_fraction
    )
    if (
        (
            isinstance(odd_even_sigma, (int, float))
            and np.isfinite(odd_even_sigma)
            and odd_even_sigma >= config.odd_even_hard_fail_sigma
        )
        or large_pooled_parity_effect
    ):
        # A hard binary verdict needs real sampling behind it: with 30-min
        # FFI cadence a transit can contribute 1-2 points per event, and a
        # median-of-few depth comparison is too noisy to reject a planet on
        # its own (DAVE ModShift's odd/even metric stays authoritative in
        # paper mode). Sparse cases stay flagged for review.
        min_points = validation.get("odd_even_min_points")
        min_events = validation.get("odd_even_min_events")
        well_sampled = (not isinstance(min_points, int) or min_points >= 6) and (
            not isinstance(min_events, int) or min_events >= 2
        )
        _add_flag(
            flags,
            "odd_even_depth_mismatch",
            "hard_fail" if well_sampled else "warning",
            "Odd/even depth mismatch exceeds sigma threshold."
            if well_sampled
            else "Odd/even depth mismatch exceeds sigma threshold, but in-transit sampling is too sparse "
            "for a hard false-positive verdict; review required.",
        )
    centroid_significance = validation.get("centroid_significance")
    if isinstance(centroid_significance, (int, float)) and np.isfinite(centroid_significance):
        if centroid_significance >= 3.0:
            _add_flag(
                flags,
                "centroid_shift",
                "warning",
                "Centroid shift exceeds 3 sigma; review source position before promotion.",
            )
        elif centroid_significance >= 2.0:
            _add_flag(flags, "centroid_shift", "warning", "Centroid shift exceeds 2 sigma.")
    else:
        centroid_shift = validation.get("centroid_shift_pixels")
        if (
            isinstance(centroid_shift, (int, float))
            and np.isfinite(centroid_shift)
            and centroid_shift > config.centroid_hard_fail_pixels
        ):
            _add_flag(flags, "centroid_shift", "warning", "Centroid shift exceeds pixel fallback threshold.")
    for validation_flag in validation.get("false_positive_flags", ()) or ():
        _add_flag(flags, str(validation_flag), "warning", "Validation marked this signal for follow-up review.")
    return flags


# Hard-fail codes that mean "required evidence is missing/incomplete", not
# "evidence says false positive". They must block promotion loudly, but a
# signal whose only hard failures are missing engines stays a reviewable TCE:
# "DAVE unavailable" is not "signal failed DAVE" (see GOAL.md engine-failure
# semantics). Evidence-against hard fails still reject outright.
MISSING_EVIDENCE_FLAG_CODES = frozenset(
    {
        "paper_tls_required",
        "dave_model_shift_required",
        "sweet_required",
        "nigraha_required",
        "nigraha_out_of_domain",
        "triceratops_required",
    }
)

# Nigraha's TESS CNN ensemble was trained on 2-minute SPOC cadence; folded
# views built from FFI-cadence data (10/30-min) are statistically outside its
# training domain and its scores there are not evidence either way.
NIGRAHA_MAX_IN_DOMAIN_CADENCE_SECONDS = 300.0

# Warnings that are review context rather than detection-quality doubts. A
# strong, otherwise-clean signal may still promote with only these present
# (Kepler/TESS triage treats catalog context and supporting-ML shortfalls as
# follow-up notes, not detection vetoes). Noise/shape warnings such as
# red_noise, low_snr, or stellar_rotation_harmonic stay promotion-blocking.
SOFT_REVIEW_WARNING_CODES = frozenset(
    {
        "catalog_contamination",
        "nigraha_low_probability",
        "known_period_low_snr",
        "planetary_secondary",
        "weak_residual_signal",
        # Red noise already deflates effective SNR via beta (Pont, Zucker &
        # Queloz 2006), and the promotion gates run on that deflated value;
        # blocking on the warning as well would double-penalize strong
        # signals on mildly variable stars.
        "red_noise",
        "odd_even_depth_mismatch",
        # Inconclusive TRICERATOPS odds withhold statistical validation (the
        # paper-grade gate still blocks on them) but are not detection-quality
        # doubts: a confirmed planet can sit in the FPP gray zone.
        "triceratops_fpp_inconclusive",
        "triceratops_nfpp_inconclusive",
    }
)


def _disposition(
    candidate, flags: list[dict], config, evidence: dict[str, Any] | None = None
) -> tuple[str, str, str, float]:
    hard_fail_codes = {flag["code"] for flag in flags if flag["severity"] == "hard_fail"}
    effective_snr = float((evidence or {}).get("effective_snr", candidate.signal_to_noise))
    final_score = float((evidence or {}).get("final_score", min(max(effective_snr / config.promotion_snr, 0.0), 1.0)))
    if hard_fail_codes - MISSING_EVIDENCE_FLAG_CODES:
        return "rejected_signal", "none", "low", min(final_score, 0.44)
    if hard_fail_codes:
        # Only missing-evidence hard fails: promotion is blocked, but the
        # signal itself was not shown to be a false positive.
        return "borderline_tce", "review_needed", "medium", min(final_score, 0.64)
    warning_codes = {flag["code"] for flag in flags if flag["severity"] == "warning"}
    only_soft_warnings = warning_codes <= SOFT_REVIEW_WARNING_CODES
    if final_score >= 0.80 and effective_snr >= config.paper_promotion_snr and only_soft_warnings:
        return "planet_candidate", "follow_up_needed", "high", final_score
    if final_score >= 0.65 and effective_snr >= config.promotion_snr and not warning_codes:
        return "planet_candidate", "follow_up_needed", "high", final_score
    if final_score >= 0.45 and effective_snr >= config.borderline_snr_min:
        return "borderline_tce", "review_needed", "medium", final_score
    if candidate.signal_to_noise >= config.borderline_snr_min:
        return "borderline_tce", "review_needed", "medium", final_score
    return "rejected_signal", "none", "low", final_score


def _payload_dict(value) -> dict:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    return dict(value)


def _paper_grade_status_from_flags(flags: list[dict]) -> str:
    if any(flag["severity"] == "hard_fail" for flag in flags):
        return "fail"
    if any(flag["severity"] == "warning" for flag in flags):
        return "review"
    return "pass"


def _apply_paper_grade_vetting(
    *,
    flags: list[dict],
    candidate,
    config,
    support: dict,
    tls: dict,
    model_shift: dict,
    sweet: dict,
    ml: dict,
    catalog_context: dict,
    fpp: dict,
    mission_upper: str,
) -> dict[str, Any]:
    thresholds = {
        "effective_snr_min": config.paper_promotion_snr,
        "tls_sde_min": config.paper_tls_sde_min,
        "min_transits": config.paper_min_transits,
        "sweet_sigma": config.paper_sweet_sigma,
        "sweet_amplitude_depth_fraction": config.paper_sweet_amplitude_depth_fraction,
        "nigraha_probability_threshold": config.paper_ml_threshold,
        "model_shift_objects": config.paper_model_shift_objects,
        "triceratops_fpp_max": config.paper_triceratops_fpp_max,
        "triceratops_nfpp_max": config.paper_triceratops_nfpp_max,
        "triceratops_fpp_reject": config.paper_triceratops_fpp_reject,
        "triceratops_nfpp_reject": config.paper_triceratops_nfpp_reject,
    }
    effective_snr = float(support.get("effective_snr", candidate.signal_to_noise))
    observed_transits = support.get("observed_transit_count")
    if effective_snr < config.paper_promotion_snr:
        _add_flag(
            flags,
            "paper_low_snr",
            "hard_fail",
            "Paper-grade mode requires Nigraha-style SNR >= 7.1 before promotion.",
        )
    if isinstance(observed_transits, int) and observed_transits < config.paper_min_transits:
        _add_flag(
            flags,
            "paper_min_transits",
            "hard_fail",
            "Paper-grade mode requires at least two observed transit events.",
        )

    tls_status = tls.get("status")
    tls_sde = _finite_float(tls.get("sde"))
    tls_count = tls.get("distinct_transit_count") or tls.get("transit_count")
    if tls_status == "complete":
        # The SDE bar is calibrated to a constant false-alarm probability for
        # this light curve's population (cadence/baseline/red-noise bin);
        # paper_tls_sde_min stays the published floor and the lookup may only
        # raise the bar above it.
        sde_gate = calibrated_sde_threshold(
            mission=mission_upper,
            cadence_seconds=support.get("cadence_seconds"),
            baseline_days=support.get("baseline_days"),
            red_noise_beta=support.get("red_noise_beta"),
            config=config,
        )
        thresholds["tls_sde_threshold_used"] = sde_gate["threshold"]
        thresholds["sde_population_bin"] = sde_gate["bin"]
        thresholds["sde_threshold_source"] = sde_gate["source"]
        thresholds["sde_table_version"] = sde_gate["table_version"]
        if tls_sde is None or tls_sde < sde_gate["threshold"]:
            _add_flag(
                flags,
                "paper_tls_sde",
                "hard_fail",
                "Full TLS search SDE is below the paper-grade threshold calibrated for this "
                "cadence/baseline/noise population.",
            )
        if isinstance(tls_count, int) and tls_count < config.paper_min_transits:
            _add_flag(
                flags,
                "paper_tls_transit_count",
                "hard_fail",
                "TLS reports fewer than two distinct transits.",
            )
    else:
        _add_flag(
            flags,
            "paper_tls_required",
            "hard_fail",
            "Full TLS evidence did not complete, so paper-grade promotion is blocked.",
        )

    if model_shift.get("status") not in {"pass", "fail"}:
        _add_flag(
            flags,
            "dave_model_shift_required",
            "hard_fail",
            "Official DAVE model-shift evidence did not complete, so paper-grade promotion is blocked.",
        )
    elif model_shift.get("hard_fail"):
        for code in model_shift.get("flags", []) or ["model_shift"]:
            _add_flag(
                flags,
                f"dave_{code}",
                "hard_fail",
                "Official DAVE model-shift vetting marked this signal as false-positive-like.",
            )

    if sweet.get("status") == "warning":
        _add_flag(
            flags,
            "sweet_sinusoid",
            "warning",
            "DAVE SWEET found a significant sinusoid at P/2, P, or 2P with amplitude comparable to the "
            "transit depth (Robovetter sine-wave-event signature).",
        )
    elif sweet.get("status") == "pass" and sweet.get("variability_detected"):
        _add_flag(
            flags,
            "stellar_variability_note",
            "info",
            "A statistically significant sinusoid exists at the tested periods but is far too small to "
            "account for the transit depth; recorded as stellar-variability context.",
        )
    elif sweet.get("status") not in {"pass", "warning"}:
        _add_flag(
            flags,
            "sweet_required",
            "hard_fail",
            "DAVE SWEET sinusoid evidence did not complete, so paper-grade promotion is blocked.",
        )

    probability = _finite_float(ml.get("probability"))
    if mission_upper == "TESS":
        if ml.get("cadence_out_of_domain"):
            # An out-of-domain score is not evidence for or against: treat it
            # as missing ML evidence rather than judging the number.
            _add_flag(
                flags,
                "nigraha_out_of_domain",
                "hard_fail",
                "Nigraha was trained on 2-minute cadence; this product's cadence is outside the model's "
                "domain, so usable TESS ML evidence is missing for paper-grade promotion.",
            )
        elif probability is None:
            _add_flag(
                flags,
                "nigraha_required",
                "hard_fail",
                "Nigraha probability did not complete for this TESS paper-grade run.",
            )
        elif probability < config.paper_ml_threshold:
            _add_flag(
                flags,
                "nigraha_low_probability",
                "warning",
                "Nigraha probability is below the upstream 0.4 paper-grade threshold.",
            )

        fpp_value = _finite_float(fpp.get("fpp"))
        nfpp_value = _finite_float(fpp.get("nfpp"))
        if fpp.get("status") != "complete" or fpp_value is None or nfpp_value is None:
            # Engine-unavailable is missing evidence, not evidence against:
            # block paper promotion loudly without branding the signal a
            # false positive (the values were never computed).
            _add_flag(
                flags,
                "triceratops_required",
                "hard_fail",
                "TRICERATOPS FPP evidence did not complete, so paper-grade promotion is blocked.",
            )
        else:
            # Giacalone et al. 2021 defines two regimes: validation
            # (FPP < 0.015 and NFPP < 0.001) and rejection (FPP > 0.5 likely
            # FP, NFPP > 0.1 likely nearby FP). In between, the statistic is
            # inconclusive — it withholds validation but is not evidence
            # against the signal, so it must not reject confirmed planets
            # whose FPP simply lands in the gray zone.
            if fpp_value > config.paper_triceratops_fpp_reject:
                _add_flag(
                    flags,
                    "triceratops_fpp",
                    "hard_fail",
                    "TRICERATOPS FPP exceeds the Giacalone et al. 2021 likely-false-positive threshold.",
                )
            elif fpp_value > config.paper_triceratops_fpp_max:
                _add_flag(
                    flags,
                    "triceratops_fpp_inconclusive",
                    "warning",
                    "TRICERATOPS FPP is above the statistical-validation threshold but below the "
                    "likely-false-positive threshold; the scenario odds are inconclusive and need review.",
                )
            if nfpp_value > config.paper_triceratops_nfpp_reject:
                _add_flag(
                    flags,
                    "triceratops_nfpp",
                    "hard_fail",
                    "TRICERATOPS nearby FPP exceeds the Giacalone et al. 2021 likely-nearby-false-positive "
                    "threshold.",
                )
            elif nfpp_value > config.paper_triceratops_nfpp_max:
                _add_flag(
                    flags,
                    "triceratops_nfpp_inconclusive",
                    "warning",
                    "TRICERATOPS nearby FPP is above the validation threshold but below the likely-nearby-"
                    "false-positive threshold; nearby-source scenarios need review.",
                )

    contamination = catalog_context.get("contamination") if isinstance(catalog_context, dict) else None
    if isinstance(contamination, dict) and contamination.get("capable_neighbor_count", 0):
        _add_flag(
            flags,
            "catalog_contamination",
            "warning",
            "TIC/Gaia catalog context found nearby sources bright enough to mimic the observed depth.",
        )

    return {
        "status": _paper_grade_status_from_flags(flags),
        "pass": _paper_grade_status_from_flags(flags) == "pass",
        "thresholds": thresholds,
        "methods": [
            "wotan_biweight",
            "tls_primary_search",
            "profiled_bls",
            "tls_full_search",
            "dave_model_shift",
            "dave_sweet",
            "tic_gaia_contamination",
            "triceratops_fpp",
            "mission_ml",
        ],
    }


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
    nigraha_threshold: float | None = None,
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
            if nigraha_threshold is None:
                verdict = tess_service.predict(tensors)
            else:
                try:
                    verdict = tess_service.predict(tensors, threshold=nigraha_threshold)
                except TypeError:
                    verdict = tess_service.predict(tensors)
            ml = _payload_dict(verdict)
            if nigraha_threshold is not None:
                probability = _finite_float(ml.get("probability"))
                ml["threshold"] = nigraha_threshold
                ml["threshold_source"] = "ExoplanetML/Nigraha gen_predict.sh"
                if probability is not None:
                    ml["label"] = "planet-candidate" if probability >= nigraha_threshold else "not-transit-like"
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
            ml = _payload_dict(service.predict(tensors))
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
            ml = _payload_dict(k2_service.predict(exomac_features))
        else:
            raise AssertionError(f"unreachable mission branch: {mission_upper}")
        ml = attach_probability_calibration(ml, mission_upper)
    except (ModelArtifactError, KeyError, FileNotFoundError, RuntimeError, ImportError, ValueError) as exc:
        ml = _ml_unavailable_payload(mission_upper, exc)
    return ml, service, tess_service, k2_service


def _attach_ml_domain_evidence(
    ml: dict,
    *,
    mission_upper: str,
    flags: list[dict],
    physics: dict[str, Any],
) -> dict:
    next_ml = dict(ml)
    training_domain = {
        "TESS": "Nigraha TESS CNN ensemble over global, local, odd/even views and stellar scalar features",
        "KEPLER": "AstroNet-style Kepler global and local folded light-curve views",
        "K2": "ExoMAC-KKT tabular candidate and stellar-context feature domain",
    }.get(mission_upper, "unknown")
    probability = _finite_float(next_ml.get("probability"))
    calibrated = _finite_float(next_ml.get("calibrated_ml_probability"))
    ood_reasons: list[str] = []
    if next_ml.get("cadence_out_of_domain"):
        ood_reasons.append("cadence_out_of_training_domain")
    if next_ml.get("preprocessing_compatible") is False:
        ood_reasons.append("preprocessing_incompatible")
    imputed = next_ml.get("imputed_features")
    if isinstance(imputed, (list, tuple)) and len(imputed) >= 4:
        ood_reasons.append("many_imputed_stellar_features")
    if probability is None:
        ood_reasons.append("no_model_score")
    if physics.get("stellar_context_source") == "solar_like_fallback":
        ood_reasons.append("fallback_stellar_context")

    hard_flags = [flag.get("code") for flag in flags if flag.get("severity") == "hard_fail"]
    warning_flags = [flag.get("code") for flag in flags if flag.get("severity") == "warning"]
    label = str(next_ml.get("label") or "")
    conflicts: list[str] = []
    if probability is not None and probability >= float(next_ml.get("threshold") or 0.5) and hard_flags:
        conflicts.append("ml_support_conflicts_with_hard_vetting_flags")
    if probability is not None and probability >= 0.5 and physics.get("planet_radius_earth"):
        radius = _finite_float(physics.get("planet_radius_earth"))
        if radius is not None and radius > 30.0:
            conflicts.append("ml_support_conflicts_with_implausible_planet_radius")
    if "not-transit-like" in label and not hard_flags and probability is not None and probability < 0.5:
        conflicts.append("ml_low_score_without_hard_vetting_failure")

    ood_score = min(1.0, len(ood_reasons) / 4.0)
    next_ml["domain_awareness"] = {
        "status": "inconclusive" if ood_reasons else "passed",
        "model_training_domain": training_domain,
        "model_score": probability,
        "calibrated_score": calibrated,
        "out_of_distribution_score": ood_score,
        "out_of_distribution_reasons": ood_reasons,
        "tensor_checksum": next_ml.get("input_tensor_checksum"),
        "artifact_checksum": next_ml.get("checksum"),
    }
    next_ml["evidence_conflicts"] = {
        "status": "inconclusive" if conflicts else "passed",
        "conflicts": conflicts,
        "hard_vetting_flags": hard_flags,
        "warning_vetting_flags": warning_flags,
    }
    return next_ml


def _difference_image_anchoring(
    *,
    tpf_metadata: dict | None,
    pixel_flux: np.ndarray | None,
    mission_upper: str,
    target_id: str,
    paper_grade_mode: bool,
) -> tuple:
    """Pre-compute target_pixel, neighbor_pixels, and prf_kernel for PRF centroiding.

    Returns (target_pixel, neighbor_pixels, prf_kernel), any of which may be None.
    Failures are silent: missing WCS or network errors degrade to None without
    breaking the analysis run.
    """
    if tpf_metadata is None or pixel_flux is None:
        return None, None, None

    target_row = tpf_metadata.get("target_pixel_row")
    target_col = tpf_metadata.get("target_pixel_col")
    target_pixel = (
        (float(target_row), float(target_col)) if (target_row is not None and target_col is not None) else None
    )

    prf_kernel = None
    if mission_upper == "TESS":
        camera = tpf_metadata.get("tess_camera")
        ccd = tpf_metadata.get("tess_ccd")
        sector = tpf_metadata.get("tess_sector")
        pixel_flux_arr = np.asarray(pixel_flux)
        ccd_row = float(target_row) if target_row is not None else None
        ccd_col = float(target_col) if target_col is not None else None
        prf_kernel = load_tess_prf_kernel(
            camera=camera, ccd=ccd, sector=sector, ccd_row=ccd_row, ccd_col=ccd_col
        )
    elif mission_upper in ("KEPLER", "K2"):
        channel = tpf_metadata.get("kepler_channel")
        pixel_flux_arr = np.asarray(pixel_flux)
        shape = pixel_flux_arr.shape[1:] if pixel_flux_arr.ndim == 3 else (11, 11)
        ccd_row = float(target_row) if target_row is not None else None
        ccd_col = float(target_col) if target_col is not None else None
        prf_kernel = load_kepler_prf_kernel(
            channel=channel, shape=shape, corner_column=ccd_col, corner_row=ccd_row
        )

    neighbor_pixels = None
    # Neighbor pixels require WCS to transform catalog RA/Dec into pixel coords.
    target_ra = tpf_metadata.get("target_ra")
    target_dec = tpf_metadata.get("target_dec")
    wcs_matrix = tpf_metadata.get("wcs_pixel_scale_matrix")
    if (
        paper_grade_mode
        and mission_upper == "TESS"
        and target_ra is not None
        and target_dec is not None
        and wcs_matrix is not None
        and target_pixel is not None
    ):
        try:
            from orbitlab.science.catalog_context import query_tic_catalog_context

            estimated_depth = 0.01  # placeholder; neighbor query not depth-filtered
            catalog = query_tic_catalog_context(target_id, observed_depth=estimated_depth)
            neighbors_raw = catalog.get("neighbors") if isinstance(catalog, dict) else None
            if neighbors_raw:
                # WCS linear transform: Δpixel = inv(scale_matrix) @ [Δra*cos(dec), Δdec]
                m = np.asarray(wcs_matrix, dtype=np.float64)  # degrees/pixel
                try:
                    m_inv = np.linalg.inv(m)
                except np.linalg.LinAlgError:
                    m_inv = None
                if m_inv is not None:
                    cos_dec = np.cos(np.radians(float(target_dec)))
                    neighbor_pixels = []
                    for nb in neighbors_raw:
                        nb_ra = nb.get("ra")
                        nb_dec = nb.get("dec")
                        if nb_ra is None or nb_dec is None:
                            continue
                        delta_ra_deg = (float(nb_ra) - float(target_ra)) * cos_dec
                        delta_dec_deg = float(nb_dec) - float(target_dec)
                        delta_pix = m_inv @ np.array([delta_ra_deg, delta_dec_deg])
                        nb_row = float(target_pixel[0]) + float(delta_pix[1])
                        nb_col = float(target_pixel[1]) + float(delta_pix[0])
                        neighbor_pixels.append({
                            "tic_id": nb.get("tic_id") or nb.get("id"),
                            "pixel_row": nb_row,
                            "pixel_col": nb_col,
                            "tmag": nb.get("tmag"),
                            "separation_arcsec": nb.get("separation_arcsec"),
                        })
        except Exception:
            neighbor_pixels = None

    return target_pixel, neighbor_pixels, prf_kernel


def analyze_light_curve_arrays(
    *,
    target_id: str,
    mission: str,
    product_uri: str | None = None,
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
    request_min_period: float | None = None,
    request_max_period: float | None = None,
    max_candidates: int = 4,
    vetting_mode: str = "paper",
    search_profile: str | None = None,
    ml_service: AstroNetService | None = None,
    nigraha_service: NigrahaService | None = None,
    k2_service: ExoMACService | None = None,
    pixel_flux: np.ndarray | None = None,
    aperture_mask: np.ndarray | None = None,
    pixel_scale_arcsec: float | None = None,
    tpf_metadata: dict | None = None,
    sector_observations: list[SectorObservation] | None = None,
) -> dict:
    config = load_science_config()
    paper_grade_mode = vetting_mode == "paper"
    if search_profile:
        profile_name = search_profile
    elif paper_grade_mode:
        profile_name = "paper_grade"
    elif vetting_mode == "deep":
        profile_name = "science_deep"
    else:
        profile_name = "science_standard"
    profile = get_search_profile(config, profile_name)
    profile, period_window_request = _apply_request_period_window(
        profile,
        request_min_period=request_min_period,
        request_max_period=request_max_period,
    )
    clean_time, clean_flux = clean_light_curve(time, flux, quality)
    detrending = {"status": "skipped", "engine": "wotan"}
    if paper_grade_mode:
        clean_flux, detrending = detrend_with_wotan(clean_time, clean_flux, method="biweight")
    data_quality = _data_quality_payload(np.asarray(time), np.asarray(flux), quality, clean_time, clean_flux)
    known_target = resolve_known_target(target_id)
    mission_upper = mission.upper()
    target_pixel, neighbor_pixels, prf_kernel = _difference_image_anchoring(
        tpf_metadata=tpf_metadata,
        pixel_flux=pixel_flux,
        mission_upper=mission_upper,
        target_id=target_id,
        paper_grade_mode=paper_grade_mode,
    )

    try:
        primary, bls_result, guided_candidates = _select_primary_candidate(
            clean_time, clean_flux, known_target, config, profile
        )
    except TypeError:
        # Some tests monkeypatch run_bls with the old narrow signature.
        bls_result = run_bls(clean_time, clean_flux)
        guided_candidates = []
        bls_result.metadata.update({"guided_known_candidates": 0, "known_target": known_target_payload(known_target)})
        known_planet = match_known_planet(known_target, bls_result.candidate.period)
        primary = _candidate_with_metadata(
            bls_result.candidate,
            period_source="blind_bls",
            signal_origin="broad_periodogram",
            catalog_match=_known_planet_payload(known_target, known_planet, bls_result.candidate),
            is_residual=False,
            display_priority=10,
        )
    bls_result.metadata.update(
        {
            "search_profile": profile.name,
            "search_profile_warning": profile.warning,
            "period_samples_requested": profile.period_samples,
            "detrending": detrending,
        }
    )
    paper_tls_primary: dict[str, Any] | None = None
    if paper_grade_mode:
        paper_tls_primary = search_with_tls(
            clean_time,
            clean_flux,
            min_period=profile.min_period,
            max_period=profile.max_period,
            stellar_radius_solar=stellar_radius_solar,
            stellar_mass_solar=stellar_mass_solar,
            transit_depth_min=10e-6,
            n_transits_min=config.paper_min_transits,
            oversampling_factor=3,
            duration_grid_step=1.1,
        )
        primary = _tls_primary_candidate(paper_tls_primary)
        bls_result.metadata["paper_tls_primary"] = paper_tls_primary

    residual_candidates = find_multi_planet_candidates(
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
    ledger_candidates = list(residual_candidates[:1])
    for guided_candidate in guided_candidates[1:]:
        if len(ledger_candidates) >= max_candidates:
            break
        if not _candidate_duplicate(guided_candidate, ledger_candidates):
            ledger_candidates.append(guided_candidate)
    for residual_candidate in residual_candidates[1:]:
        if len(ledger_candidates) >= max_candidates:
            break
        if not _candidate_duplicate(residual_candidate, ledger_candidates):
            ledger_candidates.append(residual_candidate)
    ledger_candidates = _annotate_ledger_candidates(ledger_candidates, known_target)

    folded_curves: dict[str, dict[str, list[float]]] = {}
    tce_payloads = []
    planet_candidate_payloads = []
    if mission_upper not in {"TESS", "KEPLER", "K2"}:
        raise ValueError(f"unsupported mission: {mission}")
    consistency_observations = sector_observations or [
        SectorObservation(
            sector_id=infer_sector_id(product_uri),
            time=clean_time,
            flux=clean_flux,
            quality=None,
            pixel_flux=pixel_flux,
            aperture_mask=aperture_mask,
            pixel_scale_arcsec=pixel_scale_arcsec,
        )
    ]

    service = ml_service
    tess_service = nigraha_service
    promoted_candidates = []
    evaluated_candidates = []
    primary_signal_to_noise = ledger_candidates[0].signal_to_noise if ledger_candidates else 0.0
    tls_results: dict[str, dict] = {}

    # Resolve the host-star scalar context once (job -> known_target -> TIC), so
    # the TESS ML surface (Nigraha) receives real stellar features instead of
    # collapsing on solar-default imputation. A live TIC stellar lookup runs only
    # for TESS, only when something is still missing, and never fails the run.
    job_stellar_context = {
        "teff": stellar_teff,
        "radius_solar": stellar_radius_solar,
        "logg": stellar_logg,
        "mass_solar": stellar_mass_solar,
        "luminosity_solar": stellar_luminosity_solar,
        "density_solar": stellar_density_solar,
    }
    catalog_stellar: dict[str, Any] | None = None
    catalog_stellar_status = "not_queried"
    if mission_upper == "TESS":
        needs_catalog = any(
            _positive(value) is None
            for value in (stellar_teff, stellar_radius_solar, stellar_mass_solar, stellar_logg)
        )
        known_has_all = bool(
            known_target is not None
            and _positive(getattr(known_target, "stellar_teff", None)) is not None
            and _positive(getattr(known_target, "stellar_radius_solar", None)) is not None
            and _positive(getattr(known_target, "stellar_mass_solar", None)) is not None
        )
        if needs_catalog and not known_has_all:
            try:
                catalog_stellar = query_tic_stellar_context(target_id)
                catalog_stellar_status = "complete"
            except Exception as exc:  # network/catalog failures must not break analysis
                catalog_stellar = None
                catalog_stellar_status = f"unavailable: {exc}"
    effective_stellar, stellar_context_source = _effective_stellar_context(
        job_stellar=job_stellar_context,
        known_target=known_target,
        catalog_stellar=catalog_stellar,
    )
    stellar_context_source["catalog_lookup_status"] = catalog_stellar_status

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
            stellar_radius_solar=effective_stellar["radius_solar"],
            stellar_mass_solar=effective_stellar["mass_solar"],
            stellar_teff=effective_stellar["teff"],
            provenance=stellar_context_source,
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
        difference_image = difference_image_diagnostics(
            time=clean_time,
            pixel_flux=pixel_flux,
            candidate=candidate,
            pixel_scale_arcsec=pixel_scale_arcsec,
            target_pixel=target_pixel,
            neighbor_pixels=neighbor_pixels,
            prf_kernel=prf_kernel,
        )
        centroid_shift_pixels = difference_image.get("centroid_shift_pixels")
        centroid_uncertainty_pixels = difference_image.get("centroid_uncertainty_pixels")
        vetting_time, vetting_flux, masked_siblings = _vetting_arrays_for_candidate(
            clean_time, clean_flux, candidate, ledger_candidates
        )
        validation = asdict(
            validate_candidate(
                vetting_time,
                vetting_flux,
                candidate,
                centroid_shift_pixels=centroid_shift_pixels,
                centroid_uncertainty_pixels=centroid_uncertainty_pixels,
                stellar_rotation_period=stellar_rotation_period,
                low_snr_threshold=config.promotion_snr,
            )
        )
        validation["sibling_signals_masked"] = masked_siblings
        covered_transits = _observed_transit_count(bls_result.search_time, candidate)
        observed_transits = _supported_transit_count(
            bls_result.search_time,
            bls_result.search_flux,
            candidate,
            min_depth_fraction=config.transit_support_depth_fraction,
        )
        period_alias_code = _period_alias_code(candidate, evaluated_candidates)
        alias_flags = [period_alias_code] if period_alias_code else []
        red_noise_beta = estimate_red_noise_beta(
            out_of_transit_residuals(bls_result.search_time, bls_result.search_flux, candidate)
        )
        effective_snr = candidate.signal_to_noise / red_noise_beta if red_noise_beta else candidate.signal_to_noise
        candidate_metadata = dict(candidate.metadata or {})
        catalog_match = candidate_metadata.get("catalog_match")
        support = {
            "observed_transit_count": observed_transits,
            "covered_transit_count": covered_transits,
            "period_alias_code": period_alias_code,
            "candidate_rank": index,
            "primary_signal_to_noise": primary_signal_to_noise,
            "effective_snr": effective_snr,
            "red_noise_beta": red_noise_beta,
            "cadence_seconds": _cadence_days_from_time(clean_time) * 86400.0,
            "baseline_days": float(np.nanmax(clean_time) - np.nanmin(clean_time)),
            "quality_flag_fraction": data_quality["quality_flag_fraction"],
            "is_residual": bool(candidate_metadata.get("is_residual")),
            "known_planet": catalog_match,
            "planetary_secondary_allowed": bool(
                isinstance(catalog_match, dict) and catalog_match.get("allow_planetary_secondary")
            ),
        }
        flags = _structured_flags(candidate, validation, config, support)
        if difference_image.get("transit_source_neighbor"):
            nb = difference_image["transit_source_neighbor"]
            nb_id = nb.get("tic_id") or "unknown"
            nb_sigma = nb.get("target_offset_sigma") or 0.0
            _add_flag(
                flags,
                "centroid_neighbor_source",
                "hard_fail",
                f"Transit source localizes {nb_sigma:.1f}σ from target and within fit uncertainty of "
                f"catalogued neighbor TIC {nb_id}: pixel contamination evidence against on-target transit.",
            )
        ml, service, tess_service, k2_service = _ml_payload_for_candidate(
            mission_upper=mission_upper,
            clean_time=clean_time,
            clean_flux=clean_flux,
            candidate=candidate,
            physics=physics,
            stellar_teff=effective_stellar["teff"],
            stellar_radius_solar=effective_stellar["radius_solar"],
            stellar_logg=effective_stellar["logg"],
            stellar_mass_solar=effective_stellar["mass_solar"],
            stellar_luminosity_solar=effective_stellar["luminosity_solar"],
            stellar_density_solar=effective_stellar["density_solar"],
            service=service,
            tess_service=tess_service,
            k2_service=k2_service,
            nigraha_threshold=config.paper_ml_threshold if paper_grade_mode and mission_upper == "TESS" else None,
        )
        ml["stellar_context_source"] = dict(stellar_context_source)
        cadence_seconds = _cadence_days_from_time(clean_time) * 86400.0
        ml["cadence_seconds"] = cadence_seconds
        if mission_upper == "TESS" and cadence_seconds > NIGRAHA_MAX_IN_DOMAIN_CADENCE_SECONDS:
            ml["cadence_out_of_domain"] = True
            ml["domain_label"] = ml.get("label")
            ml["label"] = "out-of-domain"
            ml["domain_note"] = (
                "Nigraha was trained on 2-minute SPOC cadence; this product's cadence is outside the "
                "model's training domain, so the score is not usable evidence."
            )
        model_shift = {"status": "skipped", "engine": "dave_model_shift"}
        sweet = {"status": "skipped", "engine": "sweet"}
        catalog_context = {
            "status": "skipped",
            "tic": target_id if mission_upper == "TESS" else None,
            "known_target": known_target_payload(known_target),
        }
        fpp = {"status": "skipped", "engine": "triceratops"}
        detrending_sensitivity = {"status": "not_assessed", "engine": "detrending_sensitivity"}
        sector_consistency = summarize_sector_consistency(candidate, consistency_observations)
        paper_grade = None
        if paper_grade_mode:
            tls_results[candidate_id] = (
                paper_tls_primary
                if index == 1 and paper_tls_primary is not None
                else search_with_tls(
                    clean_time,
                    clean_flux,
                    min_period=profile.min_period,
                    max_period=profile.max_period,
                    stellar_radius_solar=stellar_radius_solar,
                    stellar_mass_solar=stellar_mass_solar,
                    transit_depth_min=10e-6,
                    n_transits_min=config.paper_min_transits,
                    oversampling_factor=3,
                    duration_grid_step=1.1,
                )
            )
            model_shift = run_model_shift(
                vetting_time,
                vetting_flux,
                candidate,
                objects_evaluated=config.paper_model_shift_objects,
            )
            sweet = run_sweet_test(
                vetting_time,
                vetting_flux,
                candidate,
                threshold_sigma=config.paper_sweet_sigma,
                amplitude_depth_fraction=config.paper_sweet_amplitude_depth_fraction,
            )
            if mission_upper == "TESS":
                catalog_context = query_tic_catalog_context(
                    target_id,
                    observed_depth=candidate.depth,
                    search_radius_arcsec=config.paper_catalog_radius_arcsec,
                )
                try:
                    fpp = run_triceratops_fpp(
                        target_id=target_id,
                        product_uri=product_uri,
                        time=clean_time,
                        flux=clean_flux,
                        candidate=candidate,
                        aperture_mask=aperture_mask,
                        samples=config.paper_triceratops_samples,
                        parallel=True,
                    )
                except Exception as exc:
                    fpp = {
                        "status": "failed",
                        "engine": "triceratops",
                        "detail": str(exc),
                        "source": "TRICERATOPS calc_probs",
                        "samples": config.paper_triceratops_samples,
                        "validation_thresholds": {
                            "fpp_max": config.paper_triceratops_fpp_max,
                            "nfpp_max": config.paper_triceratops_nfpp_max,
                        },
                    }
            paper_grade = _apply_paper_grade_vetting(
                flags=flags,
                candidate=candidate,
                config=config,
                support=support,
                tls=tls_results[candidate_id],
                model_shift=model_shift,
                sweet=sweet,
                ml=ml,
                catalog_context=catalog_context,
                fpp=fpp,
                mission_upper=mission_upper,
            )
        if vetting_mode in {"deep", "paper"}:
            try:
                detrending_sensitivity = run_detrending_sensitivity(clean_time, clean_flux, candidate)
            except (RuntimeError, ValueError, ImportError) as exc:
                detrending_sensitivity = {
                    "status": "failed",
                    "engine": "detrending_sensitivity",
                    "detail": str(exc),
                }
        ml = _attach_ml_domain_evidence(ml, mission_upper=mission_upper, flags=flags, physics=physics)
        science_readiness = _candidate_science_readiness(
            result_kind="analysis",
            vetting_mode=vetting_mode,
            flags=flags,
            physics=physics,
            paper_grade=paper_grade,
            fpp=fpp,
            sector_consistency=sector_consistency,
            detrending_sensitivity=detrending_sensitivity,
            ml=ml,
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
        elif paper_grade_mode:
            evidence["tls"] = tls_results[candidate_id]
            evidence["model_shift"] = model_shift
            evidence["sweet"] = sweet
            evidence["paper_grade"] = paper_grade
        disposition, action_label, confidence_band, disposition_score = _disposition(candidate, flags, config, evidence)
        if science_readiness.get("status") == "blocked" and disposition == "planet_candidate":
            disposition = "borderline_tce"
            action_label = "review_needed"
            confidence_band = "medium"
            disposition_score = min(disposition_score, 0.64)
            evidence["explanation"] = list(evidence.get("explanation") or [])
            evidence["explanation"].append("Science-readiness blockers prevent planet-candidate promotion.")

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
            "model_depth_fraction": candidate_metadata.get("model_depth_fraction"),
            "measured_depth_fraction": candidate_metadata.get("measured_depth_fraction"),
            "bls_power": candidate.power,
            "bls_snr": candidate.signal_to_noise,
            "raw_snr": candidate.signal_to_noise,
            "red_noise_beta": evidence["red_noise_beta"],
            "effective_snr": evidence["effective_snr"],
            "sde": candidate.power,
            "local_noise_snr": evidence["effective_snr"],
            "duration_period_ratio": duration_period_ratio,
            "transit_count": observed_transits,
            "covered_transit_count": covered_transits,
            "phase_coverage_score": evidence["phase_coverage_score"],
            "alias_flags": alias_flags,
            "period_source": candidate_metadata.get("period_source", "blind_bls"),
            "depth_source": candidate_metadata.get("depth_source"),
            "signal_origin": candidate_metadata.get("signal_origin", "broad_periodogram"),
            "catalog_match": catalog_match,
            "is_residual": bool(candidate_metadata.get("is_residual")),
            "display_priority": int(candidate_metadata.get("display_priority", index * 10)),
            "secondary_context": {
                "planetary_secondary_allowed": bool(support.get("planetary_secondary_allowed")),
                "secondary_depth_ratio": (
                    _finite_float(validation.get("secondary_depth") / max(candidate.depth, np.finfo(float).eps))
                    if isinstance(validation.get("secondary_depth"), (int, float))
                    and np.isfinite(validation.get("secondary_depth"))
                    and validation.get("secondary_depth") > 0
                    else None
                ),
            },
            "disposition": disposition,
            "action_label": action_label,
            "disposition_score": disposition_score,
            "final_score": evidence["final_score"],
            "confidence_band": confidence_band,
            "flags": flags,
            "science_readiness": science_readiness,
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
                "covered_transit_count": covered_transits,
                "local_noise_snr": evidence["effective_snr"],
                "duration_period_ratio": duration_period_ratio,
                "phase_coverage_score": evidence["phase_coverage_score"],
                "alias_flags": alias_flags,
                "candidate_rank": index,
                "primary_signal_to_noise": primary_signal_to_noise,
                "tls_sde": _finite_float(tls_results.get(candidate_id, {}).get("sde")),
                "paper_grade_pass": paper_grade.get("pass") if isinstance(paper_grade, dict) else None,
                "paper_grade_status": paper_grade.get("status") if isinstance(paper_grade, dict) else None,
                "period_source": candidate_metadata.get("period_source", "blind_bls"),
                "depth_source": candidate_metadata.get("depth_source"),
                "model_depth_fraction": candidate_metadata.get("model_depth_fraction"),
                "measured_depth_fraction": candidate_metadata.get("measured_depth_fraction"),
                "signal_origin": candidate_metadata.get("signal_origin", "broad_periodogram"),
                "catalog_match": catalog_match,
                "is_residual": bool(candidate_metadata.get("is_residual")),
                "display_priority": int(candidate_metadata.get("display_priority", index * 10)),
            },
            "aperture_stability": aperture_stability_diagnostics(
                time=clean_time,
                pixel_flux=pixel_flux,
                candidate=candidate,
                selected_mask=aperture_mask,
                percentiles=config.aperture_percentiles,
            ),
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
                    "centroid_shift_arcsec": _finite_float(difference_image.get("centroid_shift_arcsec")),
                },
                "difference_image": difference_image,
                "quality_cadence_dominance": {
                    "status": "warning"
                    if data_quality["quality_flag_fraction"] >= config.quality_flag_dominance_fraction
                    else "pass",
                    "quality_flag_fraction": data_quality["quality_flag_fraction"],
                    "threshold": config.quality_flag_dominance_fraction,
                },
                "model_shift": model_shift,
                "sweet": sweet,
                "paper_grade": paper_grade,
                "detrending_sensitivity": detrending_sensitivity,
                "sector_consistency": sector_consistency,
            },
            "detrending_sensitivity": detrending_sensitivity,
            "sector_consistency": sector_consistency,
            "catalog_context": catalog_context | {"known_target": known_target_payload(known_target)},
            "fpp": fpp,
            "physics": physics,
            "validation": validation,
            "ml": ml,
        }
        tce_payloads.append(tce_payload)
        evaluated_candidates.append(candidate)
        if disposition == "planet_candidate":
            planet_candidate_payloads.append(tce_payload)
            promoted_candidates.append(candidate)

    injection_recovery = {"status": "skipped", "engine": "injection_recovery"}
    if vetting_mode in {"deep", "paper"}:
        injection_recovery = run_injection_recovery(
            clean_time,
            clean_flux,
            injection_models=("box", "tls_like"),
            tolerance_fraction=config.forced_period_tolerance_fraction,
        )

    config_audit = config_usage_audit()
    if vetting_mode == "fast":
        tls_status = "skipped"
    elif any(result.get("status") == "complete" for result in tls_results.values()):
        tls_status = "complete"
    elif tls_results:
        tls_status = "failed"
    else:
        tls_status = "skipped"
    triceratops_status = "skipped"
    if paper_grade_mode and mission_upper == "TESS":
        triceratops_status = (
            "complete"
            if tce_payloads and all(tce.get("fpp", {}).get("status") == "complete" for tce in tce_payloads)
            else "failed"
        )
    elif paper_grade_mode:
        triceratops_status = "not_applicable"
    detrending_sensitivity_status = "skipped"
    if vetting_mode in {"deep", "paper"}:
        sensitivity_statuses = [
            tce.get("detrending_sensitivity", {}).get("status")
            for tce in tce_payloads
            if isinstance(tce.get("detrending_sensitivity"), dict)
        ]
        if sensitivity_statuses and all(status == "passed" for status in sensitivity_statuses):
            detrending_sensitivity_status = "passed"
        elif any(status == "failed" for status in sensitivity_statuses):
            detrending_sensitivity_status = "failed"
        elif any(status == "unstable_result" for status in sensitivity_statuses):
            detrending_sensitivity_status = "unstable_result"
        elif sensitivity_statuses:
            detrending_sensitivity_status = "inconclusive"
    sector_statuses = [
        tce.get("sector_consistency", {}).get("multi_sector_status")
        for tce in tce_payloads
        if isinstance(tce.get("sector_consistency"), dict)
    ]
    if any(status == "inconsistent" for status in sector_statuses):
        sector_consistency_status = "inconsistent"
    elif any(status == "consistent" for status in sector_statuses):
        sector_consistency_status = "consistent"
    elif any(status == "single_sector_only" for status in sector_statuses):
        sector_consistency_status = "single_sector_only"
    elif sector_statuses:
        sector_consistency_status = "insufficient_data"
    else:
        sector_consistency_status = "skipped"
    engine_status = {
        "bls": {"status": "complete", "search_profile": profile.name},
        "tls": {"status": tls_status},
        "injection_recovery": {"status": injection_recovery["status"]},
        "wotan": detrending,
        "detrending_sensitivity": {"status": detrending_sensitivity_status},
        "sector_consistency": {"status": sector_consistency_status},
        "triceratops": {"status": triceratops_status},
        "dave_model_shift": {"status": "complete" if paper_grade_mode and tce_payloads else "skipped"},
        "sweet": {"status": "complete" if paper_grade_mode and tce_payloads else "skipped"},
        "paper_grade": {"status": "complete" if paper_grade_mode else "skipped"},
        "ml": {"status": "complete" if tce_payloads else "skipped"},
    }
    enrichment_steps = []
    if vetting_mode == "deep":
        enrichment_steps = ["tls_refinement", "detrending_sensitivity", "sector_consistency", "injection_recovery"]
    elif paper_grade_mode:
        enrichment_steps = [
            "tls_full_search",
            "dave_model_shift",
            "dave_sweet",
            "paper_thresholds",
            "detrending_sensitivity",
            "sector_consistency",
            "injection_recovery",
        ]
    operative_min_transits = config.paper_min_transits if paper_grade_mode else profile.min_transits
    period_window_note = _baseline_period_note(
        baseline_days=data_quality["baseline_days"],
        max_period=profile.max_period,
        min_transits=operative_min_transits,
    )
    period_window = dict(period_window_request)
    period_window["min_transits_required"] = float(operative_min_transits)
    return {
        "schema_version": "orbitlab.analysis_result.v2",
        "pipeline_version": "orbitlab-stormbreaker-0.2.0",
        "science_config_hash": science_config_hash(),
        **config_audit,
        "target_id": target_id,
        "mission": mission,
        "vetting_mode": vetting_mode,
        "search_profile": profile.name,
        "period_window": period_window,
        "period_window_note": period_window_note,
        "data_quality": data_quality,
        "tces": tce_payloads,
        "planet_candidates": planet_candidate_payloads,
        "science_readiness": _summarize_science_readiness(
            tce_payloads,
            result_kind="analysis",
            vetting_mode=vetting_mode,
        ),
        "validation_status": "complete",
        "engine_status": engine_status,
        "deep_mode_progress": {
            "mode": vetting_mode,
            "complete": vetting_mode == "fast" or injection_recovery["status"] in {"complete", "skipped"},
            "steps": ["profiled_bls", "tce_ledger", "core_vetting", "evidence_scoring", "ml_calibration"]
            + enrichment_steps,
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
            "effective_radius_solar": effective_stellar["radius_solar"] or 1.0,
            "effective_mass_solar": effective_stellar["mass_solar"] or 1.0,
            "effective_teff": effective_stellar["teff"] or 5778.0,
            "provenance": dict(stellar_context_source),
            "physics_source": _stellar_context_for_physics(
                stellar_radius_solar=effective_stellar["radius_solar"],
                stellar_mass_solar=effective_stellar["mass_solar"],
                stellar_teff=effective_stellar["teff"],
                provenance=stellar_context_source,
            )[3],
        },
        "preprocessing": bls_result.metadata,
    }
